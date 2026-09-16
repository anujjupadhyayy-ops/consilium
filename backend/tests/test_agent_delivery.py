"""Rewrite for P3.6: loads the real agent (agents/configs/delivery.json)
via the registry instead of a bare DeliveryConfig(rules_summary=[]), and
calls check()/_position_from_check() instead of evaluate() -- see
test_agent_finance.py's module docstring for the full rationale."""
from agents.registry import get_agent

BASE_FACTS = {
    "budget": 1_000_000,
    "actual_pct": 0.55,
    "schedule_pct": 0.65,
    "spend_to_date": 600_000,
    "slip_days_before_change": 15,
    "is_resourced": True,
    "is_on_critical_path": True,
    "is_revenue_tagged": True,
    "revenue_value": 420_000,
    "reported_rag_before": "amber",
    "reported_rag_after": "green",
}


def _agent():
    return get_agent("delivery")


def _position(agent, facts):
    result = agent.check(facts)
    assert result.stance is not None, f"expected a trigger, got nothing fired ({result.unchecked=})"
    return agent._position_from_check(facts, result)


def test_supplier_milestone_seed_reduces_critical_revenue_at_risk(seed_facts):
    position = _position(_agent(), seed_facts["delivery"])

    assert position["stance"] == "yes"
    assert "420,000" in position["driving_constraint"] or "420000" in position["driving_constraint"]


def test_unresourced_milestone_downgrades_to_conditional():
    """Effective RAG floors at amber for unresourced work -- even though the
    reported status would go green, Critical Revenue at Risk can't clear,
    so the change can't be scored "yes" purely on schedule improvement."""
    facts = {**BASE_FACTS, "is_resourced": False}

    position = _position(_agent(), facts)

    assert position["stance"] == "conditional"
    assert "unchanged" in position["driving_constraint"].lower()


def test_off_critical_path_milestone_carries_no_critical_revenue_at_risk():
    facts = {**BASE_FACTS, "is_on_critical_path": False}

    position = _position(_agent(), facts)

    assert position["stance"] == "conditional"


def test_rag_improving_within_the_same_amber_or_red_bucket_is_still_conditional_not_yes():
    """Regression for a real gap the golden-differential process caught
    during migration: red -> amber is a genuine schedule improvement, but
    both ends of that move are still >=amber, so Critical Revenue at Risk
    doesn't actually change -- evaluate() scores this conditional (crar
    unchanged), never yes, REGARDLESS of is_resourced/is_on_critical_path/
    is_revenue_tagged all being true. An earlier, narrower rule design
    (three separate "schedule improves but NOT <flag>" rules) missed this
    exact case; the single combined
    "rag improves AND crar_reduction <= 0" rule does not."""
    facts = {**BASE_FACTS, "reported_rag_before": "red", "reported_rag_after": "amber"}

    position = _position(_agent(), facts)

    assert position["stance"] == "conditional"
    assert "unchanged by £0" in position["driving_constraint"] or "unchanged by" in position["driving_constraint"]


def test_no_rag_improvement_scores_no():
    facts = {**BASE_FACTS, "reported_rag_after": "amber"}  # no change at all

    position = _position(_agent(), facts)

    assert position["stance"] == "no"


def test_derive_reflects_the_configured_unresourced_floor_not_a_python_literal():
    """Direct proof the floor is read from config: an unresourced milestone
    whose reported RAG is green floors to whatever unresourced_floor_rag
    says -- amber (default) still counts as "at risk" for CRAR, but the
    floor value itself is genuinely config-sourced, not hardcoded."""
    facts = {**BASE_FACTS, "is_resourced": False, "reported_rag_after": "green"}

    default_agent = _agent()
    assert default_agent.config.unresourced_floor_rag == "amber"
    default_derived = default_agent.derive(facts)

    lenient_agent = get_agent("delivery")
    lenient_agent.config = lenient_agent.config.model_copy(update={"unresourced_floor_rag": "green"})
    lenient_derived = lenient_agent.derive(facts)

    # Flooring at "green" (i.e. no floor at all) makes the after-side
    # genuinely clear, dropping Critical Revenue at Risk to 0 -- flooring
    # at the default "amber" keeps it counted as at-risk.
    assert default_derived["crar_after"] == 420_000
    assert lenient_derived["crar_after"] == 0.0
