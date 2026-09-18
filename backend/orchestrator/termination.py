from __future__ import annotations

from .state import ConsiliumState

# P3.6: the graph is two supersteps -- every agent checks its own rules in
# parallel (extract -> check -> narrate, internally, no separate routing
# stage), then reconcile. One prior step (the fan-out) must have completed,
# and only that one, before reconcile may run. This is a belt-and-braces
# guard alongside the graph's own acyclic topology and LangGraph's
# recursion_limit -- see graph.py.
MAX_PRIOR_STEPS = 1


class BoundedTerminationError(RuntimeError):
    pass


def assert_bounded(state: ConsiliumState, max_prior_steps: int = MAX_PRIOR_STEPS) -> None:
    if state["step_count"] > max_prior_steps:
        raise BoundedTerminationError(
            f"step_count {state['step_count']} exceeds the bound of "
            f"{max_prior_steps} -- refusing to continue. Consilium v1 is a "
            "single-pass orchestration: one parallel specialist pass "
            "(extract -> check -> narrate), one reconcile. No agent-to-agent loops."
        )
