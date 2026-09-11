from orchestrator.state import AgentPosition

from .base import StubAgent


class PMOAgent(StubAgent):
    name = "pmo"

    def position_for(self, seed_input: str) -> AgentPosition:
        return AgentPosition(
            agent=self.name,
            stance="conditional",
            recommendation="Conditional yes -- only via formal change control",
            reasoning=(
                "Pulling this milestone forward re-sequences shared resource "
                "against another workstream's sprint plan. It can proceed, but "
                "only through a formal contract-variation change request, not "
                "as an in-flight adjustment."
            ),
            driving_constraint=(
                "Requires Change Control Gate 2 (contract variation) sign-off "
                "before the supplier can be instructed"
            ),
        )
