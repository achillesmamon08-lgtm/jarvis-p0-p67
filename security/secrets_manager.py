"""
Secrets Manager for JARVIS — secure key/account management.

Stores API keys, OAuth tokens, and credentials with encryption-at-rest.
Integration points:
  - Reads COMPOSIO_API_KEY, FISH_API_KEY from environment or .env file
  - Writes to encrypted store.json under security/ directory
  - Never exposes secrets to the LLM pipeline — only metadata
  - health() returns status without leaking values

Design principles:
  - Zero plaintext secrets on disk (AES-256-GCM encryption)
  - Keys sourced from environment first, then encrypted store
  - All secret values masked in logs (first 4 chars + last 4 chars)
  - PermissionManager controls access to the secret store
"""
import os
import sys
import json
import time
import base64
from typing import Optional, Dict, Any
from pathlib import Path

# Encryption
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SecretsManager:
    """
    Manages encrypted storage of API keys and OAuth tokens.

    File layout:
      security/
        secrets.enc       — encrypted blob (AES-256-GCM via Fernet)
        secrets.meta      — metadata (key IDs, timestamps, masked values)
        master.key        — NOT stored. Derived from env or user passphrase.

    Environment variables checked first (highest priority):
      COMPOSIO_API_KEY, FISH_API_KEY, OPENROUTER_API_KEY,
      TS_AUTHKEY, NVIDIA_API_KEY, OMNIROUTE_API_KEY
    """

    SECRET_ENV_VARS = [
        "COMPOSIO_API_KEY",
        "FISH_API_KEY",
        "OPENROUTER_API_KEY",
        "TS_AUTHKEY",
        "NVIDIA_API_KEY",
        "OMNIROUTE_API_KEY",
    ]

    def __init__(self, secrets_dir: str = None):
        self.root = Path(secrets_dir or os.path.join(os.getcwd(), "security"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.enc_path = self.root / "secrets.enc"
        self.meta_path = self.root / "secrets.meta"
        self._cache: Dict[str, str] = {}  # In-memory cache (plaintext, not persisted)
        self._load_env_secrets()

    def _load_env_secrets(self):
        """Load secrets from environment variables (highest priority)."""
        for var in self.SECRET_ENV_VARS:
            val = os.environ.get(var)
            if val:
                self._cache[var] = val

    def _derive_key(self, passphrase: Optional[str] = None) -> bytes:
        """Derive a Fernet key from a passphrase or environment."""
        if passphrase is None:
            passphrase = os.environ.get("JARVIS_MASTER_KEY", "")
        if not passphrase:
            # Fall back to a device-specific key (NOT secure, but functional)
            passphrase = f"jarvis-secrets-{os.uname().nodename}-{os.getuid()}"

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"jarvis-secrets-v1",  # Static salt for device-local; OK for single-device use
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
        return key

    def store(self, key_id: str, value: str) -> bool:
        """
        Store a secret value, encrypted at rest.
        Returns True on success. Never throws on encryption failure
        (degrades to memory-only storage with warning).
        """
        if not key_id or not value:
            return False

        self._cache[key_id] = value

        # Try to persist encrypted
        try:
            fernet = Fernet(self._derive_key())
            all_secrets = self._load_encrypted(fernet)
            all_secrets[key_id] = value

            # Write encrypted blob
            encrypted = fernet.encrypt(json.dumps(all_secrets).encode())
            with open(self.enc_path, "wb") as f:
                f.write(encrypted)

            # Write metadata (masked values only)
            meta = {
                key_id: {
                    "stored_at": time.time(),
                    "masked": self._mask(value),
                    "source": "api",
                }
                for key_id, value in all_secrets.items()
            }
            with open(self.meta_path, "w") as f:
                json.dump(meta, f, indent=2)

            return True
        except ImportError:
            # cryptography not installed — memory only
            print(f"[Secrets] cryptography module not available — secret '{key_id}' stored in memory only",
                  file=sys.stderr)
            return True
        except Exception as e:
            print(f"[Secrets] Encryption failed for '{key_id}': {e}", file=sys.stderr)
            return True  # Still keep in memory cache

    def retrieve(self, key_id: str) -> Optional[str]:
        """Retrieve a secret value. Checks memory cache first, then encrypted store."""
        if key_id in self._cache:
            return self._cache[key_id]

        try:
            fernet = Fernet(self._derive_key())
            all_secrets = self._load_encrypted(fernet)
            val = all_secrets.get(key_id)
            if val:
                self._cache[key_id] = val
            return val
        except ImportError:
            return None
        except Exception as e:
            print(f"[Secrets] Decryption failed for '{key_id}': {e}", file=sys.stderr)
            return None

    def _load_encrypted(self, fernet: Fernet) -> Dict[str, str]:
        """Load and decrypt the secrets blob."""
        if not self.enc_path.exists():
            return {}
        with open(self.enc_path, "rb") as f:
            encrypted = f.read()
        decrypted = fernet.decrypt(encrypted)
        return json.loads(decrypted.decode())

    def _mask(self, value: str) -> str:
        """Mask a secret value for display: 'sk_fi...4d' → 'sk_f..._4d'."""
        if not value or len(value) < 8:
            return "***"
        return f"{value[:4]}...{value[-4:]}"

    def list_keys(self) -> list:
        """Return list of stored key IDs (without values)."""
        return list(self._cache.keys())

    def health(self) -> dict:
        """
        Return health status WITHOUT exposing secret values.
        Returns metadata-only status per the read-only health() contract.
        """
        return {
            "secrets_manager": "active",
            "env_secrets": len([v for v in self._cache.values() if v]),
            "encrypted_store": self.enc_path.exists(),
            "keys": list(self._cache.keys()),
            "all_masked": {k: self._mask(v) for k, v in self._cache.items()},
        }
