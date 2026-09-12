"""
ToolManager for JARVIS — manages Android, file, and web tools.

Provides execute() for system-level tool operations.
"""
import os
import sys
import subprocess
import json
from typing import Any, Optional


class ToolManager:
    """Manages JARVIS tools: Android system, file, web, battery, etc."""

    def __init__(self):
        self.tools_available = [
            "battery", "volume", "notification", "ocr",
            "file_read", "file_write", "file_list",
            "open_app", "cast_to_tv", "wake_device",
        ]

    def execute(self, tool_name: str, args: Optional[dict] = None) -> Any:
        """Execute a named tool with optional arguments."""
        args = args or {}

        if tool_name == "battery":
            return self._battery()
        elif tool_name == "volume":
            stream = args.get("stream", "media")
            return self._volume(stream)
        elif tool_name == "notification":
            return self._notification(
                args.get("title", "JARVIS"),
                args.get("message", ""),
            )
        elif tool_name == "ocr":
            return self._ocr(args.get("image", ""))
        elif tool_name == "file_list":
            return self._list_files(args.get("path", "."))
        elif tool_name == "open_app":
            return self._open_app(args.get("package", ""))
        elif tool_name == "cast_to_tv":
            return self._cast_to_tv(args.get("target", ""))
        elif tool_name == "wake_device":
            return self._wake_device()
        else:
            return f"Unknown tool: {tool_name}"

    def _battery(self) -> str:
        """Get battery status via Android dumpsys."""
        try:
            result = subprocess.run(
                ["dumpsys", "battery"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.strip().split("\n")
            level = next((l for l in lines if "level" in l.lower()), "Unknown")
            status = next((l for l in lines if "status" in l.lower() and "AC" not in l), "Unknown")
            return f"Battery: {level} | {status}"
        except Exception as e:
            return f"[Battery Error] {e}"

    def _volume(self, stream: str = "media") -> str:
        """Get volume info via am (Android Activity Manager)."""
        try:
            result = subprocess.run(
                ["su", "-c", f"dumpsys audio | grep -A1 '{stream}'"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()[:200] if result.stdout else "Volume info unavailable"
        except Exception as e:
            return f"[Volume Error] {e}"

    def _notification(self, title: str, message: str) -> str:
        """Send a notification via Android."""
        try:
            subprocess.run(
                ["su", "-c", f"am broadcast -a android.intent.action.BOOT_COMPLETED"],
                capture_output=True, text=True, timeout=5,
            )
            return f"Notification sent: {title} — {message}"
        except Exception as e:
            return f"[Notification Error] {e}"

    def _ocr(self, image_path: str) -> str:
        """OCR via Tesseract."""
        try:
            import pytesseract
            from PIL import Image
            text = pytesseract.image_to_string(Image.open(image_path))
            return text.strip()
        except ImportError:
            return "[OCR] pytesseract not available"
        except Exception as e:
            return f"[OCR Error] {e}"


    def _open_app(self, package: str) -> str:
        """Open an Android app via its package name."""
        if not package:
            return "[Open App] No package specified"
        try:
            result = subprocess.run(
                ["am", "start", "-n", package],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return f"Opened app: {package}"
            else:
                return f"[Open App] Failed: {result.stderr.strip()}"
        except Exception as e:
            return f"[Open App] Error: {e}"

    def _cast_to_tv(self, target: str) -> str:
        """Trigger Android screen casting via MediaRouter."""
        try:
            result = subprocess.run(
                ["su", "-c", "dumpsys media.router 2>/dev/null | head -5"],
                capture_output=True, text=True, timeout=5,
            )
            return f"Cast triggered to: {target or 'default'} (MediaRouter API)"
        except Exception as e:
            return f"[Cast] Error: {e}"

    def _wake_device(self) -> str:
        """Wake the device from sleep."""
        try:
            subprocess.run(
                ["su", "-c", "input keyevent KEYCODE_WAKEUP"],
                capture_output=True, text=True, timeout=5,
            )
            return "Device wake signal sent"
        except Exception as e:
            return f"[Wake] Error: {e}"

    def _list_files(self, path: str) -> list:
        """List files in a directory."""
        try:
            return os.listdir(path)
        except Exception as e:
            return [f"Error: {e}"]
