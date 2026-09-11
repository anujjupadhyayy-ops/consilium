from orchestrator.state import AgentPosition

from .base import StubAgent


class DeliveryAgent(StubAgent):
    name = "delivery"

    def position_for(self, seed_input: str) -> AgentPosition:
        return AgentPosition(
            agent=self.name,
            stance="yes",
            recommendation="Yes -- pull the milestone forward",
            reasoning=(
                "This milestone sits on the critical path. Pulling it forward "
                "3 weeks removes the single largest schedule risk in the plan "
                "and directly de-risks a revenue-recognition date."
            ),
            driving_constraint=(
                "£420k of revenue currently exposed to the 3-week "
                "slippage risk this variation removes"
            ),
        )
