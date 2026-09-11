import pytest

from orchestrator.state import initial_state
from orchestrator.termination import BoundedTerminationError, assert_bounded


def test_assert_bounded_passes_at_the_limit():
    state = initial_state("scenario")
    state["step_count"] = 1  # only route has run

    assert_bounded(state)  # should not raise


def test_assert_bounded_raises_over_the_limit():
    state = initial_state("scenario")
    state["step_count"] = 2  # route has run twice, or looped back -- not allowed

    with pytest.raises(BoundedTerminationError):
        assert_bounded(state)
