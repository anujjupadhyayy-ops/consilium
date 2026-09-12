from agents.finance import FinanceAgent, FinanceConfig

BASE_FACTS = {
    "margin_erosion_pts": 1.0,
    "supplier_cost_increase_pct": 1.0,
    "budget_forecast_utilisation_pct": 50.0,
    "fy_month_elapsed": 6,
}


def _agent(config: FinanceConfig = None) -> FinanceAgent:
    return FinanceAgent(agent_id="finance", config=config or FinanceConfig(lens="test", rules_summary=[]))


def test_supplier_milestone_seed_trips_supplier_cost_no_line(seed_facts):
    position = _agent().evaluate(seed_facts["finance"])

    assert position["stance"] == "no"
    assert "15" in position["driving_constraint"]


def test_margin_erosion_alone_trips_the_no_line():
    facts = {**BASE_FACTS, "margin_erosion_pts": 6.0}  # > default 5pt threshold, supplier-cost stays low

    position = _agent().evaluate(facts)

    assert position["stance"] == "no"
    assert "margin erosion" in position["reasoning"].lower()


def test_forecast_flagged_early_in_the_fy():
    # default config: threshold ramps from 80% at month 2 to 100% at month 12
    facts = {**BASE_FACTS, "budget_forecast_utilisation_pct": 82.0, "fy_month_elapsed": 2}

    position = _agent().evaluate(facts)

    assert position["stance"] == "conditional"
    assert "month 2" in position["reasoning"]


def test_same_forecast_utilisation_not_a_concern_late_in_the_fy():
    # the spec's own example: the same (or higher) utilisation read late,
    # still within budget, is NOT a concern.
    facts = {**BASE_FACTS, "budget_forecast_utilisation_pct": 96.0, "fy_month_elapsed": 12}

    position = _agent().evaluate(facts)

    assert position["stance"] == "yes"


def test_forecast_hard_breach_over_the_generic_overspend_test():
    facts = {**BASE_FACTS, "budget_forecast_utilisation_pct": 110.0, "fy_month_elapsed": 6}

    position = _agent().evaluate(facts)

    assert position["stance"] == "no"
    assert "hard breach" in position["reasoning"].lower()


def test_config_swap_changes_the_stance_for_the_same_facts():
    """The regression guard for editability: change a threshold in config,
    get a different stance for identical facts -- proves rules are data,
    not Python literals."""
    facts = {**BASE_FACTS, "supplier_cost_increase_pct": 8.0}  # trips the default 7% line

    default_position = _agent().evaluate(facts)
    lenient_config = FinanceConfig(
        lens="test", rules_summary=[], supplier_cost_increase_threshold_pct=20.0
    )
    lenient_position = _agent(lenient_config).evaluate(facts)

    assert default_position["stance"] == "no"
    assert lenient_position["stance"] == "yes"
