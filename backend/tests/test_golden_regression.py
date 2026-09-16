"""P3.6-Rules-Trigger-Spec.md §6.3 -- the migration's regression control.
Golden files (tests/golden/*.json) were generated from the CURRENT,
unmigrated `evaluate()` (tests/golden/generate.py) and committed before any
rules-engine logic existed. As each agent migrates to rules[], its new
check()-based output must match those golden outputs under the §5.3.4
equivalence rule -- any genuine difference gets logged in
docs/P3.6-migration-diffs.md and that agent's test here marked
xfail(strict=True) pointing at the diff, never silently accepted.
"""
import json
from pathlib import Path

from agents.registry import get_agent

GOLDEN_DIR = Path(__file__).parent / "golden"


def _new_result(agent, facts: dict):
    """(stance, driving_constraint, unchecked) from the NEW rules-based
    path -- stance/driving_constraint are None when nothing triggered."""
    result = agent.check(facts)
    if result.stance is None:
        return None, None, result.unchecked
    position = agent._position_from_check(facts, result)
    return result.stance, position["driving_constraint"], result.unchecked


def _equivalent(old_stance: str, old_constraint: str, new_stance, new_constraint, new_unchecked) -> bool:
    """P3.6 §5.3.4: stance must match exactly, EXCEPT old `yes` is
    equivalent to new not-triggered-with-no-unchecked-fields (the
    "all rules checked, none tripped" all-clear card -- P3.6 change 3)
    UNLESS a new `yes` rule fires, in which case new stance is genuinely
    `yes` and compared normally. Old driving constraint must be ONE OF
    the new fired rules' rendered constraints (new may list more, e.g.
    Operations listing every red/amber signal instead of picking one
    "weakest" -- that's not itself a difference)."""
    if new_stance is None:
        return old_stance == "yes" and not new_unchecked
    if old_stance != new_stance:
        return False
    return old_constraint in (new_constraint or "")


def _run_golden_check(agent_id: str) -> list[dict]:
    agent = get_agent(agent_id)
    golden = json.loads((GOLDEN_DIR / f"factsets_{agent_id}.json").read_text())
    mismatches = []
    for case in golden:
        new_stance, new_constraint, new_unchecked = _new_result(agent, case["facts"])
        if not _equivalent(case["stance"], case["driving_constraint"], new_stance, new_constraint, new_unchecked):
            mismatches.append({
                "facts": case["facts"],
                "old": (case["stance"], case["driving_constraint"]),
                "new": (new_stance, new_constraint),
            })
    return mismatches


def _assert_matches_golden(agent_id: str) -> None:
    mismatches = _run_golden_check(agent_id)
    assert not mismatches, (
        f"{agent_id}: {len(mismatches)} golden mismatch(es) -- see docs/P3.6-migration-diffs.md. "
        f"First few: {mismatches[:3]}"
    )


def test_finance_matches_golden_factsets():
    _assert_matches_golden("finance")


def test_pmo_matches_golden_factsets():
    _assert_matches_golden("pmo")


def test_operations_matches_golden_factsets():
    _assert_matches_golden("operations")


def test_delivery_matches_golden_factsets():
    _assert_matches_golden("delivery")


def test_seed_golden_matches():
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    seed_golden = json.loads((GOLDEN_DIR / "seed_supplier_milestone.json").read_text())
    failures = []
    for agent_id, expected in seed_golden.items():
        agent = get_agent(agent_id)
        new_stance, new_constraint, new_unchecked = _new_result(agent, SUPPLIER_MILESTONE_SEED["facts"][agent_id])
        if not _equivalent(expected["stance"], expected["driving_constraint"], new_stance, new_constraint, new_unchecked):
            failures.append(f"{agent_id}: old={expected}, new=({new_stance!r}, {new_constraint!r})")
    assert not failures, "\n".join(failures)
