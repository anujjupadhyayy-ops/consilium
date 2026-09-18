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


# --------------------------- end-to-end through the real graph (free text) --

def _free_text_run(monkeypatch, message, extracted_by_agent):
    """Run the real graph on free text with per-agent extraction mocked to
    return `extracted_by_agent[agent_id]` (dict of field -> (value, quote))."""
    from agents.evidence import ExtractedValue, ExtractionResult
    from orchestrator.graph import build_graph
    from orchestrator.state import initial_state

    def fake(system, user, response_model, config=None, temperature=0.2):
        if response_model is ExtractionResult:
            agent_id = system.split("for the ")[1].split(" specialist")[0]
            return ExtractionResult(fields={
                f: ExtractedValue(value=v, evidence=[q]) for f, (v, q) in extracted_by_agent.get(agent_id, {}).items()
            })
        from model.llm import LLMUnavailableError
        raise LLMUnavailableError("mocked")

    monkeypatch.setattr("model.llm.call_structured", fake)
    return build_graph().invoke(initial_state(message, {}), config={"recursion_limit": 10})


SUPPLIER_EMAIL = (
    "A 3rd-party supplier offers to pull a delivery milestone forward 3 weeks for a 15% cost "
    "increase and a contract variation."
)


def test_supplier_email_without_licence_sla_or_capacity_wording_produces_no_unclear_flags(monkeypatch):
    """Owner change 1: tripwire keywords are specific to the fact -- a brief
    that says supplier/contract/cost but never licence/SLA/capacity/3PP
    spend/savings must NOT flag anything `unclear`."""
    result = _free_text_run(monkeypatch, SUPPLIER_EMAIL, {})
    for check in result["checks"].values():
        assert check["unclear"] == []
    # ...but the unmentioned blocker fields are disclosed as not in the brief:
    assert result["checks"]["operations"]["blocker_not_mentioned"]


def test_unmentioned_blocker_fields_disclosed_verdict_not_a_clean_approve(monkeypatch):
    result = _free_text_run(monkeypatch, SUPPLIER_EMAIL, {})
    rec = result["reconciliation"]["recommendation"]
    # nothing triggered at all here -> the no-trigger verdict, listing what couldn't be checked
    assert "no rule triggered" in rec.lower()
    assert "operations.licence_provisioned_for_new_date" in result["reconciliation"]["why"]


def test_licence_mentioned_but_unconfirmed_is_unclear_and_caps_the_verdict(monkeypatch):
    msg = SUPPLIER_EMAIL + " We are still checking whether the licence will be ready."
    result = _free_text_run(monkeypatch, msg, {"finance": {"supplier_cost_increase_pct": (3.0, "a 15% cost increase")}})
    ops = result["checks"]["operations"]
    assert "licence_provisioned_for_new_date" in ops["unclear"]
    rec = result["reconciliation"]["recommendation"].lower()
    assert "proceed only after confirming" in rec
    assert "operations.licence_provisioned_for_new_date" in rec


def test_stated_licence_blocker_extracted_with_evidence_blocks_the_verdict(monkeypatch):
    msg = SUPPLIER_EMAIL + " The licence won't be ready for the new date."
    result = _free_text_run(monkeypatch, msg, {
        "operations": {"licence_provisioned_for_new_date": (False, "The licence won't be ready for the new date")},
        "finance": {"supplier_cost_increase_pct": (3.0, "a 15% cost increase")},
    })
    assert result["checks"]["operations"]["stance"] == "blocker"
    assert result["checks"]["operations"]["provenance"]["licence_provisioned_for_new_date"] == "extracted"
    assert "decline" in result["reconciliation"]["recommendation"].lower()
