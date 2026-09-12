"""P3: the streaming endpoint the trace UI consumes, plus the frontend
itself served as static files from the same origin (no CORS needed)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from orchestrator.graph import build_graph
from orchestrator.state import initial_state
from seeds.registry import get_seed, list_seeds

app = FastAPI(title="Consilium", version="0.3.0")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND_DIR = _REPO_ROOT / "frontend"

# Pauses inserted between streamed stages so a human watching the run can
# actually register each stage -- the graph itself runs in milliseconds
# (deterministic rule evaluation, no live model calls), which would
# otherwise render everything in one imperceptible flash. Pure UI pacing:
# it lives here, not in orchestrator/graph.py, and never touches agent
# logic or the trace content itself. `pace=0` (used by tests) disables it.
PACING_SECONDS = {"after_route": 0.5, "between_positions": 0.3, "before_reconcile": 0.7}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/seeds")
def seeds() -> list[dict]:
    return list_seeds()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_seed(seed_id: str, pace: float) -> Iterator[str]:
    seed = get_seed(seed_id)
    if seed is None:
        yield _sse("error", {"message": f"Unknown seed '{seed_id}'."})
        return
    if not seed.get("available", True):
        yield _sse("error", {"message": f"Seed '{seed_id}' isn't built yet."})
        return

    compiled = build_graph()
    state = initial_state(seed["scenario"], seed["facts"])

    try:
        first_stage = True
        for chunk in compiled.stream(state, config={"recursion_limit": 10}, stream_mode="updates"):
            for node_name, update in chunk.items():
                for event in update.get("trace", []):
                    if event["kind"] == "route":
                        pass
                    elif event["kind"] == "position":
                        time.sleep((PACING_SECONDS["after_route"] if first_stage else PACING_SECONDS["between_positions"]) * pace)
                        first_stage = False
                    elif event["kind"] == "conflict":
                        time.sleep(PACING_SECONDS["before_reconcile"] * pace)
                    yield _sse("trace", event)
    except Exception as exc:  # recommend-only demo: surface the failure, never half-render a wrong answer
        yield _sse("error", {"message": str(exc)})
        return

    yield _sse("done", {"seed_id": seed_id})


@app.get("/run/{seed_id}/stream")
def run_seed_stream(seed_id: str, pace: float = 1.0) -> StreamingResponse:
    if get_seed(seed_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown seed '{seed_id}'.")
    return StreamingResponse(
        _stream_seed(seed_id, pace),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Mounted last so it never shadows the API routes above -- serves
# frontend/index.html at "/" and any sibling assets alongside it.
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
