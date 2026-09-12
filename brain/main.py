"""
JARVIS Brain — main conversation processing pipeline.

Wiring (auto-applied, no manual system_prompt assignment required):
  1. Persona system auto-injects system prompts via process()
  2. Offline mode auto-falls back to local Ollama
  3. Voice pipeline integrated via process_stream() on_sentence callbacks

Usage:
    from brain.main import JarvisBrain
    j = JarvisBrain()
    j.process("switch to sarcastic mode")
    j.process("what is the capital of France?")
    j.process_stream("hello", on_text=callback, on_sentence=callback)
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ai.router import AIRouter
from ai.integrations import ComposioAdapter
from memory.store import Memory
from tools.manager import ToolManager
from voice import JarvisVoice
from persona_system import PersonaRegistry


class JarvisBrain:
    """
    Core JARVIS brain.

    process() — synchronous conversation processing
    process_stream() — streaming with on_text / on_sentence callbacks (voice pipeline)
    """

    def __init__(self):
        # Router handles LLM routing (OpenRouter → Ollama fallback)
        self.router = AIRouter()
        self.model = self.router.model

        # Persona system — auto-applies system prompts
        self.persona = PersonaRegistry()

        # Memory persistence
        self.memory = Memory()

        # Tool manager
        self.tools = ToolManager()

        # Voice system
        self.voice = JarvisVoice()

        # Composio integration
        self.composio = ComposioAdapter()

    def process(self, message: str) -> str:
        """
        Process a message through the full conversation pipeline.

        Persona system prompts are auto-injected here — no manual
        system_prompt assignment needed.

        1. Check for persona commands (switch to sarcastic/serious/normal)
        2. Check for offline mode commands
        3. Route through router (with persona system_prompt + offline flag)
        4. Store in memory if it's a "remember" request
        5. Return response
        """
        message_lower = message.lower().strip()

        # ── Persona command handling ──────────────────────────────────
        # "switch to sarcastic mode" → tone change
        for tone in ("sarcastic", "serious", "normal"):
            if f"switch to {tone} mode" in message_lower or f"switch to {tone}" in message_lower:
                self.persona.switch_tone(tone)
                # Sync to router
                self.router.system_prompt = self.persona.system_prompt()
                return f"Switched to {tone} mode."

        # Offline mode handling
        if "switch to offline mode" in message_lower or "go offline" in message_lower:
            self.persona.switch_routing("offline")
            self.router.is_offline = True
            self.router.system_prompt = self.persona.system_prompt()
            return "Switched to offline mode — using local Ollama only."

        if "switch to auto mode" in message_lower or "go online" in message_lower:
            self.persona.switch_routing("auto")
            self.router.is_offline = False
            self.router.system_prompt = self.persona.system_prompt()
            return "Switched to auto mode — using cloud providers."

        # List personas
        if "list personas" in message_lower or "what personas" in message_lower:
            personas = list(self.persona.personas.keys())
            return f"Available personas: {', '.join(personas)}. Active: {self.persona.active().tone}"

        # ── Memory: remember / recall ─────────────────────────────────
        if message_lower.startswith("remember "):
            parts = message_lower[8:].split(" as ", 1)
            if len(parts) == 2:
                value, key = parts[1].strip(), parts[0].strip()
                self.memory.remember(key, value)
                return f"Remembered: {key} = {value}"
            else:
                # remember X → store under "latest"
                value = message[8:].strip()
                self.memory.remember("latest", value)
                return f"Remembered: {value}"

        if message_lower.startswith("recall"):
            key = message_lower.replace("recall", "", 1).strip()
            if not key:
                key = "latest"
            value = self.memory.recall(key)
            if value:
                return f"Recalled: {value}"
            else:
                return f"Nothing remembered under '{key}'."

        # ── Persona is wired — sync system_prompt before AI call ──────
        self.router.system_prompt = self.persona.system_prompt()
        # Offline flag is also synced (set by persona commands above)
        # self.router.is_offline is already in sync

        # ── AI call through router ────────────────────────────────────
        result = self.router.ask(message)

        return result

    def process_stream(self, message: str, on_text=None, on_sentence=None):
        """
        Streaming version of process().

        Called by the HTTP API wrapper with voice callbacks.
        on_text(chunk) — called for each text segment
        on_sentence(sentence) — called for each complete sentence (voice speaks here)
        """
        # Apply persona
        self.router.system_prompt = self.persona.system_prompt()

        if on_text:
            on_text("[Processing...]\n")

        # For now, delegate to the same pipeline but split into sentences
        result = self.router.ask(message)

        if on_sentence:
            # Split result into sentences for voice pipeline
            sentences = result.replace("\n", " ").split(". ")
            for s in sentences:
                s = s.strip()
                if s:
                    if not s.endswith("."):
                        s += "."
                    if on_sentence:
                        on_sentence(s)

        if on_text:
            on_text(result + "\n")

    def _handle_tools(self, message: str, tool_results: list) -> str:
        """Handle tool execution results from the AI."""
        return f"Tools executed: {len(tool_results)} result(s)"


# ── Tool execution via ToolManager ──────────────────────────────────────
def execute_tool(tool_name: str, args: dict = None):
    """Convenience function for external callers."""
    brain = JarvisBrain()
    return brain.tools.execute(tool_name, args)
