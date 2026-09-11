from orchestrator.state import AgentPosition

from .base import StubAgent


class FinanceAgent(StubAgent):
    name = "finance"

    def position_for(self, seed_input: str) -> AgentPosition:
        return AgentPosition(
            agent=self.name,
            stance="no",
            recommendation="No -- do not accept the variation as proposed",
            reasoning=(
                "The 15% cost increase breaches this workstream's approved margin "
                "threshold. A one-off schedule benefit doesn't offset a "
                "recurring-basis cost-of-service increase of this size."
            ),
            driving_constraint=(
                "15% cost increase vs an 8% approved margin-erosion threshold "
                "for this workstream"
            ),
        )
