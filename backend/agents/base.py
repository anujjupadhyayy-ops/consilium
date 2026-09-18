from __future__ import annotations

import json
import re
from dataclasses import replace
from abc import ABC
from typing import Any, ClassVar, Literal, Optional, Type

from pydantic import BaseModel, Field, field_validator, model_validator

from orchestrator.state import AgentPosition, Check, ConsiliumState
from orchestrator.trace import make_trace_event, next_step

from .rules import CheckResult, Rule, RuleError, check_rules, most_severe, validate_expression

# P3.6: plain-English rules are free-text and genuinely change an agent's
# reasoning (they're injected into narrate()'s system prompt below) --
# capped in count/length so Council editing can't be used to blow up the
# prompt or smuggle in something absurd. Numeric limits are the hard
# signals and stay enforced in code (each agent's own Config fields).
MAX_RULES = 12
MAX_RULE_LENGTH = 240

STANCE_VERB = {"yes": "Yes", "conditional": "Conditional", "no": "No", "blocker": "Blocked"}


class RuleConfig(BaseModel):
    """One structured, executable rule (P3.6 §5.1/§5.2). `description` is
    also a str.format() template over the same env `when` is evaluated
    against (stated facts + derived values + config scalars) -- this is
    what lets a fired rule's driving-constraint text reproduce the old
    evaluate()'s dynamic numeric phrasing rather than a static label.
    System-governed for `stance == "blocker"`: the Council UI and the
    config-save endpoint cannot add, remove or alter those rules (see
    registry.save_agent_config)."""

    id: str
    description: str
    fields: list[str] = Field(min_length=1)
    when: str
    stance: Literal["yes", "conditional", "no", "blocker"]
    keywords: list[str] = []

    @model_validator(mode="after")
    def _blocker_requires_keywords(self) -> "RuleConfig":
        if self.stance == "blocker" and not self.keywords:
            raise ValueError(f"rule {self.id!r}: blocker rules must declare `keywords` (tripwire, spec §5.5)")
        return self


class AgentConfig(BaseModel):
    """Base shape every agent-kind's config extends.

    Every threshold an agent reasons on lives here, not as a Python literal
    in the evaluator -- this is what makes the edit-agent UI (Council)
    possible without touching code: change a number in this model
    (persisted as JSON in agents/configs/*.json), get a different stance
    for the same facts. See tests/test_registry.py's config-swap test.

    `rules_summary` (free text, narrate()'s prompt) and `rules` (structured,
    executable, P3.6) are deliberately separate: the former is what an
    operator edits and reads; the latter is what actually decides whether
    the agent triggers.
    """

    lens: str
    rules_summary: list[str] = Field(max_length=MAX_RULES)
    user_overridable: bool = True
    # Keyword/phrase match against a (simulated) inbound trigger, e.g. an
    # email -- see api/app.py's /trigger/inbound-email. Unrelated to a
    # blocker Rule's own `keywords` (the tripwire, §5.5).
    trigger_keywords: list[str] = []
    rules: list[RuleConfig] = []

    @field_validator("rules_summary")
    @classmethod
    def _validate_rules_summary(cls, rules: list[str]) -> list[str]:
        cleaned = [r.strip() for r in rules if r.strip()]
        for rule in cleaned:
            if len(rule) > MAX_RULE_LENGTH:
                raise ValueError(f"rule exceeds {MAX_RULE_LENGTH} characters: {rule[:40]}...")
        return cleaned


class NarrationResult(BaseModel):
    reasoning: str
    lead_figure: str


def _word_boundary_present(keyword: str, lowered_text: str) -> bool:
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, lowered_text) is not None


