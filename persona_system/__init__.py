"""
Persona system for JARVIS.

Manages tone personas (Normal/Sarcastic/Serious) and routing modes
(auto/offline). Each tone maps to a system prompt that gets injected
into the brain's process() pipeline automatically — no manual
system_prompt assignment required.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


# ── Tone definitions with system prompts ─────────────────────────────────

TONE_PROMPTS = {
    "normal": (
        "You are JARVIS, a helpful, friendly assistant. "
        "Keep responses concise and accurate."
    ),
    "sarcastic": (
        "You are JARVIS, a witty and sarcastic assistant. "
        "Respond with dry humor and subtle sarcasm. "
        "Keep answers accurate but with a snarky edge."
    ),
    "serious": (
        "You are JARVIS, operating in formal/analytical mode. "
        "Provide precise, well-structured responses. "
        "No jokes, no casual language."
    ),
}


@dataclass
class Persona:
    """Active persona state."""
    tone: str = "normal"
    routing: str = "auto"  # "auto" or "offline"


@dataclass
class PersonaRegistry:
    """
    Registry of all available personas.

    Usage:
        reg = PersonaRegistry()
        reg.switch_tone("sarcastic")   # → Persona(tone="sarcastic", routing="auto")
        reg.switch_routing("offline")  # → Persona(tone="sarcastic", routing="offline")
        reg.active()                   # → Persona object
        reg.system_prompt()            # → the tone's system prompt string
    """

    personas: dict = field(default_factory=lambda: dict(TONE_PROMPTS))
    _active: Persona = field(default_factory=lambda: Persona(tone="normal", routing="auto"))

    def switch_tone(self, tone: str) -> Persona:
        """Switch the active tone persona."""
        if tone not in self.personas:
            raise ValueError(f"Unknown tone: {tone}. Available: {list(self.personas)}")
        self._active = Persona(tone=tone, routing=self._active.routing)
        return self._active

    def switch_routing(self, mode: str) -> Persona:
        """Switch routing mode: 'auto' or 'offline'."""
        if mode not in ("auto", "offline"):
            raise ValueError(f"Unknown routing mode: {mode}. Use 'auto' or 'offline'.")
        self._active = Persona(tone=self._active.tone, routing=mode)
        return self._active

    def active(self) -> Persona:
        """Return the current persona state."""
        return self._active

    def system_prompt(self) -> str:
        """Return the system prompt for the active tone."""
        return self.personas.get(self._active.tone, self.personas["normal"])

    def is_offline(self) -> bool:
        """Check if offline routing is active."""
        return self._active.routing == "offline"
