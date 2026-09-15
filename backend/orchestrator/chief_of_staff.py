from __future__ import annotations

from pydantic import BaseModel

from .state import AgentPosition, Conflict, ConsiliumState, Reconciliation
from .termination import assert_bounded
from .trace import make_trace_event, next_step

OPERATIONAL_BLOCKER_POLICY = (
    "Consilium's reconciliation policy treats a 'blocker' stance from any "
    "agent as decisive, independent of the cost/schedule trade-off: a plan "
    "that can't be executed is moot regardless of who wins that argument. "
    "This is a disclosed, system-governed policy -- not something the "
    "Chief of Staff's own deliberation can override."
)


def _persona() -> str:
    """User-editable framing (P3.6 Settings/Council) -- tone and priority
    only. Appended after the mandatory instructions in each prompt, never
    substituted for them, and never able to touch the locked policy: see
    _enforce_blocker_policy, which checks the model's actual output
    regardless of what the persona asked for."""
    from .cos_settings import read_cos_settings

    try:
        return read_cos_settings().get("persona", "")
    except (FileNotFoundError, ValueError):
        return ""


class RoutingDecision(BaseModel):
    rationale: str
    engaged: dict[str, str] = {}
    skipped: dict[str, str] = {}
    facts: dict[str, dict] = {}


class ReconciliationDraft(BaseModel):
    recommendation: str
    why: str
    trade_off: str
    assumptions: list[str] = []
    not_considered: list[str] = []


def route_node(state: ConsiliumState) -> dict:
    from agents.registry import load_agents_from_manifest

    agents = load_agents_from_manifest()
    step = next_step(state)

    try:
        decision = _llm_route(state["input"], agents)
        engaged = {aid: reason for aid, reason in decision.engaged.items() if aid in {a.id for a in agents}}
        if not engaged:
            raise LLMRoutingEmptyError("model engaged no known agents")
        skipped = decision.skipped
        rationale = decision.rationale
        extracted_facts = decision.facts
    except (LLMUnavailableForRouting, LLMRoutingEmptyError):
        engaged = {a.id: "Engaged by default (fallback routing -- model unavailable or unusable)" for a in agents}
        skipped = {}
        rationale = (
            "The routing model was unavailable or returned nothing usable, so every "
            "configured agent was engaged by default rather than guessing who to skip."
        )
        extracted_facts = {}

    # Pre-supplied facts (a seed, a test) always win over LLM extraction --
    # extraction only fills gaps for agents nothing already told us about.
    merged_facts = {**extracted_facts, **state["facts"]}

    event = make_trace_event(
        step=step,
        kind="route",
        agent=None,
        summary=f"Engaged: {', '.join(engaged) or '(none)'}",
        payload={"engaged": engaged, "skipped": skipped, "rationale": rationale},
    )
    return {
        "routed_agents": list(engaged.keys()),
        "skipped_agents": skipped,
        "routing_reasoning": rationale,
        "facts": merged_facts,
        "trace": [event],
        "step_count": state["step_count"] + 1,
    }


class LLMUnavailableForRouting(RuntimeError):
    pass


class LLMRoutingEmptyError(RuntimeError):
    pass


def _llm_route(input_text: str, agents: list) -> RoutingDecision:
    from model.llm import LLMUnavailableError, call_structured

    roster = "\n".join(
        f'- "{a.id}": lens={a.config.lens!r}; rules={a.config.rules_summary}; '
        f"facts_schema={a.facts_model.model_json_schema().get('properties', {})}"
        for a in agents
    )
    system = (
        "You are the Chief of Staff of a back-office decision council. Given a free-text "
        "decision scenario, decide which specialist agents are relevant and which should be "
        "explicitly skipped, with a one-line reason each -- selective routing is itself a "
        "sign of judgement; do not engage an agent that has nothing to add. For every ENGAGED "
        "agent, extract the numeric/boolean facts their evaluation needs from the scenario, in "
        "the shape of their facts_schema. If a specific figure isn't stated, make a clearly "
        "reasonable illustrative estimate consistent with the scenario rather than leaving it "
        "out.\n\nAvailable agents:\n" + roster + "\n\n"
        'Respond with ONLY a JSON object: {"rationale": str, "engaged": {agent_id: reason}, '
        '"skipped": {agent_id: reason}, "facts": {agent_id: {...fields matching that agent\'s '
        "facts_schema...}}}. "
        f"Additional style/priority guidance from the user (does not override the rules above): {_persona()}"
    )
    try:
        return call_structured(system, f"Scenario: {input_text}", RoutingDecision)
    except LLMUnavailableError as exc:
        raise LLMUnavailableForRouting(str(exc)) from exc


