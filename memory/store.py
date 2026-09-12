"""
Memory store for JARVIS — JSON-based file persistence.

Provides remember() / recall() with file persistence.
"""
import os
import json
from typing import Optional

MEMORY_DIR = os.environ.get(
    "JARVIS_MEMORY_DIR",
    "/data/data/com/termux/files/home/JARVIS/memory",
)
MEMORY_FILE = os.path.join(MEMORY_DIR, "store.json")


class Memory:
    """Simple JSON-backed key/value memory store."""

    def __init__(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        self._data = {}
        self._load()

    def _load(self):
        """Load memory from disk."""
        try:
            if os.path.exists(MEMORY_FILE):
                with open(MEMORY_FILE, "r") as f:
                    self._data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._data = {}

    def _save(self):
        """Persist memory to disk."""
        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            print(f"[Memory] Save error: {e}", file=sys.stderr) if 'sys' in dir() else None

    def remember(self, key: str, value: str) -> bool:
        """Store a value under key."""
        self._data[key] = value
        self._save()
        return True

    def recall(self, key: str) -> Optional[str]:
        """Retrieve a value by key. Returns None if not found."""
        return self._data.get(key)

    def all(self) -> dict:
        """Return all stored entries."""
        return dict(self._data)

    def forget(self, key: str) -> bool:
        """Remove a key. Returns True if key existed."""
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False
