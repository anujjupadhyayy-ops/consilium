from orchestrator.state import AgentPosition

from .base import StubAgent


class OperationsAgent(StubAgent):
    name = "operations"

    def position_for(self, seed_input: str) -> AgentPosition:
        return AgentPosition(
            agent=self.name,
            stance="conditional",
            recommendation="Blocked -- cannot absorb the pulled-forward work yet",
            reasoning=(
                "Even if Finance, Delivery and PMO agree, the operational team "
                "cannot absorb the pulled-forward work in its current form -- "
                "the licence/kit required for early cutover isn't provisioned "
                "until the original date."
            ),
            driving_constraint=(
                "3PP licence for the cutover kit is not active until the "
                "original milestone date -- a 3-week pull-forward exceeds "
                "current licence coverage"
            ),
        )
