from agents.registry import load_agents_from_manifest
from orchestrator.chief_of_staff import build_reconciliation, detect_conflict


def _positions(seed_facts: dict):
    agents = load_agents_from_manifest()
    return [agent.evaluate(seed_facts[agent.id]) for agent in agents]


def test_detects_finance_delivery_conflict_structurally(seed_facts):
    conflict = detect_conflict(_positions(seed_facts))

    # The yes/no clash is still detected structurally even though the
    # summary text leads with the blocker (operations) -- blockers take
    # narrative priority since they make the yes/no trade-off moot.
    assert ("delivery", "finance") in conflict["disagreeing_pairs"]


def test_summary_leads_with_the_blocker_when_one_is_present(seed_facts):
    conflict = detect_conflict(_positions(seed_facts))

    assert "operations" in conflict["summary"]
    assert "blocker" in conflict["summary"]


def test_blocker_notes_capture_operations(seed_facts):
    conflict = detect_conflict(_positions(seed_facts))

    assert any(note.startswith("operations:") for note in conflict["blocker_notes"])


def test_trade_off_names_both_sides_real_constraints(seed_facts):
    positions = _positions(seed_facts)
    reconciliation = build_reconciliation(positions)

    finance_constraint = next(p for p in positions if p["agent"] == "finance")["driving_constraint"]
    delivery_constraint = next(p for p in positions if p["agent"] == "delivery")["driving_constraint"]

    assert finance_constraint in reconciliation["trade_off"]
    assert delivery_constraint in reconciliation["trade_off"]


def test_assumptions_and_not_considered_always_populated(seed_facts):
    reconciliation = build_reconciliation(_positions(seed_facts))

    assert reconciliation["assumptions"]
    assert reconciliation["not_considered"]


def test_blocker_policy_wins_by_default(seed_facts):
    reconciliation = build_reconciliation(_positions(seed_facts))

    assert "Do not proceed" in reconciliation["recommendation"]
    assert "blocker" in reconciliation["why"].lower()
    assert "independent of the cost/schedule trade-off" in reconciliation["why"]
