"""Guided rule editing (Council tab): edit / add / delete rules through the
API, with the P3.6 guardrails intact -- blocker rules untouchable, nothing
user-supplied ever parsed as an expression, invalid input refused with a
readable reason and nothing saved."""
import json
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from agents import registry
from agents.registry import (
    BlockerRuleImmutableError,
    apply_rules_request,
    get_agent,
    load_agents_from_manifest,
    save_agent_config,
)
from agents.rule_edit import RuleEditError, condition_text, rules_view
from api.app import app
from orchestrator.graph import RECURSION_LIMIT, build_graph
from orchestrator.state import initial_state

client = TestClient(app)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """Isolated copies of the real manifest + configs, wired into the registry
    so both direct calls and the API use them -- the repo's JSON is never touched."""
    configs_dir = tmp_path / "configs"
    shutil.copytree(registry.DEFAULT_CONFIGS_DIR, configs_dir)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(registry.DEFAULT_MANIFEST_PATH.read_text())
    monkeypatch.setattr(registry, "DEFAULT_CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(registry, "DEFAULT_MANIFEST_PATH", manifest_path)
    return manifest_path, configs_dir


def _rules(agent_id):
    return client.get(f"/agents/{agent_id}/rules").json()["rules"]


def _payload(agent_id, **changes):
    """The current rules as the UI would send them back, with `changes` = {rule_id: {...}}."""
    return {"rules": [{"id": r["id"], **changes.get(r["id"], {})} for r in _rules(agent_id)]}


def _add(agent_id, label, stance, field, op, value):
    body = _payload(agent_id)
    body["rules"].append({"label": label, "stance": stance, "condition": {"field": field, "op": op, "value": value}})
    return client.put(f"/agents/{agent_id}/rules", json=body)


SUPPLIER_15 = {"finance": {"supplier_cost_increase_pct": 15.0}}


def _finance_check(facts):
    return get_agent("finance").check(facts)


# ------------------------------------------------------------ edit persists --

def test_editing_a_threshold_persists_and_changes_the_next_runs_outcome(dirs):
    assert _finance_check(SUPPLIER_15["finance"]).stance == "no"          # 15% > the 7% line

    body = _payload("finance")
    body["thresholds"] = {"supplier_cost_increase_threshold_pct": 50}
    resp = client.put("/agents/finance/rules", json=body)

    assert resp.status_code == 200
    saved = next(r for r in resp.json()["rules"] if r["id"] == "supplier_cost_high")
    assert saved["threshold"]["value"] == 50 and "50%" in saved["condition_text"]
    assert _finance_check(SUPPLIER_15["finance"]).stance is None          # the very next check uses it


def test_editing_a_stance_persists_and_changes_the_outcome(dirs):
    resp = client.put("/agents/finance/rules", json=_payload("finance", supplier_cost_high={"stance": "conditional"}))
    assert resp.status_code == 200
    assert _finance_check(SUPPLIER_15["finance"]).stance == "conditional"


def test_editing_a_description_changes_the_text_a_fired_rule_shows(dirs):
    client.put("/agents/finance/rules", json=_payload("finance", supplier_cost_high={"label": "Fee uplift is too steep"}))
    agent = get_agent("finance")
    result = agent.check(SUPPLIER_15["finance"])
    position = agent._position_from_check(SUPPLIER_15["finance"], result)
    assert "Fee uplift is too steep" in position["driving_constraint"]
    assert next(r for r in _rules("finance") if r["id"] == "supplier_cost_high")["label"] == "Fee uplift is too steep"


def test_a_description_is_literal_text_never_a_template(dirs):
    label = "Uplift {supplier_cost_increase_pct} > {0} and {__class__}"
    assert client.put("/agents/finance/rules", json=_payload("finance", supplier_cost_high={"label": label})).status_code == 200
    agent = get_agent("finance")
    position = agent._position_from_check(SUPPLIER_15["finance"], agent.check(SUPPLIER_15["finance"]))
    assert label in position["driving_constraint"]        # braces kept verbatim, nothing substituted


def test_field_and_operator_of_a_shipped_rule_cannot_change(dirs):
    manifest_path, configs_dir = dirs
    current = json.loads((configs_dir / "finance.json").read_text())["rules"]
    for change in ({"when": "supplier_cost_increase_pct < 7"}, {"fields": ["margin_erosion_pts"]}):
        tampered = [{**r, **change} if r["id"] == "supplier_cost_high" else r for r in current]
        with pytest.raises(RuleEditError, match="only a rule's stance, description and threshold|can't be changed"):
            save_agent_config("finance", {"rules": tampered})


# ------------------------------------------------------------ add persists --

def test_an_added_rule_persists_and_fires(dirs):
    resp = _add("finance", "Late in the year", "conditional", "fy_month_elapsed", ">=", 10)
    assert resp.status_code == 200
    added = next(r for r in resp.json()["rules"] if r["user_added"])
    assert added["deletable"] and added["condition_text"] == "Financial-year month the forecast is read in is at least 10"

    result = _finance_check({"fy_month_elapsed": 11})
    assert result.stance == "conditional" and [f.id for f in result.fired] == [added["id"]]
    assert _finance_check({"fy_month_elapsed": 3}).stance is None


def test_added_rules_of_each_value_type_work(dirs):
    assert _add("operations", "Uses the old SLA", "no", "supplier_sla_in_place", "==", False).status_code == 200
    assert _add("delivery", "Already red", "conditional", "reported_rag_before", "==", "red").status_code == 200
    assert _add("pmo", "Not a variation", "yes", "is_contract_variation", "!=", True).status_code == 200


def test_an_added_rules_value_and_stance_can_be_edited_but_not_its_field_or_operator(dirs):
    _add("finance", "Late in the year", "conditional", "fy_month_elapsed", ">=", 10)
    rid = next(r["id"] for r in _rules("finance") if r["user_added"])
    assert client.put("/agents/finance/rules", json=_payload("finance", **{rid: {"value": 6, "stance": "no"}})).status_code == 200
    assert _finance_check({"fy_month_elapsed": 7}).stance == "no"

    _, configs_dir = dirs
    current = json.loads((configs_dir / "finance.json").read_text())["rules"]
    tampered = [{**r, "condition": {**r["condition"], "op": "<"}, "when": "fy_month_elapsed < 6"} if r["id"] == rid else r for r in current]
    with pytest.raises(RuleEditError, match="field and operator"):
        save_agent_config("finance", {"rules": tampered})


# ------------------------------------------------------------------ delete --

def test_a_user_added_rule_can_be_deleted(dirs):
    _add("finance", "Late in the year", "conditional", "fy_month_elapsed", ">=", 10)
    rid = next(r["id"] for r in _rules("finance") if r["user_added"])
    body = {"rules": [{"id": r["id"]} for r in _rules("finance") if r["id"] != rid]}
    assert client.put("/agents/finance/rules", json=body).status_code == 200
    assert not any(r["user_added"] for r in _rules("finance"))
    assert _finance_check({"fy_month_elapsed": 11}).stance is None


def test_a_shipped_rule_cannot_be_deleted(dirs):
    body = {"rules": [{"id": r["id"]} for r in _rules("finance") if r["id"] != "supplier_cost_high"]}
    resp = client.put("/agents/finance/rules", json=body)
    assert resp.status_code == 422 and "shipped config and can't be deleted" in resp.json()["detail"]
    assert any(r["id"] == "supplier_cost_high" for r in _rules("finance"))    # still there
    assert all(r["deletable"] is False for r in _rules("finance"))            # and the UI is told so


# ---------------------------------------------------------------- blockers --

def test_blocker_rules_render_as_system_governed_and_not_deletable(dirs):
    blockers = [r for r in _rules("operations") if r["system_governed"]]
    assert {r["id"] for r in blockers} >= {"capacity_red", "licence_not_provisioned", "supplier_sla_not_in_place"}
    assert all(not r["deletable"] for r in blockers)


@pytest.mark.parametrize("change", [{"stance": "no"}, {"label": "Renamed"}])
def test_a_blocker_rule_cannot_be_edited_through_the_rules_api(dirs, change):
    resp = client.put("/agents/operations/rules", json=_payload("operations", licence_not_provisioned=change))
    assert resp.status_code == 422 and "system-governed" in resp.json()["detail"]


def test_a_blocker_rule_cannot_be_deleted_through_the_rules_api(dirs):
    body = {"rules": [{"id": r["id"]} for r in _rules("operations") if r["id"] != "licence_not_provisioned"]}
    resp = client.put("/agents/operations/rules", json=body)
    assert resp.status_code == 422 and "system-governed" in resp.json()["detail"]


def test_a_blocker_rule_cannot_be_added_through_the_rules_api(dirs):
    resp = _add("finance", "Sneaky blocker", "blocker", "margin_erosion_pts", ">", 1)
    assert resp.status_code == 422
    assert not any(r["stance"] == "blocker" for r in _rules("finance"))


def test_a_blocker_stance_cannot_be_reached_by_editing_a_normal_rule(dirs):
    resp = client.put("/agents/finance/rules", json=_payload("finance", supplier_cost_high={"stance": "blocker"}))
    assert resp.status_code == 422
    assert next(r for r in _rules("finance") if r["id"] == "supplier_cost_high")["stance"] == "no"


def test_raw_config_put_still_cannot_touch_a_blocker_rule(dirs):
    _, configs_dir = dirs
    current = json.loads((configs_dir / "operations.json").read_text())["rules"]
    tampered = [{**r, "stance": "no"} if r["id"] == "licence_not_provisioned" else r for r in current]
    resp = client.put("/agents/operations/config", json={"rules": tampered})
    assert resp.status_code == 422 and "system-governed" in resp.json()["detail"]


def test_a_blockers_threshold_is_still_editable(dirs):
    body = _payload("operations")
    body["thresholds"] = {"capacity_red_threshold_pct": 95}
    assert client.put("/agents/operations/rules", json=body).status_code == 200
    assert get_agent("operations").config.capacity_red_threshold_pct == 95
    blocker = next(r for r in _rules("operations") if r["id"] == "capacity_red")
    assert blocker["system_governed"] and blocker["threshold"]["value"] == 95


# ------------------------------------------------- invalid input is refused --

@pytest.mark.parametrize("field,op,value,reason", [
    ("mystery_field", ">", 5, "not a field this agent can compare"),                 # invalid field
    ("tolerance_variances_pct", ">", 5, "not a field this agent can compare"),       # dict-shaped facts aren't comparable
    ("supplier_cost_increase_pct", "~", 5, "operator"),                              # invalid operator
    ("supplier_cost_increase_pct", "__import__", 5, "operator"),
    ("supplier_cost_increase_pct", ">", "lots", "number"),                           # wrong type
    ("supplier_cost_increase_pct", ">", True, "number"),                             # a bool is not a number
    ("supplier_cost_increase_pct", ">", 10**9, "out of range"),                      # out of bounds
    ("fy_month_elapsed", ">", 13, "out of range"),
    ("fy_month_elapsed", ">", 6.5, "whole number"),
])
def test_invalid_added_rule_is_rejected_with_a_readable_reason_and_nothing_saved(dirs, field, op, value, reason):
    before = _rules("finance")
    resp = _add("finance", "Bad rule", "no", field, op, value)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail.startswith("Rejected --") and reason in detail
    assert "pydantic" not in detail.lower() and "Traceback" not in detail
    assert _rules("finance") == before


def test_operator_must_suit_the_fields_type(dirs):
    assert _add("operations", "x", "no", "supplier_sla_in_place", ">", True).status_code == 422       # bool with >
    assert _add("delivery", "x", "no", "reported_rag_after", "==", "purple").status_code == 422       # not an enum option
    assert _add("delivery", "x", "no", "reported_rag_after", "<", "red").status_code == 422           # enum with <


def test_a_bad_description_stance_or_threshold_is_rejected(dirs):
    assert _add("finance", "", "no", "fy_month_elapsed", ">", 3).status_code == 422                  # empty description
    assert _add("finance", "x" * 300, "no", "fy_month_elapsed", ">", 3).status_code == 422           # too long
    assert _add("finance", "x", "maybe", "fy_month_elapsed", ">", 3).status_code == 422              # not a stance
    body = _payload("finance"); body["thresholds"] = {"margin_erosion_threshold_pts": -5}
    resp = client.put("/agents/finance/rules", json=body)
    assert resp.status_code == 422 and "margin_erosion_threshold_pts" in resp.json()["detail"]
    body["thresholds"] = {"lens": "x"}                                                               # not a declared threshold
    assert client.put("/agents/finance/rules", json=body).status_code == 422


def test_one_invalid_change_saves_none_of_the_batch(dirs):
    body = _payload("finance", supplier_cost_high={"stance": "conditional"})
    body["rules"].append({"label": "Bad", "stance": "no", "condition": {"field": "nope", "op": ">", "value": 1}})
    assert client.put("/agents/finance/rules", json=body).status_code == 422
    assert next(r for r in _rules("finance") if r["id"] == "supplier_cost_high")["stance"] == "no"   # the valid edit wasn't applied


def test_no_free_text_expression_can_get_in_by_any_route(dirs):
    _, configs_dir = dirs
    current = json.loads((configs_dir / "finance.json").read_text())["rules"]
    typed = {"id": "user_9", "label": "x", "description": "x", "fields": ["margin_erosion_pts"],
             "when": "margin_erosion_pts > 0", "stance": "no", "keywords": []}
    # a rule that isn't user_added / has no structured condition
    assert client.put("/agents/finance/config", json={"rules": [*current, typed]}).status_code == 422
    # user_added, but the `when` isn't the one generated from its condition
    forged = {**typed, "user_added": True, "fields": ["fy_month_elapsed"],
              "condition": {"field": "fy_month_elapsed", "op": ">", "value": 3}, "when": "fy_month_elapsed > 3 or True"}
    assert client.put("/agents/finance/config", json={"rules": [*current, forged]}).status_code == 422
    # an unsafe expression is refused by the engine before anything else
    unsafe = {**forged, "when": "__import__('os').system('true')"}
    assert client.put("/agents/finance/config", json={"rules": [*current, unsafe]}).status_code == 422
    assert not any(r.get("user_added") for r in json.loads((configs_dir / "finance.json").read_text())["rules"])


def test_a_rules_request_with_unexpected_keys_is_refused(dirs):
    assert client.put("/agents/finance/rules", json={"rules": [], "config": {"lens": "x"}}).status_code == 422


# ----------------------------------------------------------------- restart --

def test_a_saved_rule_survives_a_restart(dirs):
    manifest_path, configs_dir = dirs
    _add("finance", "Late in the year", "conditional", "fy_month_elapsed", ">=", 10)
    client.put("/agents/finance/rules", json={**_payload("finance", supplier_cost_high={"stance": "conditional"}),
                                               "thresholds": {"supplier_cost_increase_threshold_pct": 12}}
               | {"rules": [{"id": r["id"], **({"stance": "conditional"} if r["id"] == "supplier_cost_high" else {})} for r in _rules("finance")]})

    # a fresh process would read exactly this: load from disk, nothing in memory
    reloaded = {a.id: a for a in load_agents_from_manifest(manifest_path=manifest_path, configs_dir=configs_dir)}["finance"]
    user_rule = next(r for r in reloaded.config.rules if r.user_added)
    assert user_rule.label == "Late in the year" and user_rule.when == "fy_month_elapsed >= 10"
    assert next(r for r in reloaded.config.rules if r.id == "supplier_cost_high").stance == "conditional"
    assert reloaded.config.supplier_cost_increase_threshold_pct == 12
    assert reloaded.check({"fy_month_elapsed": 11}).stance == "conditional"


# --------------------------------- the decision changes when the rule does --

def _decide(facts):
    result = build_graph().invoke(
        initial_state("Supplier wants a 15% uplift on the fee.", facts), config={"recursion_limit": RECURSION_LIMIT}
    )
    return result


def test_changing_a_rule_changes_the_verdict_for_the_same_decision(dirs):
    facts = {"finance": {"supplier_cost_increase_pct": 15.0}}

    before = _decide(facts)
    assert before["checks"]["finance"]["stance"] == "no"
    assert before["reconciliation"]["recommendation"] != "No rule triggered on stated facts."

    body = _payload("finance"); body["thresholds"] = {"supplier_cost_increase_threshold_pct": 50}
    assert client.put("/agents/finance/rules", json=body).status_code == 200
    relaxed = _decide(facts)                                    # the same decision, re-run
    assert relaxed["checks"]["finance"]["triggered"] is False
    assert relaxed["reconciliation"]["recommendation"] == "No rule triggered on stated facts."

    body = _payload("finance", supplier_cost_high={"stance": "conditional"})
    body["thresholds"] = {"supplier_cost_increase_threshold_pct": 10}
    assert client.put("/agents/finance/rules", json=body).status_code == 200
    tightened = _decide(facts)
    assert tightened["checks"]["finance"]["stance"] == "conditional"          # rule now fires, softer stance
    assert tightened["reconciliation"]["recommendation"] not in (
        before["reconciliation"]["recommendation"], relaxed["reconciliation"]["recommendation"])


# ------------------------------------------------------ plain-English view --

RAW_NAME = re.compile(r"[a-z]+_[a-z_]+")


@pytest.mark.parametrize("agent_id", ["finance", "delivery", "pmo", "operations"])
def test_every_rule_reads_in_plain_english_with_no_raw_names_or_placeholders(dirs, agent_id):
    view = rules_view(get_agent(agent_id))
    assert view["rules"]
    for r in view["rules"]:
        shown = [r["label"], r["condition_text"]]
        if r["threshold"]:
            shown.append(r["threshold"]["label"])
        for text in shown:
            assert text and not RAW_NAME.search(text), f"{agent_id}/{r['id']}: {text!r}"
            assert not re.search(r"[{}<>‹›]", text), f"{agent_id}/{r['id']}: {text!r}"
    for f in view["fields"]:
        assert not RAW_NAME.search(f["label"])


def test_every_shipped_rule_has_a_plain_english_label():
    for agent in load_agents_from_manifest():
        for r in agent.config.rules:
            assert r.label.strip(), f"{agent.id}/{r.id} has no label"


def test_conditions_use_field_titles_and_the_current_values():
    finance = get_agent("finance")
    assert condition_text(finance, "supplier_cost_increase_pct > supplier_cost_increase_threshold_pct") == \
        "Supplier cost increase (%) is above 7%"
    ops = get_agent("operations")
    assert condition_text(ops, "licence_provisioned_for_new_date == False") == "Licence provisioned for the new date: no"
