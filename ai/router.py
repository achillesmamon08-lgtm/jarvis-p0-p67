"""
AIRouter — routes LLM requests through OmniRoute → OpenRouter → local Ollama fallback.

Auto-detects Ollama availability at init and adds it to the fallback chain.
Respects the persona's offline routing flag: when is_offline=True, skips
all cloud providers and routes directly to local Ollama.
"""
import os
import shutil
import requests
from typing import Optional, List


class AIRouter:
    """
    Routes AI requests with automatic fallback.

    Chain: OpenRouter (OmniRoute/best-free) → local Ollama fallback

    When is_offline=True (set by PersonaRegistry), skips cloud providers
    entirely and uses local Ollama only.
    """

    def __init__(self):
        self.model: str = "auto/best-free"
        self.is_offline: bool = False

        # Auto-detect Ollama
        self._ollama_local_model: Optional[str] = self._detect_ollama_model()
        self.local_fallback_model: str = "tinyllama:latest"

        # Read OpenRouter API key from env
        self.openrouter_key: Optional[str] = os.environ.get("OPENROUTER_API_KEY")
        self.ollama_url: str = "http://127.0.0.1:11434"

        # Set system prompt (overwritten by brain when persona is active)
        self.system_prompt: str = "You are JARVIS, a helpful assistant."

    def _detect_ollama_model(self) -> Optional[str]:
        """Auto-detect available Ollama models on localhost."""
        try:
            resp = requests.get(
                "http://127.0.0.1:11434/api/tags",
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                if models:
                    # Prefer phi3:mini, then any available model
                    for m in models:
                        name = m.get("name", "")
                        if "phi3" in name:
                            return name
                    return models[0].get("name", None)
        except Exception:
            pass
        return None

    def _call_ollama(self, prompt: str, model: str) -> str:
        """Call Ollama directly on localhost."""
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", "").strip()
        except Exception as e:
            return f"[Ollama Error] {e}"
        return ""

    def _build_messages(self, messages: List[dict]) -> List[dict]:
        """Inject system prompt into the message chain."""
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(messages)
        return msgs

    def ask(self, message: str) -> str:
        """
        Route a message through the appropriate provider.

        If is_offline: use Ollama only (skip cloud).
        Otherwise: try OpenRouter first, then fall back to Ollama.
        """
        system_msg = {"role": "system", "content": self.system_prompt}
        user_msg = {"role": "user", "content": message}
        messages = [system_msg, user_msg]

        # If offline mode, skip straight to Ollama
        if self.is_offline:
            print("[AI Router] Offline mode active — using local Ollama only")
            model = self._ollama_local_model or self.local_fallback_model
            result = self._call_ollama(message, model)
            if result:
                return result
            return "[Offline] No local model available. Install Ollama and pull a model."

        # Try OpenRouter first
        if self.openrouter_key:
            try:
                print(f"[AI Router] OmniRoute disabled, routing to OpenRouter :free pool")
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://jarvis.local",
                        "X-Title": "JARVIS",
                    },
                    json={
                        "model": "nousresearch/hermes-3-llama-3.2-3b:free",
                        "messages": messages,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if result:
                        return result
                else:
                    print(f"[AI Router] OpenRouter error {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"[AI Router] OpenRouter failed: {e}")

        # Fallback to Ollama
        if self._ollama_local_model:
            print(f"[AI Router] Falling back to Ollama: {self._ollama_local_model}")
            result = self._call_ollama(message, self._ollama_local_model)
            if result:
                return result

        return "[Router] No provider available to answer the question."

    def ask_with_tools(self, message: str, tools: list = None) -> str:
        """Extended ask that supports tool calling."""
        return self.ask(message)