def detect_conflict(positions: list[AgentPosition]) -> Conflict:
    yes_side = [p for p in positions if p["stance"] == "yes"]
    no_side = [p for p in positions if p["stance"] == "no"]
    conditional_side = [p for p in positions if p["stance"] == "conditional"]
    blocker_side = [p for p in positions if p["stance"] == "blocker"]

    disagreeing_pairs = [(y["agent"], n["agent"]) for y in yes_side for n in no_side]
    conditional_notes = [f"{p['agent']}: {p['driving_constraint']}" for p in conditional_side]
    blocker_notes = [f"{p['agent']}: {p['driving_constraint']}" for p in blocker_side]

    if blocker_side:
        names = ", ".join(p["agent"] for p in blocker_side)
        summary = f"{names} raise a hard blocker, independent of any cost/schedule disagreement"
    elif disagreeing_pairs:
        a, b = disagreeing_pairs[0]
        summary = f"{a} and {b} disagree on whether to proceed"
    else:
        summary = "No direct yes/no clash; conditional constraints apply"

    return Conflict(
        summary=summary,
        disagreeing_pairs=disagreeing_pairs,
        conditional_notes=conditional_notes,
        blocker_notes=blocker_notes,
    )


def build_reconciliation(positions: list[AgentPosition]) -> Reconciliation:
    """Deterministic fallback (P2 logic) -- used when the reconcile model
    is unavailable. Rule-based over structured data, not a template: it
    still names the real trade-off and applies the blocker policy."""
    blockers = [p for p in positions if p["stance"] == "blocker"]
    yes_side = next((p for p in positions if p["stance"] == "yes"), None)
    no_side = next((p for p in positions if p["stance"] == "no"), None)
    conditional_side = [p for p in positions if p["stance"] == "conditional"]

    if yes_side and no_side:
        trade_off = (
            f"Optimises for {yes_side['agent']}'s {yes_side['driving_constraint']} "
            f"at the cost of {no_side['agent']}'s {no_side['driving_constraint']}"
        )
    else:
        trade_off = "No direct cost/schedule trade-off identified."

    if blockers:
        blocker_detail = "; ".join(f"{p['agent']} ({p['driving_constraint']})" for p in blockers)
        recommendation = (
            "Do not proceed as currently scoped -- resolve the blocker(s) first, "
            "then re-run this decision via the appropriate governance gate."
        )
        why = f"{blocker_detail} raise a hard blocker that makes any cost/schedule trade-off moot until resolved. {OPERATIONAL_BLOCKER_POLICY}"
    elif no_side:
        recommendation = f"Hold -- {no_side['agent']}'s objection stands"
        why = no_side["reasoning"]
    elif conditional_side:
        gates = "; ".join(f"{p['agent']}: {p['driving_constraint']}" for p in conditional_side)
        recommendation = "Proceed, but only via the stated gate(s)/condition(s)"
        why = gates
    else:
        recommendation = "Proceed"
        why = "No hard blocker, objection, or conditional gate identified among the routed agents."

    return Reconciliation(
        recommendation=recommendation,
        why=why,
        trade_off=trade_off,
        assumptions=[
            "Facts for this scenario are illustrative estimates feeding real agent logic, "
            "not live 3PP/EVM/PRINCE2 system data -- a fork wires these to real data sources.",
        ],
        not_considered=[
            "Alternative suppliers",
            "Partial or phased cutover instead of a full 3-week pull-forward",
        ],
    )


