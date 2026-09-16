from __future__ import annotations

from pydantic import BaseModel

from .state import AgentPosition, Check, Conflict, ConsiliumState, Reconciliation
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
    only, reconciliation wording ONLY (P3.6 §5.6: "Persona affects wording
    only"). Never reaches extraction, relevance, blocker checks or stances
    -- see agents/base.py's extract_facts()/check(), which never call this."""
    from .cos_settings import read_cos_settings

    try:
        return read_cos_settings().get("persona", "")
    except (FileNotFoundError, ValueError):
        return ""


class ReconciliationDraft(BaseModel):
    recommendation: str
    why: str
    trade_off: str
    assumptions: list[str] = []
    not_considered: list[str] = []


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
    elif positions:
        summary = "No direct yes/no clash; conditional constraints apply"
    else:
        summary = "No agent's rules triggered on the facts as stated"

    return Conflict(
        summary=summary,
        disagreeing_pairs=disagreeing_pairs,
        conditional_notes=conditional_notes,
        blocker_notes=blocker_notes,
    )


def build_reconciliation(positions: list[AgentPosition]) -> Reconciliation:
    """Deterministic fallback -- used when the reconcile model is
    unavailable. Rule-based over structured data, not a template: it still
    names the real trade-off and applies the blocker policy."""
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
        why = f"{blocker_detail} raise a hard blocker that makes any cost/schedule trade-off moot until resolved."
    elif no_side:
        recommendation = f"Hold -- {no_side['agent']}'s objection stands"
        why = no_side["reasoning"]
    elif conditional_side:
        gates = "; ".join(f"{p['agent']}: {p['driving_constraint']}" for p in conditional_side)
        recommendation = "Proceed, but only via the stated gate(s)/condition(s)"
        why = gates
    else:
        recommendation = "Proceed"
        why = "No hard blocker, objection, or conditional gate identified among the triggered agents."

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
        "specialists' triggered positions and produce ONE defensible recommendation. Name the real "
        "trade-off using the agents' actual driving constraints -- never write in generalities. "
        "Your job is wording only: which agents triggered, their stances, and the resulting "
        "direction are already decided in code and cannot be changed by your wording. "
        "Always state what was assumed and what was not considered. " + policy_clause +
        'Respond with ONLY a JSON object: {"recommendation": str, "why": str, "trade_off": str, '
        '"assumptions": [str], "not_considered": [str]}. '
        f"Additional style/priority guidance from the user (wording only, never overrides the policy above): {_persona()}"
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
    enforced invariant rather than a prompted request, and is how "a fired
    blocker always results in a blocking verdict, regardless of LLM
    wording" (P3.6 §5.5) holds structurally rather than by classification."""
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


def _blocker_field_lists(checks: dict) -> tuple[list[str], list[str]]:
    unclear: list[str] = []
    not_mentioned: list[str] = []
    for agent_id, check in checks.items():
        unclear += [f"{agent_id}.{f}" for f in check.get("unclear", [])]
        not_mentioned += [f"{agent_id}.{f}" for f in check.get("blocker_not_mentioned", [])]
    return unclear, not_mentioned


def _apply_verdict_cap(reconciliation: Reconciliation, checks: dict) -> Reconciliation:
    """P3.6 §5.5, code-authoritative (same reasoning as _enforce_blocker_policy
    -- never inferred from the model's wording). Two levels, only reached
    when no stance-blocker actually fired (that case is already the
    strictest possible verdict via _enforce_blocker_policy and takes
    priority): a blocker-relevant field that's `unclear` (mentioned, not
    confirmed) caps the verdict at "proceed only after confirming"; one
    that's simply not in the brief at all still lets the verdict proceed on
    stated facts, but must disclose it rather than present a clean approve.
    """
    unclear_fields, not_mentioned_fields = _blocker_field_lists(checks)

    if unclear_fields:
        forced = (
            f"Proceed only after confirming: {', '.join(unclear_fields)}. A blocker-relevant field "
            "was mentioned in the brief but not confirmed with verified evidence, so the verdict "
            "cannot be an unconditional approve until it is."
        )
        return Reconciliation(
            recommendation=forced,
            why=reconciliation["why"],
            trade_off=reconciliation["trade_off"],
            assumptions=reconciliation["assumptions"],
            not_considered=reconciliation["not_considered"],
        )

    if not_mentioned_fields:
        note = f"Not checked (not in the brief): {', '.join(not_mentioned_fields)}."
        return Reconciliation(
            recommendation=f"{reconciliation['recommendation']} {note}",
            why=reconciliation["why"],
            trade_off=reconciliation["trade_off"],
            assumptions=reconciliation["assumptions"],
            not_considered=reconciliation["not_considered"],
        )

    return reconciliation


def _no_trigger_reconciliation(checks: dict) -> Reconciliation:
    """P3.6 §5.6: no agent's rules fired on the facts as stated. Not an
    approval -- the absence of a triggered concern, disclosed alongside
    whatever couldn't be checked or was left unclear."""
    unchecked: list[str] = []
    unclear: list[str] = []
    for agent_id, check in checks.items():
        unchecked += [f"{agent_id}.{f}" for f in check.get("unchecked", [])]
        unclear += [f"{agent_id}.{f}" for f in check.get("unclear", [])]

    why = "Every agent checked its rules against the facts available and none fired."
    if unchecked:
        why += f" Couldn't check: {', '.join(unchecked)}."
    if unclear:
        why += f" Unclear: {', '.join(unclear)}."

    return Reconciliation(
        recommendation="No rule triggered on stated facts.",
        why=why,
        trade_off="Not assessable -- no rule fired to name a trade-off.",
        assumptions=["No agent's rules were triggered by the facts as stated."],
        not_considered=unchecked or ["Nothing outstanding -- every referenced field was stated and checked."],
    )


def reconcile_node(state: ConsiliumState) -> dict:
    assert_bounded(state)

    step = next_step(state)
    positions = state["positions"]
    checks: dict = state["checks"]
    conflict = detect_conflict(positions)
    blockers = [p for p in positions if p["stance"] == "blocker"]

    if not positions:
        reconciliation = _no_trigger_reconciliation(checks)
    else:
        try:
            reconciliation = _llm_reconcile(state["input"], positions, conflict, blockers)
            if len(reconciliation["recommendation"].strip()) < 15:
                # A one-word "yes"/"no" isn't a defensible recommendation --
                # some small local models under-follow the prompt; fall
                # back rather than ship an unusably thin verdict.
                reconciliation = build_reconciliation(positions)
        except LLMUnavailableForReconcile:
            reconciliation = build_reconciliation(positions)

        reconciliation = _enforce_blocker_policy(reconciliation, blockers)
        if not blockers:
            reconciliation = _apply_verdict_cap(reconciliation, checks)

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
