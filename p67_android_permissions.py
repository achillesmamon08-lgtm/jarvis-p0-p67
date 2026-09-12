"""
P6.7 Android Permission Classes — JARVIS permission management for Android 14.

Implements secure runtime permission handling for JARVIS's Android capabilities:
- PermissionManager: declares, checks, and requests Android permissions
- AccessibilityHelper: manages accessibility service state and capabilities
- SafHelper: manages Android Settings Action Framework (SAF) intents
- SafBrainBridge: bridges SAF intents to JARVIS processing pipeline

Designed for Termux root context where `su` and `am` are available.
All permission checks use real Android APIs (dumpsys, pm, settings).

Usage:
    pm = PermissionManager()
    pm.check("android.permission.CAMERA")  # → True/False
    pm.request("android.permission.RECORD_AUDIO")  # → triggers SAF intent

    ah = AccessibilityHelper()
    ah.is_enabled()  # → True (if accessibility service is active)

    saf = SafHelper()
    bridge = SafBrainBridge()
    bridge.handle_saf_intent(saf.create_document_intent("notes", "text/plain"))
"""
import os
import sys
import json
import re
import subprocess
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class PermissionStatus(Enum):
    GRANTED = "granted"
    DENIED = "denied"
    REQUESTED = "requested"
    PENDING = "pending"
    NOT_FOUND = "not_found"


@dataclass
class PermissionInfo:
    """Info about a single Android permission."""
    name: str
    status: PermissionStatus
    description: str = ""
    protection_level: str = ""
    requested_at: Optional[str] = None


