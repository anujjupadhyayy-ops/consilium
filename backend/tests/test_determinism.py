"""P3.6-Rules-Trigger-Spec.md §6.9 -- the supplier_milestone seed must
produce an identical outcomes table and verdict direction across repeated
runs. The mocked half runs in the normal suite; the live half is gated
behind `pytest -m live` and is never run or claimed passed by the tool --
see docs/P3.6-BUILD-REPORT.md for the exact owner command.
"""
import pytest

from orchestrator.graph import build_graph
from orchestrator.state import initial_state


def _outcomes_table(result) -> dict:
    return {
        agent_id: (check["triggered"], check["stance"], tuple(sorted(check["fired"])))
        for agent_id, check in result["checks"].items()
    }


def test_seed_x5_mocked_model_identical_outcomes_and_verdict_direction(seed_input, seed_facts):
    """Model mocked off (conftest's autouse fixture) -- five independent
    runs of the deterministic fallback path must agree exactly."""
    tables = []
    directions = []
    for _ in range(5):
        compiled = build_graph()
        result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})
        tables.append(_outcomes_table(result))
        directions.append(result["reconciliation"]["recommendation"])

    assert all(t == tables[0] for t in tables), f"outcomes table varied across runs: {tables}"
    assert all(d == directions[0] for d in directions), f"verdict direction varied across runs: {directions}"


@pytest.mark.live
def test_seed_x5_live_model_identical_outcomes_and_verdict_direction(seed_input, seed_facts):
    """Owner-run only (`pytest -m live tests/test_determinism.py`), against
    whatever model is configured in the environment. Wording may differ run
    to run; the outcomes table (which agents trigger, which rules fire) and
    the verdict's DIRECTION must not."""
    tables = []
    directions = []
    for _ in range(5):
        compiled = build_graph()
        result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})
        tables.append(_outcomes_table(result))
        directions.append("decline" in result["reconciliation"]["recommendation"].lower())

    assert all(t == tables[0] for t in tables), f"outcomes table varied across live runs: {tables}"
    assert all(d == directions[0] for d in directions), f"verdict direction varied across live runs: {directions}"
