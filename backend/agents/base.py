from __future__ import annotations

from abc import ABC, abstractmethod

from orchestrator.state import AgentPosition, ConsiliumState
from orchestrator.trace import make_trace_event, next_step


class StubAgent(ABC):
    """P1 interface: a hard-coded, seed-specific position.

    P2 replaces the body of `position_for` in each subclass with real
    domain logic (possibly calling the model layer) -- `run`, the trace
    emission, and the graph wiring stay untouched.
    """

    name: str

    @abstractmethod
    def position_for(self, seed_input: str) -> AgentPosition:
        ...

    def run(self, state: ConsiliumState) -> dict:
        position = self.position_for(state["input"])
        step = next_step(state)
        event = make_trace_event(
            step=step,
            kind="position",
            agent=self.name,
            summary=f"{self.name}: {position['recommendation']}",
            payload=dict(position),
        )
        return {"positions": [position], "trace": [event]}
