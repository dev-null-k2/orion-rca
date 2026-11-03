"""Web UI and API. The WebSocket streams every harness event live and carries the flow question both ways."""
from __future__ import annotations

import asyncio
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse

from .estate.builder import list_scenarios, load_scenario
from .report import to_markdown
from .runner import investigate

STATIC = Path(__file__).parent / "server_static"
app = FastAPI(title="Orion", version="0.4.0")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/scenarios")
def scenarios():
    return [{"id": s, "key": (sc := load_scenario(s))["ticket"]["key"], "title": sc["title"],
             "summary": sc["ticket"]["summary"]} for s in list_scenarios()]


@app.get("/api/investigate/{scenario}", response_class=PlainTextResponse)
def investigate_md(scenario: str, policy: str = "reference"):
    return to_markdown(investigate(scenario, policy))


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    try:
        req = await socket.receive_json()
    except WebSocketDisconnect:
        return
    out: queue.Queue = queue.Queue()
    replies: queue.Queue = queue.Queue()

    def ask(kind, payload):
        out.put({"kind": "question", "question": kind, **payload})
        try:
            return replies.get(timeout=120)
        except queue.Empty:
            return None

    def work():
        try:
            r = investigate(req["scenario"], req.get("policy", "reference"), ask=ask if req.get("interactive", True) else None,
                            listeners=[lambda e: out.put({"kind": e.kind, **{k: v for k, v in e.data.items()}})])
            out.put({"kind": "answer", "answer": r.answer.model_dump(), "markdown": to_markdown(r),
                     "evidence": [{"id": e.id, "system": e.system, "tool": e.tool, "summary": e.summary,
                                   "content": e.content[:1500]} for e in r.harness.ledger.records.values()],
                     "stats": {"tool_calls": r.tool_calls, "seconds": round(r.seconds, 2)}})
        except Exception as exc:  # surface errors to the UI
            out.put({"kind": "error", "message": str(exc)})
        out.put(None)

    threading.Thread(target=work, daemon=True).start()

    async def pump_replies():
        try:
            while True:
                msg = await socket.receive_json()
                if msg.get("kind") == "reply":
                    replies.put(msg.get("answer"))
        except (WebSocketDisconnect, RuntimeError):
            replies.put(None)

    reader = asyncio.create_task(pump_replies())
    while True:
        item = await asyncio.to_thread(out.get)
        if item is None:
            break
        await socket.send_json(item)
    reader.cancel()
    await socket.close()
