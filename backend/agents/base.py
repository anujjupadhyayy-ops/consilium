from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type

from pydantic import BaseModel

from orchestrator.state import AgentPosition, ConsiliumState
from orchestrator.trace import make_trace_event, next_step


class AgentConfig(BaseModel):
    """Base shape every agent-kind's config extends.

    Every threshold an agent reasons on lives here, not as a Python literal
    in the evaluator -- this is what makes a P4 edit-agent UI possible
    without touching code: change a number in this model (persisted as
    JSON in agents/configs/*.json), get a different stance for the same
    facts. See tests/test_registry.py's config-swap test.
    """

    lens: str
    rules_summary: list[str]
    user_overridable: bool = True


class ConfigurableAgent(ABC):
    """P2 interface: real domain logic, parameterised entirely by config.

    Replaces P1's StubAgent. `id` is this agent instance's id in
    agents/manifest.json (usually, but not necessarily, the same as `kind`
    -- the manifest can list two instances of the same kind with different
    configs, e.g. a second Finance agent for a different business unit).
    """

    kind: ClassVar[str]
    config_model: ClassVar[Type[AgentConfig]]

    def __init__(self, agent_id: str, config: AgentConfig):
        self.id = agent_id
        self.config = config

    @abstractmethod
    def evaluate(self, facts: dict[str, Any]) -> AgentPosition:
        """Evaluate this agent's config against its slice of the decision
        facts (state["facts"][self.id]) and return a structured position."""
        ...

    def run(self, state: ConsiliumState) -> dict:
        facts = state["facts"].get(self.id, {})
        position = self.evaluate(facts)
        step = next_step(state)
        event = make_trace_event(
            step=step,
            kind="position",
            agent=self.id,
            summary=f"{self.id}: {position['recommendation']}",
            payload=dict(position),
        )
        return {"positions": [position], "trace": [event]}