def _llm_reconcile(input_text: str, positions: list[AgentPosition], conflict: Conflict, blockers: list[AgentPosition]) -> Reconciliation:
    from model.llm import LLMUnavailableError, call_structured

    positions_desc = "\n".join(
        f"- {p['agent']} ({p['stance']}): {p['reasoning']} [driving constraint: {p['driving_constraint']}]"
        for p in positions
    )
    policy_clause = (
        "A HARD BLOCKER has been raised. Non-negotiable policy: your recommendation MUST NOT "
        "propose proceeding as currently scoped -- say so explicitly (e.g. 'decline'/'do not "
        "proceed'/'hold') and explain that the blocker makes any cost/schedule trade-off moot "
        "until it's resolved. "
        if blockers
        else ""
    )
    system = (
        "You are the Chief of Staff adjudicating a back-office decision council. Weigh the "
        "specialists' positions and produce ONE defensible recommendation. Name the real "
        "trade-off using the agents' actual driving constraints -- never write in generalities. "
        "Always state what was assumed and what was not considered. " + policy_clause +
        'Respond with ONLY a JSON object: {"recommendation": str, "why": str, "trade_off": str, '
        '"assumptions": [str], "not_considered": [str]}. '
        f"Additional style/priority guidance from the user (does not override the policy above): {_persona()}"
    )
    user = f"Scenario: {input_text}\n\nPositions:\n{positions_desc}\n\nDetected conflict: {conflict['summary']}"

    try:
        draft = call_structured(system, user, ReconciliationDraft)
    except LLMUnavailableError as exc:
        raise LLMUnavailableForReconcile(str(exc)) from exc

    return Reconciliation(
        recommendation=draft.recommendation,
        why=draft.why,
        trade_off=draft.trade_off,
        assumptions=draft.assumptions or ["Illustrative facts, not live system data."],
        not_considered=draft.not_considered or ["Alternatives outside the scenario as given."],
    )


class LLMUnavailableForReconcile(RuntimeError):
    pass


def _enforce_blocker_policy(reconciliation: Reconciliation, blockers: list[AgentPosition]) -> Reconciliation:
    """Under a hard blocker the verdict line is code-authoritative.

    We deliberately do NOT inspect the model's recommendation text to decide
    whether it "complied": any keyword check is defeatable by negation (e.g.
    "do not hold back; approve" contains the decline word "hold" yet ships a
    proceed). So when a blocker is present the decisive recommendation is
    always authored here by policy; the model's contribution is confined to
    the explanatory why/trade_off. This makes OPERATIONAL_BLOCKER_POLICY an
    enforced invariant rather than a prompted request."""
    if not blockers:
        return reconciliation
    blocker_detail = "; ".join(f"{p['agent']} ({p['driving_constraint']})" for p in blockers)
    forced = (
        f"Decline as currently scoped -- {blocker_detail}. Resolve the blocker(s), "
        "then re-run this decision via the appropriate governance gate."
    )
    return Reconciliation(
        recommendation=forced,
        why=f"{reconciliation['why']} {OPERATIONAL_BLOCKER_POLICY}",
        trade_off=reconciliation["trade_off"],
        assumptions=reconciliation["assumptions"],
        not_considered=reconciliation["not_considered"],
    )


def reconcile_node(state: ConsiliumState) -> dict:
    assert_bounded(state)

    step = next_step(state)
    positions = state["positions"]
    conflict = detect_conflict(positions)
    blockers = [p for p in positions if p["stance"] == "blocker"]

    try:
        reconciliation = _llm_reconcile(state["input"], positions, conflict, blockers)
        if len(reconciliation["recommendation"].strip()) < 15:
            # A one-word "yes"/"no" isn't a defensible recommendation --
            # some small local models under-follow the prompt; fall back
            # rather than ship an unusably thin verdict.
            reconciliation = build_reconciliation(positions)
    except LLMUnavailableForReconcile:
        reconciliation = build_reconciliation(positions)

    reconciliation = _enforce_blocker_policy(reconciliation, blockers)

    conflict_event = make_trace_event(step, "conflict", None, conflict["summary"], dict(conflict))
    reconciliation_event = make_trace_event(
        step + 1, "reconciliation", None, reconciliation["recommendation"], dict(reconciliation)
    )

    return {
        "conflict": conflict,
        "reconciliation": reconciliation,
        "trace": [conflict_event, reconciliation_event],
        "step_count": state["step_count"] + 1,
    }
