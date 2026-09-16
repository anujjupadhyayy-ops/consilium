from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, TypedDict

from .state import ConsiliumState

TraceKind = Literal["route", "dispatch", "position", "conflict", "reconciliation"]


class TraceEvent(TypedDict):
    step: int
    kind: TraceKind
    agent: Optional[str]
    summary: str
    payload: dict
    timestamp: str


def next_step(state: ConsiliumState) -> int:
    """Sequence number for the next event(s) this node will emit.

    Nodes that run in the same LangGraph superstep (the four parallel
    specialists) each see the state as of after the previous superstep and
    before their own concurrent siblings' writes are merged in, so they all
    compute the same step number here — which correctly reflects that they
    happened in the same step of the orchestration, not a strict wall-clock
    ordering.
    """
    return len(state["trace"])


def make_trace_event(
    step: int,
    kind: TraceKind,
    agent: Optional[str],
    summary: str,
    payload: dict,
) -> TraceEvent:
    return TraceEvent(
        step=step,
        kind=kind,
        agent=agent,
        summary=summary,
        payload=payload,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
