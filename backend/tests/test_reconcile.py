from agents.delivery import DeliveryAgent
from agents.finance import FinanceAgent
from agents.operations import OperationsAgent
from agents.pmo import PMOAgent
from orchestrator.master import build_reconciliation, detect_conflict

AGENTS = [FinanceAgent(), DeliveryAgent(), PMOAgent(), OperationsAgent()]


def _positions(seed_input: str):
    return [agent.position_for(seed_input) for agent in AGENTS]


def test_detects_finance_delivery_conflict_structurally(seed_input):
    conflict = detect_conflict(_positions(seed_input))

    assert ("delivery", "finance") in conflict["disagreeing_pairs"]
    assert "delivery" in conflict["summary"]
    assert "finance" in conflict["summary"]


def test_trade_off_names_both_sides_real_constraints(seed_input):
    positions = _positions(seed_input)
    reconciliation = build_reconciliation(positions)

    finance_constraint = next(p for p in positions if p["agent"] == "finance")["driving_constraint"]
    delivery_constraint = next(p for p in positions if p["agent"] == "delivery")["driving_constraint"]

    assert finance_constraint in reconciliation["trade_off"]
    assert delivery_constraint in reconciliation["trade_off"]


def test_assumptions_and_not_considered_always_populated(seed_input):
    reconciliation = build_reconciliation(_positions(seed_input))

    assert reconciliation["assumptions"]
    assert reconciliation["not_considered"]


def test_operational_blocker_policy_wins_by_default(seed_input):
    reconciliation = build_reconciliation(_positions(seed_input))

    assert "Do not proceed" in reconciliation["recommendation"]
    assert "blocker" in reconciliation["why"].lower()
    assert "independent of the cost/schedule trade-off" in reconciliation["why"]
