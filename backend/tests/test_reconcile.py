from agents.registry import load_agents_from_manifest
from orchestrator.chief_of_staff import build_reconciliation, detect_conflict


def _positions(seed_facts: dict):
    """P3.6 rewrite: evaluate() is deleted -- build each triggered agent's
    position via check()/_position_from_check() instead. Every agent in
    the seed genuinely triggers, so this is a like-for-like replacement,
    not a scope reduction."""
    agents = load_agents_from_manifest()
    positions = []
    for agent in agents:
        result = agent.check(seed_facts[agent.id])
        assert result.stance is not None, f"{agent.id} must trigger on the seed's engineered facts"
        positions.append(agent._position_from_check(seed_facts[agent.id], result))
    return positions


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
    """build_reconciliation() states the factual blocker detail; the global
    policy sentence itself is _enforce_blocker_policy's job (applied to
    every reconciliation path, not just this deterministic fallback) --
    see test_chief_of_staff.py for that guarantee end-to-end. Asserting the
    policy text here too used to duplicate it whenever this fallback ran."""
    reconciliation = build_reconciliation(_positions(seed_facts))

    assert "Do not proceed" in reconciliation["recommendation"]
    assert "blocker" in reconciliation["why"].lower()
    assert "moot until resolved" in reconciliation["why"]
