"""Rewrite for P3.6: these tests used to call the deterministic evaluate()
directly on a bare FinanceConfig (rules_summary=[] but no rules[] needed,
since evaluate() never read that field). Now that stance comes from
config.rules, a bare FinanceConfig would have zero rules to check --
tests load the real agent (agents/configs/finance.json) via the registry
instead, so they exercise the actual shipped rules[], and use
model_copy(update=...) to vary just a threshold for the config-swap proof
without hand-authoring rules[] in every test.
"""
from agents.registry import get_agent

BASE_FACTS = {
    "margin_erosion_pts": 1.0,
    "supplier_cost_increase_pct": 1.0,
    "budget_forecast_utilisation_pct": 50.0,
    "fy_month_elapsed": 6,
}


def _agent():
    return get_agent("finance")


def _position(agent, facts):
    result = agent.check(facts)
    assert result.stance is not None, f"expected a trigger, got nothing fired ({result.unchecked=})"
    return agent._position_from_check(facts, result)


def test_supplier_milestone_seed_trips_supplier_cost_no_line(seed_facts):
    position = _position(_agent(), seed_facts["finance"])

    assert position["stance"] == "no"
    assert "15" in position["driving_constraint"]


def test_margin_erosion_alone_trips_the_no_line():
    facts = {**BASE_FACTS, "margin_erosion_pts": 6.0}  # > default 5pt threshold, supplier-cost stays low

    position = _position(_agent(), facts)

    assert position["stance"] == "no"
    assert "margin erosion" in position["reasoning"].lower()


def test_forecast_flagged_early_in_the_fy():
    # default config: threshold ramps from 80% at month 2 to 100% at month 12
    facts = {**BASE_FACTS, "budget_forecast_utilisation_pct": 82.0, "fy_month_elapsed": 2}

    position = _position(_agent(), facts)

    assert position["stance"] == "conditional"
    assert "month 2" in position["reasoning"]


def test_same_forecast_utilisation_not_a_concern_late_in_the_fy():
    """The spec's own example: the same (or higher) utilisation read late,
    still within budget, is NOT a concern -- under P3.6 this is the
    all-clear "no rule triggered" case (equivalent to the old explicit
    "yes"), not a stance."""
    facts = {**BASE_FACTS, "budget_forecast_utilisation_pct": 96.0, "fy_month_elapsed": 12}

    result = _agent().check(facts)

    assert result.stance is None
    assert result.unchecked == ()  # every rule COULD be checked; none fired


def test_forecast_hard_breach_over_the_generic_overspend_test():
    facts = {**BASE_FACTS, "budget_forecast_utilisation_pct": 110.0, "fy_month_elapsed": 6}

    position = _position(_agent(), facts)

    assert position["stance"] == "no"
    assert "hard breach" in position["reasoning"].lower()


def test_config_swap_changes_the_stance_for_the_same_facts():
    """The regression guard for editability: change a threshold in config,
    get a different stance for identical facts -- proves rules are data,
    not Python literals. The rules[] list itself (system-governed shape,
    not the threshold) is carried over unchanged via model_copy."""
    facts = {**BASE_FACTS, "supplier_cost_increase_pct": 8.0}  # trips the default 7% line

    default_agent = _agent()
    default_result = default_agent.check(facts)

    lenient_agent = get_agent("finance")
    lenient_agent.config = lenient_agent.config.model_copy(update={"supplier_cost_increase_threshold_pct": 20.0})
    lenient_result = lenient_agent.check(facts)

    assert default_result.stance == "no"
    assert lenient_result.stance is None  # 8% no longer trips the now-20% line, and nothing else fires
