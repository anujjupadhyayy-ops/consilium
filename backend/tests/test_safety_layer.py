"""P3.6-Rules-Trigger-Spec.md §6.5 -- the tripwire (unclear vs unchecked)
and the two-level verdict cap it feeds."""
from agents.base import AgentConfig, ConfigurableAgent, RuleConfig
from orchestrator.chief_of_staff import _apply_verdict_cap, _blocker_field_lists
from orchestrator.state import Reconciliation


class _TestConfig(AgentConfig):
    licence_red_ok: bool = False  # unused config scalar, just fleshes out the shape


class _TestFacts:
    model_fields = {"licence_ok": None, "capacity_pct": None}


class _TestAgent(ConfigurableAgent):
    kind = "test"
    config_model = _TestConfig
    facts_model = _TestFacts


def _agent(rules):
    config = _TestConfig(lens="test", rules_summary=[], rules=rules)
    return _TestAgent(agent_id="test_agent", config=config)


BLOCKER_RULE = RuleConfig(
    id="licence_blocker", description="licence not provisioned", fields=["licence_ok"],
    when="licence_ok == False", stance="blocker", keywords=["licence", "provisioned"],
)


def test_keyword_present_blocker_field_not_stated_is_unclear():
    agent = _agent([BLOCKER_RULE])
    unclear, not_mentioned = agent._blocker_field_status(
        "We need to check the licence before proceeding.", unchecked=("licence_ok",)
    )
    assert unclear == ["licence_ok"]
    assert not_mentioned == []


def test_keyword_absent_field_not_stated_is_unchecked_not_unclear():
    agent = _agent([BLOCKER_RULE])
    unclear, not_mentioned = agent._blocker_field_status(
        "A totally unrelated message about something else entirely.", unchecked=("licence_ok",)
    )
    assert unclear == []
    assert not_mentioned == ["licence_ok"]


def test_keyword_present_field_stated_with_evidence_is_neither_unclear_nor_unchecked():
    """Once the field IS stated, it's no longer in `unchecked` at all (the
    caller only ever passes check_rules' `unchecked` output here), so it
    can't appear in either bucket -- the rule is evaluated normally."""
    agent = _agent([BLOCKER_RULE])
    result = agent.check({"licence_ok": False})
    assert result.stance == "blocker"
    assert result.unchecked == ()
    unclear, not_mentioned = agent._blocker_field_status("The licence is not provisioned.", unchecked=result.unchecked)
    assert unclear == []
    assert not_mentioned == []


def test_non_blocker_field_never_becomes_unclear_or_not_mentioned():
    """_blocker_field_status only considers fields referenced by a BLOCKER
    rule -- a field missing from a yes/no/conditional rule is plain
    `unchecked`, never routed through the tripwire machinery at all."""
    ordinary_rule = RuleConfig(
        id="ordinary", description="capacity high", fields=["capacity_pct"], when="capacity_pct > 90", stance="no",
    )
    agent = _agent([ordinary_rule])
    unclear, not_mentioned = agent._blocker_field_status("capacity is a concern here", unchecked=("capacity_pct",))
    assert unclear == []
    assert not_mentioned == []


# ------------------------------------------------------------ verdict cap --

def _reconciliation(recommendation="Proceed") -> Reconciliation:
    return Reconciliation(
        recommendation=recommendation, why="why", trade_off="trade_off",
        assumptions=["a"], not_considered=["b"],
    )


def test_unclear_blocker_field_caps_the_verdict_at_conditional():
    checks = {"operations": {"unclear": ["licence_ok"], "blocker_not_mentioned": []}}
    capped = _apply_verdict_cap(_reconciliation("Proceed unconditionally"), checks)
    assert "proceed only after confirming" in capped["recommendation"].lower()
    assert "operations.licence_ok" in capped["recommendation"]


def test_unmentioned_blocker_field_discloses_but_does_not_block_proceeding():
    checks = {"operations": {"unclear": [], "blocker_not_mentioned": ["licence_ok"]}}
    disclosed = _apply_verdict_cap(_reconciliation("Proceed as scoped"), checks)
    assert disclosed["recommendation"].startswith("Proceed as scoped")
    assert "not checked (not in the brief)" in disclosed["recommendation"].lower()
    assert "operations.licence_ok" in disclosed["recommendation"]


def test_unclear_takes_priority_over_not_mentioned_when_both_present():
    checks = {
        "operations": {"unclear": ["licence_ok"], "blocker_not_mentioned": []},
        "finance": {"unclear": [], "blocker_not_mentioned": ["margin_erosion_pts"]},
    }
    result = _apply_verdict_cap(_reconciliation("Proceed"), checks)
    assert "proceed only after confirming" in result["recommendation"].lower()


def test_no_unclear_or_unmentioned_blocker_fields_leaves_verdict_untouched():
    checks = {"operations": {"unclear": [], "blocker_not_mentioned": []}}
    original = _reconciliation("Proceed as scoped")
    result = _apply_verdict_cap(original, checks)
    assert result == original


def test_blocker_field_lists_aggregates_across_agents_with_agent_prefix():
    checks = {
        "operations": {"unclear": ["licence_ok"], "blocker_not_mentioned": []},
        "finance": {"unclear": [], "blocker_not_mentioned": ["margin_erosion_pts"]},
    }
    unclear, not_mentioned = _blocker_field_lists(checks)
    assert unclear == ["operations.licence_ok"]
    assert not_mentioned == ["finance.margin_erosion_pts"]