class PermissionManager:
    """
    Manages Android runtime permissions via real system calls.

    Uses `dumpsys package` (when available) or `pm list permissions`
    for status checks. Requests are done via `am start` with SAF intents
    or `pm grant` for rooted devices.

    On non-Android or non-rooted environments, falls back to environment
    variable checks for permission simulation.
    """

    # Android permissions used by JARVIS
    JARVIS_PERMISSIONS = [
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.SEND_SMS",
        "android.permission.READ_CONTACTS",
        "android.permission.NOTIFICATION_LISTEN_SERVICE",
    ]

    # Descriptions
    PERMISSION_DESCRIPTIONS = {
        "android.permission.CAMERA": "Camera access for image/OCR capture",
        "android.permission.RECORD_AUDIO": "Microphone for voice input",
        "android.permission.WRITE_EXTERNAL_STORAGE": "Write files to storage",
        "android.permission.READ_EXTERNAL_STORAGE": "Read files from storage",
        "android.permission.ACCESS_FINE_LOCATION": "Precise location for context",
        "android.permission.SEND_SMS": "Send SMS messages",
        "android.permission.READ_CONTACTS": "Read contacts for context",
        "android.permission.NOTIFICATION_LISTEN_SERVICE": "Read notifications",
    }

    def __init__(self, debug: bool = False):
        self.debug = debug
        self._is_android = self._check_android()
        self._has_root = self._check_root()
        self._state_file = Path.home() / ".jarvis_permissions.json"
        self._load_state()

    def _check_android(self) -> bool:
        """Check if running on Android."""
        return os.path.exists("/system/bin/app_process") or \
               os.path.exists("/system/bin/getprop")

    def _check_root(self) -> bool:
        """Check if we have root access."""
        try:
            result = subprocess.run(["su", "-c", "id"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def _load_state(self):
        """Load saved permission state from file."""
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    self._state = json.load(f)
            except Exception:
                self._state = {}
        else:
            self._state = {}

    def _save_state(self):
        """Save permission state to file."""
        try:
            with open(self._state_file, "w") as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            if self.debug:
                print(f"[PermissionManager] Failed to save state: {e}", file=sys.stderr)

    def _run_cmd(self, cmd: list) -> tuple:
        """Run a command and return (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return -1, "", str(e)

    def check(self, permission: str) -> PermissionInfo:
        """
        Check the status of a permission.
        Uses `dumpsys package` on Android, falls back to env vars on non-Android.
        """
        # Check if we have saved state (from previous requests on this device)
        if permission in self._state:
            saved = self._state[permission]
            return PermissionInfo(
                name=permission,
                status=PermissionStatus(saved.get("status", "unknown")),
                description=self.PERMISSION_DESCRIPTIONS.get(permission, ""),
                requested_at=saved.get("requested_at"),
            )

        if self._is_android:
            # Try dumpsys (most reliable)
            rc, stdout, _ = self._run_cmd(["su", "-c", "dumpsys package com.termux"])
            if rc == 0 and stdout:
                # Parse permission grant status
                match = re.search(
                    rf"{permission}:\s*granted=(\w+)", stdout
                )
                if match:
                    granted = match.group(1) == "true"
                    return PermissionInfo(
                        name=permission,
                        status=PermissionStatus.GRANTED if granted else PermissionStatus.DENIED,
                        description=self.PERMISSION_DESCRIPTIONS.get(permission, ""),
                    )

            # Fallback: check /data/system/packages.xml or pm
            rc, stdout, _ = self._run_cmd(["su", "-c", f"pm list permissions -g -f | grep {permission}"])
            if rc == 0 and stdout:
                return PermissionInfo(
                    name=permission,
                    status=PermissionStatus.GRANTED,
                    description=self.PERMISSION_DESCRIPTIONS.get(permission, ""),
                )

        # Non-Android: check environment variable
        env_key = permission.replace("android.permission.", "").upper() + "_GRANTED"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            granted = env_val.lower() in ("1", "true", "yes", "granted")
            return PermissionInfo(
                name=permission,
                status=PermissionStatus.GRANTED if granted else PermissionStatus.DENIED,
                description=self.PERMISSION_DESCRIPTIONS.get(permission, ""),
            )

        return PermissionInfo(
            name=permission,
            status=PermissionStatus.NOT_FOUND,
            description=self.PERMISSION_DESCRIPTIONS.get(permission, ""),
        )

    def check_all(self) -> Dict[str, PermissionInfo]:
        """Check all JARVIS permissions."""
        return {p: self.check(p) for p in self.JARVIS_PERMISSIONS}

    def request(self, permission: str) -> PermissionInfo:
        """
        Request a permission.
        On Android with root: uses `pm grant` directly.
        On Android without root: returns info with status REQUESTED (user must grant manually).
        On non-Android: simulates via environment variable.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        self._state[permission] = {
            "status": "requested",
            "requested_at": now,
            "description": self.PERMISSION_DESCRIPTIONS.get(permission, ""),
        }
        self._save_state()

        if self._is_android and self._has_root:
            # Grant directly via pm
            rc, stdout, stderr = self._run_cmd(["su", "-c", f"pm grant com.termux {permission}"])
            if rc == 0:
                self._state[permission]["status"] = "granted"
                self._state[permission]["granted_at"] = now
                self._save_state()
                return PermissionInfo(
                    name=permission,
                    status=PermissionStatus.GRANTED,
                    description=self.PERMISSION_DESCRIPTIONS.get(permission, ""),
                    requested_at=now,
                )
            else:
                # Request failed — maybe permission doesn't exist in manifest
                self._state[permission]["status"] = "denied"
                self._state[permission]["error"] = stderr
                self._save_state()
                if self.debug:
                    print(f"[PermissionManager] pm grant failed: {stderr}", file=sys.stderr)
        elif self._is_android:
            # Non-root: can't grant directly, user must do it via Settings
            if self.debug:
                print(f"[PermissionManager] Request {permission} — user must grant via Settings > Apps > Termux > Permissions",
                      file=sys.stderr)

        return PermissionInfo(
            name=permission,
            status=PermissionStatus.REQUESTED if (self._is_android and not self._has_root)
                   else PermissionStatus.NOT_FOUND,
            description=self.PERMISSION_DESCRIPTIONS.get(permission, ""),
            requested_at=now,
        )

    def has(self, permission: str) -> bool:
        """Check if a permission is granted. Convenience method."""
        return self.check(permission).status == PermissionStatus.GRANTED

    def health(self) -> dict:
        """Read-only health check."""
        all_perms = self.check_all()
        granted = [p.name for p in all_perms.values() if p.status == PermissionStatus.GRANTED]
        denied = [p.name for p in all_perms.values() if p.status == PermissionStatus.DENIED]
        not_found = [p.name for p in all_perms.values() if p.status == PermissionStatus.NOT_FOUND]

        return {
            "is_android": self._is_android,
            "has_root": self._has_root,
            "total_permissions": len(self.JARVIS_PERMISSIONS),
            "granted": len(granted),
            "denied": len(denied),
            "not_found": len(not_found),
            "granted_list": [p.split(".")[-1] for p in granted],
            "state_file": str(self._state_file),
        }


class AccessibilityHelper:
    """
    Manages Android accessibility service state and capabilities.

    Uses `dumpsys accessibility` to check if accessibility services are enabled
    for com.termux. On non-Android, checks environment variables.
    """

    def __init__(self, debug: bool = False):
        self.debug = debug
        self._is_android = os.path.exists("/system/bin/app_process")
        self._package = "com.termux"

    def _run_cmd(self, cmd: list) -> tuple:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return -1, "", str(e)

    def is_enabled(self) -> bool:
        """Check if accessibility service is enabled for this app."""
        if not self._is_android:
            return os.environ.get("ACCESSIBILITY_ENABLED", "false").lower() == "true"

        rc, stdout, _ = self._run_cmd(
            ["su", "-c", "settings get secure enabled_accessibility_services"]
        )
        if rc == 0:
            services = stdout.strip()
            if self._package in services:
                return True

        # Fallback to dumpsys
        rc, stdout, _ = self._run_cmd(["su", "-c", "dumpsys accessibility"])
        if rc == 0 and self._package in stdout:
            return True

        return False

    def enabled_services(self) -> List[str]:
        """List all enabled accessibility services."""
        if not self._is_android:
            return []

        rc, stdout, _ = self._run_cmd(
            ["su", "-c", "settings get secure enabled_accessibility_services"]
        )
        if rc == 0 and stdout.strip():
            return [s.strip() for s in stdout.strip().split(":") if s]
        return []

    def request_accessibility(self) -> dict:
        """
        Generate a prompt for the user to enable accessibility service.
        Returns the intent/command needed.
        """
        if self._is_android:
            return {
                "action": "settings",
                "command": "su -c 'am start -a android.settings.ACCESSIBILITY_SETTINGS'",
                "instructions": "Navigate to 'Downloaded services' and enable JARVIS accessibility service",
                "package": self._package,
            }
        return {
            "action": "env",
            "command": "Set ACCESSIBILITY_ENABLED=true environment variable",
        }

    def health(self) -> dict:
        """Read-only health check."""
        return {
            "is_android": self._is_android,
            "enabled": self.is_enabled(),
            "enabled_services": self.enabled_services(),
            "package": self._package,
        }


class SafHelper:
    """
    Manages Android Settings Action Framework (SAF) intents.

    SAF allows apps to perform operations like file creation/deletion
    without requiring full storage permissions. Uses `am start` with
    intent actions.

    On Termux root: wraps intents with `su -c am start`.
    On non-Android: returns intent JSON for simulation.
    """

    SAF_ACTIONS = {
        "create_document": "android.intent.action.CREATE_DOCUMENT",
        "open_document": "android.intent.action.OPEN_DOCUMENT",
        "open_document_tree": "android.intent.action.OPEN_DOCUMENT_TREE",
        "delete_document": "android.intent.action.DELETE_DOCUMENT",
        "edit_document": "android.intent.action.EDIT_DOCUMENT",
    }

    def __init__(self, debug: bool = False):
        self.debug = debug
        self._is_android = os.path.exists("/system/bin/app_process")
        self._package = "com.termux"

    def _run_cmd(self, cmd: list) -> tuple:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode, result.stdout, result.stderr
        except Exception:
            return -1, "", ""

    def create_document_intent(self, filename: str, mime_type: str = "text/plain") -> dict:
        """Create a SAF intent for document creation."""
        intent = {
            "action": self.SAF_ACTIONS["create_document"],
            "package": self._package,
            "extras": {
                "android.provider.EXTRA_TITLE": filename,
                "android.intent.extra.MIME_TYPES": [mime_type],
            },
            "flags": ["GRANT_WRITE_URI_PERMISSION", "GRANT_READ_URI_PERMISSION"],
        }
        return intent

    def open_document_intent(self, mime_type: str = "*/*") -> dict:
        """Create a SAF intent for document opening."""
        return {
            "action": self.SAF_ACTIONS["open_document"],
            "package": self._package,
            "extras": {
                "android.intent.extra.MIME_TYPES": [mime_type],
            },
            "flags": ["GRANT_READ_URI_PERMISSION"],
        }

    def execute_intent(self, intent: dict) -> dict:
        """Execute a SAF intent via `am start`."""
        if not self._is_android:
            return {
                "status": "simulated",
                "intent": intent,
                "message": "Non-Android environment: intent returned but not executed",
            }

        action = intent.get("action", "")
        cmd_parts = [
            "su", "-c",
            f"am start -a {action} -t {intent.get('extras', {}).get('android.intent.extra.MIME_TYPES', ['*/*'])[0]}",
        ]

        if intent.get("extras", {}).get("android.provider.EXTRA_TITLE"):
            title = intent["extras"]["android.provider.EXTRA_TITLE"]
            cmd_parts[2] += f" --es android.provider.EXTRA_TITLE \"{title}\""

        rc, stdout, stderr = self._run_cmd(cmd_parts)
        return {
            "status": "ok" if rc == 0 else "error",
            "command": " ".join(cmd_parts),
            "stdout": stdout,
            "stderr": stderr,
        }

    def health(self) -> dict:
        """Read-only health check."""
        return {
            "is_android": self._is_android,
            "package": self._package,
            "saf_actions_available": list(self.SAF_ACTIONS.keys()),
        }


class SafBrainBridge:
    """
    Bridges SAF intents to the JARVIS processing pipeline.

    When a SAF intent result comes back (e.g., user selected a file via
    OPEN_DOCUMENT), this bridge formats the result and passes it to
    JarvisBrain.process() or processes it directly.

    Usage:
        bridge = SafBrainBridge()
        result = bridge.handle_create_result(uri_data, "my-note", "Hello")
        # → Returns formatted for JARVIS brain to process
    """

    def __init__(self, debug: bool = False):
        self.debug = debug
        self._is_android = os.path.exists("/system/bin/app_process")

    def handle_create_result(self, uri_data: str, filename: str, content: str) -> dict:
        """
        Handle a CREATE_DOCUMENT intent result.
        uri_data: The URI returned by the SAF intent
        filename: The filename that was created
        content: The content written to the file
        """
        return {
            "action": "create",
            "uri": uri_data,
            "filename": filename,
            "content_length": len(content),
            "success": bool(uri_data),
            "timestamp": os.environ.get("JARVIS_TIMESTAMP", ""),
        }

    def handle_open_result(self, uri_data: str, filename: str) -> dict:
        """
        Handle an OPEN_DOCUMENT intent result.
        uri_data: The URI returned by the SAF intent
        filename: The filename that was selected (derived from URI if possible)
        """
        if not uri_data:
            return {"action": "open", "success": False, "error": "No URI received"}

        # Try to read content from the URI (requires su context)
        content = ""
        if self._is_android:
            rc, stdout, _ = self._run_cmd(
                ["su", "-c", f"cat {uri_data}"]
            )
            if rc == 0:
                content = stdout

        return {
            "action": "open",
            "uri": uri_data,
            "filename": filename,
            "content_preview": content[:200] if content else "(unable to read content)",
            "content_length": len(content),
            "success": bool(uri_data),
        }

    def _run_cmd(self, cmd: list) -> tuple:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode, result.stdout, result.stderr
        except Exception:
            return -1, "", ""

    def to_brain_input(self, saf_result: dict) -> str:
        """Format a SAF result as input for JarvisBrain.process()."""
        action = saf_result.get("action", "unknown")
        filename = saf_result.get("filename", "unnamed")

        if action == "create":
            return f"I created a file called {filename} through the Android SAF system. Content length: {saf_result.get('content_length', 0)} characters."
        elif action == "open":
            preview = saf_result.get("content_preview", "")
            return f"I opened a file called {filename} from Android. Content preview: {preview}"
        return f"SAF action '{action}' completed for file '{filename}'."

    def health(self) -> dict:
        """Read-only health check."""
        return {
            "is_android": self._is_android,
            "handlers": ["create", "open"],
            "brain_bridge": True,
        }
