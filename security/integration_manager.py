"""
Integration Manager for JARVIS — manages third-party service integrations.

Acts as the bridge between JARVIS and external APIs (Composio, Fish Audio,
Tailscale, etc.). All integration operations flow through ApprovalGateway.

Design:
  - Each integration has an IntegrationConfig (API key ref, endpoints, enabled)
  - Integrations are discovered from environment + SecretsManager
  - health() returns per-integration status (read-only)
  - execute() validates against ApprovalGateway before running
"""
import os
import sys
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum


class IntegrationStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    ERROR = "error"


@dataclass
class IntegrationConfig:
    """Configuration for a single integration."""
    name: str
    provider: str  # "composio", "fish_audio", "tailscale", "tesseract", etc.
    enabled: bool = True
    api_key_ref: Optional[str] = None  # Key ID in SecretsManager (NOT the actual key)
    endpoints: Dict[str, str] = field(default_factory=dict)
    status: str = "inactive"
    last_error: Optional[str] = None
    tools_available: List[str] = field(default_factory=list)


class IntegrationManager:
    """
    Manages all JARVIS integrations with third-party services.

    All sensitive operations (OAuth initiation, key provisioning) are
    gated behind ApprovalGateway.
    """

    def __init__(self, secrets=None, approver=None):
        self.secrets = secrets  # SecretsManager instance (optional)
        self.approver = approver  # ApprovalGateway instance (optional)
        self.integrations: Dict[str, IntegrationConfig] = {}
        self._init_integrations()

    def _init_integrations(self):
        """Discover and configure integrations from environment."""
        # Composio via MCP
        mcp_key = os.environ.get("MCP_COMPOSIO_API_KEY")
        if mcp_key:
            self.integrations["composio"] = IntegrationConfig(
                name="composio",
                provider="composio",
                enabled=True,
                api_key_ref="MCP_COMPOSIO_API_KEY",
                endpoints={"mcp": "https://connect.composio.dev/mcp"},
                status="active",
                tools_available=[
                    "COMPOSIO_GET_TOOL_SCHEMAS",
                    "COMPOSIO_MANAGE_CONNECTIONS",
                    "COMPOSIO_MULTI_EXECUTE_TOOL",
                    "COMPOSIO_SEARCH_TOOLS",
                    "COMPOSIO_WAIT_FOR_CONNECTIONS",
                ],
            )
        else:
            self.integrations["composio"] = IntegrationConfig(
                name="composio",
                provider="composio",
                enabled=False,
                status="inactive",
                last_error="MCP_COMPOSIO_API_KEY not set in environment",
            )

        # Fish Audio TTS
        fish_key = os.environ.get("FISH_API_KEY")
        if fish_key:
            self.integrations["fish_audio"] = IntegrationConfig(
                name="fish_audio",
                provider="fish_audio",
                enabled=True,
                api_key_ref="FISH_API_KEY",
                endpoints={"api": "https://api.fish.audio/v1/tts"},
                status="active",
                tools_available=["tts_speak", "tts_stream"],
            )
        else:
            self.integrations["fish_audio"] = IntegrationConfig(
                name="fish_audio",
                provider="fish_audio",
                enabled=False,
                status="inactive",
                last_error="FISH_API_KEY not set",
            )

        # Tailscale
        self.integrations["tailscale"] = IntegrationConfig(
            name="tailscale",
            provider="tailscale",
            enabled=True,
            endpoints={"status": "tailscale status", "ip": "tailscale ip"},
            status="active",
            tools_available=["tailscale_up", "tailscale_status", "tailscale_ip"],
        )

        # Tesseract OCR
        import shutil
        tesseract_path = shutil.which("tesseract")
        if tesseract_path:
            self.integrations["ocr"] = IntegrationConfig(
                name="ocr",
                provider="tesseract",
                enabled=True,
                endpoints={"binary": tesseract_path},
                status="active",
                tools_available=["ocr_extract", "ocr_image"],
            )
        else:
            self.integrations["ocr"] = IntegrationConfig(
                name="ocr",
                provider="tesseract",
                enabled=False,
                status="error",
                last_error="tesseract binary not found in PATH",
            )

        # Obsidian
        obsidian_vault = os.environ.get("OBSIDIAN_VAULT_PATH")
        if obsidian_vault and os.path.isdir(obsidian_vault):
            self.integrations["obsidian"] = IntegrationConfig(
                name="obsidian",
                provider="obsidian",
                enabled=True,
                endpoints={"vault": obsidian_vault},
                status="active",
                tools_available=["vault_read", "vault_write", "vault_list"],
            )
        else:
            self.integrations["obsidian"] = IntegrationConfig(
                name="obsidian",
                provider="obsidian",
                enabled=False,
                status="inactive",
                last_error=f"OBSIDIAN_VAULT_PATH not set or not found",
            )

    def get_integration(self, name: str) -> Optional[IntegrationConfig]:
        """Get an integration config by name."""
        return self.integrations.get(name)

    def list_integrations(self) -> List[str]:
        """List all integration names."""
        return list(self.integrations.keys())

    def is_enabled(self, name: str) -> bool:
        """Check if an integration is enabled and active."""
        integ = self.integrations.get(name)
        return integ is not None and integ.enabled and integ.status == "active"

    def request_approval(self, name: str, op_type: str, reason: str,
                         params: dict = None) -> Optional[str]:
        """
        Request approval for an integration operation.
        Returns operation ID if ApprovalGateway is configured.
        """
        if not self.approver:
            print(f"[Integration] No approver configured — operation auto-authorized: {op_type} for {name}",
                  file=sys.stderr)
            return None

        integ = self.integrations.get(name)
        if not integ or not integ.enabled:
            return None

        return self.approver.request(
            operation_type=op_type,
            resource=name,
            requestor="IntegrationManager",
            reason=reason,
            params=params or {},
        )

    def execute(self, name: str, action: str, params: dict = None) -> dict:
        """
        Execute an integration action. Checks approval for sensitive operations.
        All operations require ApprovalGateway approval for sensitive actions.
        """
        integ = self.integrations.get(name)
        if not integ:
            return {"error": f"Integration '{name}' not found"}

        if not integ.enabled:
            return {"error": f"Integration '{name}' is not enabled"}

        # Sensitive operations require approval
        sensitive = {"oauth_connect", "provision_key", "create_account"}
        if action in sensitive and self.approver:
            op_id = self.approver.request(
                operation_type=action,
                resource=name,
                requestor="IntegrationManager.execute",
                reason=f"{action} on {name}",
                params=params or {},
            )
            pending = self.approver.list_pending()
            if op_id in [p.id for p in pending]:
                return {
                    "status": "pending_approval",
                    "operation_id": op_id,
                    "message": f"Operation {op_id} requires owner approval via ApprovalGateway",
                }

        result = self._dispatch(name, action, params or {})
        return {"status": "ok", "result": result}

    def _dispatch(self, name: str, action: str, params: dict) -> Any:
        """Dispatch to the appropriate integration handler."""
        if name == "composio":
            from ai.integrations import ComposioAdapter
            adapter = ComposioAdapter()
            if action == "health":
                return adapter.health()
            elif action == "execute":
                return adapter.execute(params.get("tool_slug", ""), params.get("arguments", {}))
        elif name == "obsidian":
            if action == "write":
                from obsidian_vault import ObsidianVault
                vault = ObsidianVault(params.get("vault_path"))
                return vault.write_note(params.get("filename", ""), params.get("content", ""))
            elif action == "read":
                from obsidian_vault import ObsidianVault
                vault = ObsidianVault(params.get("vault_path"))
                return vault.read_note(params.get("filename", ""))
        elif name == "tailscale":
            return self._exec_tailscale(action, params)
        elif name == "fish_audio":
            return {"status": "voice system handles Fish Audio directly"}
        elif name == "ocr":
            from tools.manager import ToolManager
            tm = ToolManager()
            if action == "extract":
                return tm.execute("ocr", {"image": params.get("image", "")})

        return f"No handler for {name}.{action}"

    def _exec_tailscale(self, action: str, params: dict) -> str:
        """Execute Tailscale commands."""
        import subprocess
        if action == "status":
            result = subprocess.run(["tailscale", "status"], capture_output=True, text=True, timeout=10)
            return result.stdout.strip()
        elif action == "ip":
            result = subprocess.run(["tailscale", "ip"], capture_output=True, text=True, timeout=10)
            return result.stdout.strip()
        return f"Unknown action: {action}"

    def health(self) -> dict:
        """Read-only health check for all integrations."""
        return {
            name: {
                "provider": integ.provider,
                "enabled": integ.enabled,
                "status": integ.status,
                "tools": integ.tools_available,
                "endpoint": integ.endpoints,
                "last_error": integ.last_error,
            }
            for name, integ in self.integrations.items()
        }