class ConfigurableAgent(ABC):
    """Real domain logic, parameterised entirely by config, PLUS an LLM
    narration step: `check()` (P3.6) runs every declared rule against
    stated facts -- this stays the guardrail and the deterministic test
    target, no LLM involved. `narrate()` asks the model to write a
    triggered position up in the agent's voice, but cannot change the
    stance: NarrationResult has no stance field, so even a model that tries
    to "helpfully" include one has it silently ignored by pydantic.
    """

    kind: ClassVar[str]
    config_model: ClassVar[Type[AgentConfig]]
    facts_model: ClassVar[Type[BaseModel]]

    def __init__(self, agent_id: str, config: AgentConfig):
        self.id = agent_id
        self.config = config

    # ------------------------------------------------------- rules engine --

    def derive(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        """Agent-specific derived values (P3.6 §4) -- e.g. an interpolated
        threshold, an EVM ratio, a flattened dict entry -- computed only
        when every input they need is stated; OMITTED from the result
        (never a placeholder/None entry) otherwise. Default: none. Override
        per agent kind."""
        return {}

    def derived_field_names(self) -> set[str]:
        """Every name `derive()` can possibly produce for THIS agent's
        config, used only to build the rule-expression validator's allowed-
        name set (not to compute values) -- override alongside derive()."""
        return set()

    def _config_scalar_env(self) -> dict[str, Any]:
        """Every plain numeric/boolean/string config field, resolvable by
        its own field name in a rule's `when`/`description` (e.g.
        `capacity_red_threshold_pct`, or a gate-name string embedded in a
        description template) -- dict/list-shaped config fields
        (rules_summary, trigger_keywords, rules, ...) are naturally
        excluded (isinstance below is False for both)."""
        return {k: v for k, v in self.config.model_dump().items() if isinstance(v, (int, float, bool, str))}

    def allowed_rule_names(self) -> set[str]:
        return set(self.facts_model.model_fields.keys()) | self.derived_field_names() | set(self._config_scalar_env().keys())

    def _rule_env(self, raw_facts: dict[str, Any], derived: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """The one place the name environment is assembled, with the spec's
        precedence (§5.1): stated facts, then derived values, then config
        thresholds -- the later dict in the merge is the LOWER precedence
        here, so facts win. validate_rules() rejects any collision at load,
        so precedence is a backstop, not something a config can lean on."""
        derived = self.derive(raw_facts) if derived is None else derived
        return {**self._config_scalar_env(), **derived, **raw_facts}

    def validate_rules(self) -> None:
        """Called by registry.py at config load and on every Council-UI
        save -- never skip this before check()."""
        fact_names = set(self.facts_model.model_fields.keys())
        clash = sorted(fact_names & set(self._config_scalar_env().keys()))
        if clash:
            raise RuleError(
                f"agent {self.id!r}: config field(s) {clash} have the same name as a facts field. "
                "A rule's name must mean one thing -- rename the config threshold "
                "(e.g. add a _threshold suffix)."
            )
        derived_clash = sorted(fact_names & self.derived_field_names())
        if derived_clash:
            raise RuleError(f"agent {self.id!r}: derived value(s) {derived_clash} shadow a facts field.")
        allowed = self.allowed_rule_names()
        for rule_config in self.config.rules:
            validate_expression(rule_config.when, allowed)

    def check(self, raw_facts: dict[str, Any]) -> CheckResult:
        raw_facts = raw_facts or {}
        stated = {k for k, v in raw_facts.items() if v is not None}
        derived = self.derive(raw_facts)
        stated |= set(derived.keys())
        env: dict[str, Any] = self._rule_env(raw_facts, derived)
        rules = [
            Rule(
                id=rc.id, description=rc.description, fields=tuple(rc.fields),
                when=rc.when, stance=rc.stance, keywords=tuple(rc.keywords),
            )
            for rc in self.config.rules
        ]
        result = check_rules(rules, env, stated)
        # Report the FACT a person can supply, not an internal derived name.
        sources = tuple(sorted({self.source_field(f) for f in result.unchecked}))
        return replace(result, unchecked=sources)

    def field_label(self, name: str) -> str:
        """Human label for a fact (its facts-model `title`); a humanised
        field name only as a last resort, so a raw identifier with
        underscores never reaches the UI."""
        info = self.facts_model.model_fields.get(name)
        title = getattr(info, "title", None)
        return title or name.replace("_", " ")

    def field_labels(self) -> dict[str, str]:
        return {name: self.field_label(name) for name in self.facts_model.model_fields}

    def source_field(self, name: str) -> str:
        """Map a derived name back to the stated fact it comes from, for
        display (default: the name itself). Override where derive() flattens
        or renames a fact."""
        return name

    # -------------------------------------------------------- extraction --

    def extract_facts(self, message: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
        """One narrow LLM call for this agent's own facts fields only, over
        the WHOLE message (never chunked -- a message estimated over
        MODEL_CONTEXT_TOKENS raises MessageTooLongError instead), evidence-
        verified in code. Deliberately persona-free (P3.6 §5.4: "Persona
        text must NOT appear in extraction prompts"). Returns
        ({field: value, ...}, {field: [evidence quotes], ...}) -- a field
        the model couldn't ground in a verified quote is simply absent."""
        from model.config import ModelConfig
        from model.llm import LLMUnavailableError, call_structured

        from .evidence import ExtractionResult, assert_within_context, verify_extraction

        config = ModelConfig.current()
        assert_within_context(message, config.context_tokens)

        fields = self.facts_model.model_fields
        field_desc = "; ".join(_field_prompt_line(name, info) for name, info in fields.items())
        system = (
            f"You extract structured facts for the {self.id} specialist on a back-office decision "
            f"council, from a free-text message. Fields to extract: {field_desc}. For each field, "
            'return {"value": <the value, or null>, "evidence": [<verbatim quotes from the message '
            'that state it>]}. Return null and an empty evidence list for anything the message does '
            "not state -- never invent, estimate, or infer a plausible figure, even a 'reasonable' "
            "one. A brief may word a fact differently from the field's name -- match on the meaning given "
            "for each field, but still only when the message states it, and quote the words it uses. "
            "Evidence quotes must be copied exactly from the message (whitespace/line-break "
            "differences are fine; do not paraphrase); a fact spanning two paragraphs may cite more "
            'than one quote. Respond with ONLY a JSON object: {"fields": {<field name>: '
            '{"value": ..., "evidence": [...]}}}.'
        )
        try:
            result = call_structured(system, message, ExtractionResult, config=config, temperature=0)
        except LLMUnavailableError:
            return {}, {}

        verified = verify_extraction(
            result, message, allowed_fields=set(fields.keys()),
            field_types={name: info.annotation for name, info in fields.items()},
        )
        raw_facts = {field: v["value"] for field, v in verified.items()}
        evidence = {field: v["evidence"] for field, v in verified.items()}
        return raw_facts, evidence

    # ------------------------------------------------------------- narrate --

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

    # ------------------------------------------------ position from check --

    def extra_reasoning_context(self, raw_facts: dict[str, Any]) -> str:
        """Hook for agent-specific reasoning context that isn't itself a
        rule (P3.6 change 6: PMO's `portfolio_contention` stays informative
        prose on a triggered position, not a rule field). Default: none."""
        return ""

    def _position_from_check(self, raw_facts: dict[str, Any], result: CheckResult) -> AgentPosition:
        env: dict[str, Any] = self._rule_env(raw_facts)
        top_severity = max(_severity(f.stance) for f in result.fired)
        top_fired = [f for f in result.fired if _severity(f.stance) == top_severity]

        def render(desc: str) -> str:
            try:
                return desc.format(**env)
            except (KeyError, ValueError, IndexError):
                return desc

        top_texts = list(dict.fromkeys(render(f.description) for f in top_fired))
        driving_constraint = "; ".join(top_texts)

        all_texts = list(dict.fromkeys(render(f.description) for f in result.fired))
        reasoning = "; ".join(all_texts) + "." if all_texts else ""
        extra = self.extra_reasoning_context(raw_facts)
        if extra:
            reasoning = f"{reasoning} {extra}" if reasoning else extra

        recommendation = f"{STANCE_VERB[result.stance]} -- {top_texts[0]}" if top_texts else STANCE_VERB[result.stance]

        return AgentPosition(
            agent=self.id,
            stance=result.stance,
            recommendation=recommendation,
            reasoning=reasoning,
            driving_constraint=driving_constraint,
            lead_figure=driving_constraint,
        )

    # ---------------------------------------------------------------- run --

    def _check_summary(self, check: Check) -> str:
        if check["triggered"]:
            return f"{self.id}: triggered ({check['stance']}) -- {', '.join(check['fired'])}"
        if check["unclear"]:
            return f"{self.id}: unclear -- {', '.join(check['unclear'])} mentioned but not confirmed"
        if check["unchecked"]:
            return f"{self.id}: couldn't check -- {', '.join(check['unchecked'])}"
        return f"{self.id}: all rules checked, none tripped"

    def _blocker_field_status(self, message: str, unchecked: tuple[str, ...]) -> tuple[list[str], list[str]]:
        """P3.6 §5.5, two-level safety net over every field a blocker rule
        references that's currently unchecked:
          - keyword mentioned in the message but the field itself wasn't
            confirmed -> `unclear` (the stronger flag: verdict capped at
            conditional at best).
          - field neither stated nor mentioned -> `blocker_not_mentioned`
            (the weaker flag: verdict may proceed but must disclose it).
        A field can only be in one bucket, never both."""
        blocker_fields: set[str] = set()
        for rc in self.config.rules:
            if rc.stance == "blocker":
                blocker_fields.update(rc.fields)
        candidates = [f for f in unchecked if f in blocker_fields]
        if not candidates:
            return [], []

        lowered = (message or "").lower()
        unclear: list[str] = []
        not_mentioned: list[str] = []
        for field in candidates:
            mentioned = any(
                _word_boundary_present(kw, lowered)
                for rc in self.config.rules
                if rc.stance == "blocker" and field in rc.fields
                for kw in rc.keywords
            )
            (unclear if mentioned else not_mentioned).append(field)
        return unclear, not_mentioned

    def run(self, state: ConsiliumState) -> dict:
        step = next_step(state)
        seed_facts = state["facts"].get(self.id)

        if seed_facts is not None:
            raw_facts = dict(seed_facts)
            provenance = {k: "seeded" for k, v in raw_facts.items() if v is not None}
            evidence: dict[str, list[str]] = {}
        else:
            try:
                raw_facts, evidence = self.extract_facts(state["input"])
            except Exception:
                # One agent's extraction failing (a bad model response, an
                # over-context message, a transient error) must not crash
                # the run -- this agent simply has no stated facts, reported
                # as unchecked like any other missing data.
                raw_facts, evidence = {}, {}
            provenance = {k: "extracted" for k in raw_facts if raw_facts.get(k) is not None}

        result = self.check(raw_facts)
        unclear, blocker_not_mentioned = self._blocker_field_status(state["input"], result.unchecked)

        check = Check(
            agent=self.id,
            triggered=result.stance is not None,
            stance=result.stance,
            fired=[f.id for f in result.fired],
            unchecked=list(result.unchecked),
            unclear=unclear,
            blocker_not_mentioned=blocker_not_mentioned,
            evidence=evidence,
            provenance=provenance,
            labels=self.field_labels(),
        )
        check_event = make_trace_event(step, "check", self.id, self._check_summary(check), dict(check))

        if result.stance is None:
            return {"checks": {self.id: check}, "positions": [], "trace": [check_event], "step_count": 1}

        position = self._position_from_check(raw_facts, result)
        position = self.narrate(raw_facts, position)
        position_event = make_trace_event(
            step + 1, "position", self.id, f"{self.id}: {position['recommendation']}", dict(position)
        )

        return {
            "checks": {self.id: check},
            "positions": [position],
            "trace": [check_event, position_event],
            "step_count": 1,
        }


def _severity(stance: str) -> int:
    return {"yes": 0, "conditional": 1, "no": 2, "blocker": 3}[stance]


def _field_prompt_line(name: str, field_info: Any) -> str:
    """`name (type): plain-English meaning` -- the description tells the model
    what the fact is and the everyday phrasings it appears under, so a brief
    that words it differently ('a 15% uplift on our fee') still maps to it."""
    line = f"{name} ({_field_type_hint(field_info)})"
    description = getattr(field_info, "description", None)
    return f"{line}: {description}" if description else line


def _field_type_hint(field_info: Any) -> str:
    annotation = getattr(field_info, "annotation", None)
    name = getattr(annotation, "__name__", None)
    return name or str(annotation)
