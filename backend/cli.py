"""P1 entry point: run the supplier-milestone seed through the graph and
print the full trace legibly -- routing reasoning, all 4 positions, the
disagreement, and the reconciliation with its trade-off named."""
from __future__ import annotations

from dotenv import find_dotenv, load_dotenv

# Loaded here, not just in model/config.py -- P1's run path never imports
# the model layer, but LangSmith tracing env vars (LANGCHAIN_*) still need
# to reach the process before orchestrator.graph runs the seed.
load_dotenv(find_dotenv(usecwd=True))

from orchestrator.graph import run_seed  # noqa: E402
from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED  # noqa: E402


def _header(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def main() -> None:
    seed = SUPPLIER_MILESTONE_SEED

    _header(f"CONSILIUM -- {seed['title']}")
    print(f"\nScenario: {seed['scenario']}")
    print(f"Why this needs several functions: {seed['why_multi_function']}")

    result = run_seed(seed["scenario"], seed["facts"])

    _header("ROUTING")
    print(f"Routed to: {', '.join(result['routed_agents'])}")
    print(f"Reasoning: {result['routing_reasoning']}")

    _header("SPECIALIST POSITIONS")
    for position in result["positions"]:
        print(f"\n[{position['agent'].upper()}] {position['recommendation']}  (stance: {position['stance']})")
        print(f"  Reasoning: {position['reasoning']}")
        print(f"  Lead figure: {position['lead_figure']}")

    _header("THE DISAGREEMENT")
    conflict = result["conflict"]
    print(conflict["summary"])
    for a, b in conflict["disagreeing_pairs"]:
        print(f"  - {a} vs {b}")
    if conflict["blocker_notes"]:
        print("Blockers:")
        for note in conflict["blocker_notes"]:
            print(f"  - {note}")
    if conflict["conditional_notes"]:
        print("Conditional constraints:")
        for note in conflict["conditional_notes"]:
            print(f"  - {note}")

    _header("RECONCILIATION")
    reconciliation = result["reconciliation"]
    print(f"Recommendation: {reconciliation['recommendation']}")
    print(f"Why: {reconciliation['why']}")
    print(f"Trade-off: {reconciliation['trade_off']}")
    print("\nAssumptions made:")
    for assumption in reconciliation["assumptions"]:
        print(f"  - {assumption}")
    print("\nWhat this did NOT consider:")
    for item in reconciliation["not_considered"]:
        print(f"  - {item}")
    print()


if __name__ == "__main__":
    main()
