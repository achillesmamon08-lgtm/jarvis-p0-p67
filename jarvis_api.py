"""
JARVIS HTTP API — FastAPI wrapper around JarvisBrain.

Binds to Tailscale interface (100.71.240.8) or all interfaces (0.0.0.0).
Only accessible from devices on the tailnet.

Endpoints:
  POST /chat          — synchronous, returns full response
  POST /chat/stream   — streaming SSE with voice output
  GET  /health        — health check
  GET  /status        — system status (model, persona, memory)
  POST /memory/remember — store a value
  POST /memory/recall  — retrieve a value

Usage:
  python3 jarvis_api.py  (defaults to 0.0.0.0:8471)
  JARVIS_API_HOST=100.71.240.8 JARVIS_API_PORT=8471 python3 jarvis_api.py
"""
import os
import sys
import json
import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

# Ensure JARVIS path is set
JARVIS_ROOT = os.environ.get(
    "JARVIS_ROOT",
    "/data/data/com/termux/files/home/JARVIS",
)
if JARVIS_ROOT not in sys.path:
    sys.path.insert(0, JARVIS_ROOT)
os.chdir(JARVIS_ROOT)

from brain.main import JarvisBrain


app = FastAPI(title="JARVIS API", description="Personal AI assistant API")
brain = JarvisBrain()
print(f"[JARVIS API] Brain initialized: model={brain.router.model}, "
      f"ollama={brain.router._ollama_local_model}", flush=True)


class ChatRequest(BaseModel):
    message: str
    persona: Optional[str] = None
    offline: Optional[bool] = False


class MemoryRequest(BaseModel):
    key: str
    value: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok", "brain": "JarvisBrain", "model": brain.router.model}


@app.get("/status")
async def status():
    return {
        "status": "running",
        "model": brain.router.model,
        "ollama_model": brain.router._ollama_local_model,
        "offline": brain.router.is_offline,
        "persona": {
            "tone": brain.persona.active().tone,
            "routing": brain.persona.active().routing,
        },
        "memory_count": len(brain.memory.all()),
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    """Synchronous chat — returns full response from JarvisBrain.process()."""
    # Handle persona switch
    if req.persona:
        if req.persona in ("sarcastic", "serious", "normal"):
            brain.process(f"Switch to {req.persona} mode")
        else:
            raise HTTPException(400, f"Unknown persona: {req.persona}")

    # Handle offline mode
    if req.offline and not brain.router.is_offline:
        brain.process("Switch to offline mode")
    elif not req.offline and brain.router.is_offline:
        brain.process("Switch to auto mode")

    result = brain.process(req.message)

    return {
        "response": result,
        "persona": brain.persona.active().tone,
        "offline": brain.router.is_offline,
        "model": brain.router.model,
    }


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming chat — returns SSE with per-sentence voice output."""

    async def event_stream():
        if req.persona:
            brain.process(f"Switch to {req.persona} mode")

        if req.offline and not brain.router.is_offline:
            brain.process("Switch to offline mode")
        elif not req.offline and brain.router.is_offline:
            brain.process("Switch to auto mode")

        def on_text(chunk):
            if chunk:
                yield f"data: {json.dumps({'type': 'text', 'data': chunk})}"

        def on_sentence(sentence):
            try:
                brain.voice.speak(sentence + " ")
            except Exception as exc:
                print(f"[Voice Error] {exc}", file=sys.stderr)
            yield f"data: {json.dumps({'type': 'sentence', 'data': sentence})}"

        # Run streaming in sync wrapper
        def _run_stream():
            brain.process_stream(req.message, on_text, on_sentence)
            yield f"data: {json.dumps({'type': 'done'})}"

        for event in _run_stream():
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/memory/remember")
async def remember(req: MemoryRequest):
    brain.memory.remember(req.key, req.value or "")
    return {"status": "stored", "key": req.key, "value": req.value}


@app.post("/memory/recall")
async def recall(req: MemoryRequest):
    value = brain.memory.recall(req.key)
    if value is not None:
        return {"status": "found", "key": req.key, "value": value}
    raise HTTPException(404, f"No memory stored for key: {req.key}")


@app.get("/memory/all")
async def all_memory():
    return {"memory": brain.memory.all()}



class CommandRequest(BaseModel):
    action: str
    target: Optional[str] = None


@app.post("/command")
async def command(req: CommandRequest):
    """Cross-device command channel for triggering tablet actions."""
    action = req.action

    if action == "open_app":
        result = brain.tools.execute("open_app", {"package": req.target})
        return {"status": "sent", "action": action, "result": result}
    elif action == "cast_to_tv":
        result = brain.tools.execute("cast_to_tv", {"target": req.target})
        return {"status": "sent", "action": action, "result": result}
    elif action == "wake":
        result = brain.tools.execute("wake_device", {})
        return {"status": "sent", "action": action, "result": result}
    else:
        raise HTTPException(400, f"Unknown command: {action}")


if __name__ == "__main__":
    host = os.environ.get("JARVIS_API_HOST", "0.0.0.0")
    port = int(os.environ.get("JARVIS_API_PORT", "8471"))
    print(f"[JARVIS API] Server starting on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
