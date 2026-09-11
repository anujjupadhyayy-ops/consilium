import pytest

from agents.delivery import DeliveryAgent
from agents.finance import FinanceAgent
from agents.operations import OperationsAgent
from agents.pmo import PMOAgent
from orchestrator.state import initial_state

ALL_AGENTS = [FinanceAgent(), DeliveryAgent(), PMOAgent(), OperationsAgent()]


@pytest.mark.parametrize("agent", ALL_AGENTS, ids=lambda a: a.name)
def test_stub_agent_returns_a_valid_position(agent, seed_input):
    position = agent.position_for(seed_input)

    assert position["agent"] == agent.name
    assert position["stance"] in ("yes", "no", "conditional")
    assert position["recommendation"]
    assert position["reasoning"]
    assert position["driving_constraint"]


@pytest.mark.parametrize("agent", ALL_AGENTS, ids=lambda a: a.name)
def test_agent_run_emits_one_position_and_one_trace_event(agent, seed_input):
    state = initial_state(seed_input)

    update = agent.run(state)

    assert len(update["positions"]) == 1
    assert update["positions"][0]["agent"] == agent.name
    assert len(update["trace"]) == 1
    assert update["trace"][0]["kind"] == "position"
    assert update["trace"][0]["agent"] == agent.name


def test_supplier_milestone_seed_produces_the_designed_conflict(seed_input):
    stances = {agent.name: agent.position_for(seed_input)["stance"] for agent in ALL_AGENTS}

    assert stances["finance"] == "no"
    assert stances["delivery"] == "yes"
    assert stances["pmo"] == "conditional"
    assert stances["operations"] == "conditional"
