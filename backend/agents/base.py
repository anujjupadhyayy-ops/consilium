from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type

from pydantic import BaseModel, Field, field_validator

from orchestrator.state import AgentPosition, ConsiliumState
from orchestrator.trace import make_trace_event, next_step

# P3.6: plain-English rules are free-text and genuinely change an agent's
# reasoning (they're injected into narrate()'s system prompt below) --
# capped in count/length so Council editing can't be used to blow up the
# prompt or smuggle in something absurd. Numeric limits are the hard
# signals and stay enforced in code (each agent's own Config fields).
MAX_RULES = 12
MAX_RULE_LENGTH = 240


class AgentConfig(BaseModel):
    """Base shape every agent-kind's config extends.

    Every threshold an agent reasons on lives here, not as a Python literal
    in the evaluator -- this is what makes the edit-agent UI (Council)
    possible without touching code: change a number in this model
    (persisted as JSON in agents/configs/*.json), get a different stance
    for the same facts. See tests/test_registry.py's config-swap test.
    """

    lens: str
    rules_summary: list[str] = Field(max_length=MAX_RULES)
    user_overridable: bool = True
    # Keyword/phrase match against a (simulated) inbound trigger, e.g. an
    # email -- see api/app.py's /trigger/inbound-email.
    trigger_keywords: list[str] = []

    @field_validator("rules_summary")
    @classmethod
    def _validate_rules(cls, rules: list[str]) -> list[str]:
        cleaned = [r.strip() for r in rules if r.strip()]
        for rule in cleaned:
            if len(rule) > MAX_RULE_LENGTH:
                raise ValueError(f"rule exceeds {MAX_RULE_LENGTH} characters: {rule[:40]}...")
        return cleaned


class NarrationResult(BaseModel):
    reasoning: str
    lead_figure: str


class ConfigurableAgent(ABC):
    """Real domain logic, parameterised entirely by config, PLUS an LLM
    narration step (P3.5): `evaluate()` computes the hard, non-negotiable
    signal (stance + driving_constraint) -- this stays the guardrail and
    the deterministic test target. `narrate()` asks the model to write
    that position up in the agent's voice, but cannot change the stance:
    NarrationResult has no stance field, so even a model that tries to
    "helpfully" include one has it silently ignored by pydantic.
    """

    kind: ClassVar[str]
    config_model: ClassVar[Type[AgentConfig]]
    facts_model: ClassVar[Type[BaseModel]]

    def __init__(self, agent_id: str, config: AgentConfig):
        self.id = agent_id
        self.config = config

    @abstractmethod
    def evaluate(self, facts: dict[str, Any]) -> AgentPosition:
        """Evaluate this agent's config against its slice of the decision
        facts (state["facts"][self.id]) and return a structured position."""
        ...

    def narrate(self, facts: dict[str, Any], position: AgentPosition) -> AgentPosition:
        from model.llm import LLMUnavailableError, call_structured

        system = (
            f"You are the {self.id} voice on a back-office decision council. "
            f"Your lens: {self.config.lens} "
            f"Your rules: {'; '.join(self.config.rules_summary)} "
            "The system has already computed your stance from hard, non-negotiable "
            "signals -- you cannot change it. Write reasoning that justifies this "
            "stance using only the facts given, in a confident, professional voice. "
            'Respond with ONLY a JSON object: {"reasoning": str, "lead_figure": str}. '
            "lead_figure is a short headline citing the number that drives your position."
        )
        user = (
            f"Facts: {json.dumps(facts, default=str)}\n"
            f"Computed stance: {position['stance']}\n"
            f"Driving constraint: {position['driving_constraint']}\n"
            f"Baseline reasoning (you may improve the prose, not the substance): {position['reasoning']}"
        )
        try:
            narration = call_structured(system, user, NarrationResult)
        except LLMUnavailableError:
            return position

        return AgentPosition(
            agent=position["agent"],
            stance=position["stance"],
            recommendation=position["recommendation"],
            reasoning=narration.reasoning,
            driving_constraint=position["driving_constraint"],
            lead_figure=narration.lead_figure or position["lead_figure"],
        )

    def run(self, state: ConsiliumState) -> dict:
        facts = state["facts"].get(self.id, {})
        try:
            position = self.evaluate(facts)
        except Exception:
            # A weak routing model can hand an agent malformed facts; fall
            # back to schema defaults rather than crash the whole council.
            position = self.evaluate({})
        position = self.narrate(facts, position)
        step = next_step(state)
        event = make_trace_event(
            step=step,
            kind="position",
            agent=self.id,
            summary=f"{self.id}: {position['recommendation']}",
            payload=dict(position),
        )
        return {"positions": [position], "trace": [event]}
