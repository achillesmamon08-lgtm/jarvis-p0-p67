"""
Obsidian Vault integration for JARVIS.

Provides read/write access to a local Obsidian vault for knowledge storage,
note-taking, and memory persistence. Vault path can be configured via
the OBSIDIAN_VAULT_PATH environment variable or passed to the constructor.

Directory structure:
  vault/
    .obsidian/          — Obsidian app config (created by Obsidian app)
    notes/              — JARVIS notes
    logs/               — Session logs
    __pycache__/        — Python cache (gitignored)

Design:
  - Vault is a simple directory of markdown files
  - Notes are individual .md files with YAML frontmatter
  - write_note() creates or overwrites
  - read_note() returns content
  - search_notes() finds notes by content (grep-based)
  - health() returns vault status (read-only)
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone


class ObsidianVault:
    """
    Read/write access to an Obsidian vault for knowledge storage.

    Usage:
        vault = ObsidianVault("/path/to/vault")
        vault.write_note("test", "# Test Note\n\nHello world!")
        content = vault.read_note("test")
    """

    def __init__(self, vault_path: str = None):
        self.vault_path = Path(vault_path or os.environ.get(
            "OBSIDIAN_VAULT_PATH",
            os.path.join(os.getcwd(), "vault")
        ))
        self.notes_dir = self.vault_path / "notes"
        self.logs_dir = self.vault_path / "logs"
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Create vault directory structure."""
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def write_note(self, filename: str, content: str) -> str:
        """
        Write a note to the vault.
        Returns the full path of the written file.
        """
        safe_name = self._sanitize_filename(filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        note_path = self.notes_dir / safe_name
        note_path.write_text(content, encoding="utf-8")

        # Also write to logs with timestamp
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_path = self.logs_dir / f"{ts}_{safe_name}"
        log_path.write_text(content, encoding="utf-8")

        return str(note_path)

    def read_note(self, filename: str) -> Optional[str]:
        """
        Read a note from the vault.
        Returns None if not found.
        """
        safe_name = self._sanitize_filename(filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        note_path = self.notes_dir / safe_name
        if not note_path.exists():
            return None

        return note_path.read_text(encoding="utf-8")

    def list_notes(self) -> List[str]:
        """List all note filenames (without .md extension)."""
        if not self.notes_dir.exists():
            return []
        return sorted([
            f.stem for f in self.notes_dir.iterdir()
            if f.is_file() and f.suffix == ".md"
        ])

    def search_notes(self, query: str) -> List[Dict[str, Any]]:
        """
        Search notes by content (case-insensitive grep).
        Returns list of dicts with 'filename' and 'matches' (line numbers).
        """
        results = []
        query_lower = query.lower()

        for note_file in self.notes_dir.glob("*.md"):
            try:
                content = note_file.read_text(encoding="utf-8")
                lines = content.split("\n")
                matches = []
                for i, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        matches.append({"line": i, "text": line.strip()})
                if matches:
                    results.append({
                        "filename": note_file.stem,
                        "matches": matches,
                    })
            except Exception:
                continue

        return results

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a filename to be safe for filesystem."""
        # Remove path separators and dangerous chars
        name = re.sub(r'[/\\]', '_', name)
        name = re.sub(r'[<>:"|?*\x00-\x1f]', '', name)
        # Limit length
        name = name[:100]
        if not name:
            name = "untitled"
        return name

    def health(self) -> dict:
        """Read-only health check for the vault."""
        notes = self.list_notes()
        return {
            "vault_path": str(self.vault_path),
            "exists": self.vault_path.exists(),
            "notes_count": len(notes),
            "notes": notes,
            "notes_dir": str(self.notes_dir),
            "logs_dir": str(self.logs_dir),
        }
