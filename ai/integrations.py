"""
Composio integration adapter for JARVIS.

Uses SDK v0.21.1 API contracts: tool_slug= and arguments=.
"""
from typing import Optional


class ComposioAdapter:
    """Adapter for Composio SDK v0.21.1 integration."""

    def __init__(self):
        self.api_key: Optional[str] = None
        self._connected = False
        try:
            import os
            self.api_key = os.environ.get("COMPOSIO_API_KEY")
            if self.api_key:
                from composio import Composio
                self._client = Composio(api_key=self.api_key)
                self._connected = True
        except ImportError:
            self._connected = False
        except Exception:
            self._connected = False


    def health(self) -> dict:
        """Return connection health status without exposing secrets."""
        return {
            "available": self._connected,
            "provider": "composio",
            "mode": "configured" if self._connected else "unavailable",
            "api_key_set": bool(self.api_key),
        }

    def execute(self, tool_slug: str, arguments: dict = None) -> dict:
        """
        Execute a Composio tool.

        Uses SDK v0.21.1 API: tool_slug= and arguments=
        (NOT legacy tool= and parameters=)
        """
        if not self._connected:
            return {"error": "Composio not available"}

        try:
            result = self._client.execute(
                tool_slug=tool_slug,
                arguments=arguments or {},
            )
            return {"result": result}
        except Exception as exc:
            return {"error": str(exc)}
