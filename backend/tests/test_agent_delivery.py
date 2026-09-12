from agents.delivery import DeliveryAgent, DeliveryConfig

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


def _agent(config: DeliveryConfig = None) -> DeliveryAgent:
    return DeliveryAgent(agent_id="delivery", config=config or DeliveryConfig(lens="test", rules_summary=[]))


def test_supplier_milestone_seed_reduces_critical_revenue_at_risk(seed_facts):
    position = _agent().evaluate(seed_facts["delivery"])

    assert position["stance"] == "yes"
    assert "420,000" in position["driving_constraint"] or "420000" in position["driving_constraint"]


def test_unresourced_milestone_downgrades_to_conditional():
    """Effective RAG floors at amber for unresourced work -- even though the
    reported status would go green, Critical Revenue at Risk can't clear,
    so the change can't be scored "yes" purely on schedule improvement."""
    facts = {**BASE_FACTS, "is_resourced": False}

    position = _agent().evaluate(facts)

    assert position["stance"] == "conditional"
    assert "unresourced" in position["reasoning"].lower()


def test_off_critical_path_milestone_carries_no_critical_revenue_at_risk():
    facts = {**BASE_FACTS, "is_on_critical_path": False}

    position = _agent().evaluate(facts)

    assert position["stance"] == "conditional"
    assert "critical path" in position["reasoning"].lower()


def test_no_rag_improvement_scores_no():
    facts = {**BASE_FACTS, "reported_rag_after": "amber"}  # no change at all

    position = _agent().evaluate(facts)

    assert position["stance"] == "no"


def test_config_swap_changes_the_cited_floor_for_the_same_facts():
    """Proves the unresourced floor is read from config, not a Python
    literal: swapping it changes what the reasoning cites. (Delivery's
    stance-changing config swap is covered by the supplier-cost/margin
    thresholds in test_agent_finance.py -- the floor here doesn't move
    Critical Revenue at Risk on its own since amber and red both count
    as "at risk", but it is genuinely config-driven.)"""
    facts = {**BASE_FACTS, "is_resourced": False}

    default_position = _agent().evaluate(facts)
    stricter_config = DeliveryConfig(lens="test", rules_summary=[], unresourced_floor_rag="red")
    stricter_position = _agent(stricter_config).evaluate(facts)

    assert "amber" in default_position["reasoning"].lower()
    assert "red" in stricter_position["reasoning"].lower()
