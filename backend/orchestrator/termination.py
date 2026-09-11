from __future__ import annotations

from .state import ConsiliumState

# route (1) must have completed, and only route, before reconcile may run.
# This is a belt-and-braces guard alongside the graph's own acyclic topology
# and LangGraph's recursion_limit -- see graph.py.
MAX_PRIOR_STEPS = 1


class BoundedTerminationError(RuntimeError):
    pass


def assert_bounded(state: ConsiliumState, max_prior_steps: int = MAX_PRIOR_STEPS) -> None:
    if state["step_count"] > max_prior_steps:
        raise BoundedTerminationError(
            f"step_count {state['step_count']} exceeds the bound of "
            f"{max_prior_steps} -- refusing to continue. Consilium v1 is a "
            "single-pass orchestration: one routing pass, one parallel "
            "specialist pass, one reconcile. No agent-to-agent loops."
        )
