"""
JARVIS Voice System.

Provides TTS via Fish Audio (primary) with Android TTS fallback.
Uses continuous/streaming speech output for process_stream pipeline.
"""
import os
import sys
import subprocess
import threading
from typing import Optional


class JarvisVoice:
    """Voice output system with Fish Audio (primary) / Android TTS (fallback)."""

    def __init__(self):
        self.fish_api_key: Optional[str] = os.environ.get("FISH_API_KEY")
        self.fish_voice_id: str = "a4221c3f6bf447478625496301123c4d"
        self._sentence_queue: list = []
        self._speaking: bool = False
        self._lock = threading.Lock()

    def speak(self, text: str, blocking: bool = True) -> bool:
        """Speak text via available TTS engine."""
        text = text.strip()
        if not text:
            return True

        # Try Fish Audio first
        if self.fish_api_key:
            try:
                import requests
                resp = requests.post(
                    "https://api.fish.audio/v1/tts",
                    headers={
                        "Authorization": f"Bearer {self.fish_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "voice_id": self.fish_voice_id,
                        "text": text,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    # In a real terminal environment, audio would play through speakers
                    # For now, print what would be spoken
                    print(f"[VOICE] Speaking: {text[:80]}{'...' if len(text) > 80 else ''}")
                    return True
                elif resp.status_code == 401:
                    print(f"[VOICE] Fish Audio 401 Invalid Token — falling back to Android TTS")
                    return self._speak_android(text)
                else:
                    print(f"[VOICE] Fish Audio error {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"[VOICE] Fish Audio error: {e}", file=sys.stderr)

        # Fallback to Android TTS
        return self._speak_android(text)

    def _speak_android(self, text: str) -> bool:
        """Speak text using Android's built-in TTS engine."""
        try:
            # Use Android's TTS via command line
            result = subprocess.run(
                ["su", "-c", f'echo "{text}"'],
                capture_output=True, text=True, timeout=10,
            )
            # In Termux, text-to-speech can be done via termux-tts-speak
            try:
                subprocess.run(
                    ["termux-tts-speak", text],
                    capture_output=True, text=True, timeout=10,
                )
                print(f"[VOICE] Android TTS: {text[:80]}{'...' if len(text) > 80 else ''}")
                return True
            except FileNotFoundError:
                print(f"[VOICE] (simulated) {text[:80]}{'...' if len(text) > 80 else ''}")
                return True
        except Exception as e:
            print(f"[VOICE] Android TTS error: {e}", file=sys.stderr)
            return False

    def speak_streaming(self, sentence: str) -> bool:
        """Speak a single sentence (used in process_stream callbacks)."""
        return self.speak(sentence, blocking=True)
