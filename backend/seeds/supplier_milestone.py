"""The one seed in scope for P1: "supplier milestone variation" (docs/01).

The other 3 seeds from the Agent Profiles doc (budget overrun, resourcing
clash, Project PME compliance) are P2+ scope -- not stubbed here.
"""

SUPPLIER_MILESTONE_SEED = {
    "id": "supplier_milestone",
    "title": "Supplier milestone variation",
    "scenario": (
        "A 3rd-party supplier offers to pull a delivery milestone forward "
        "3 weeks for a 15% cost increase and a contract variation."
    ),
    "why_multi_function": (
        "No single function can answer this alone: it trades cost (Finance) "
        "against schedule risk (Delivery), needs a governance route (PMO), "
        "and depends on whether the operation can actually absorb the "
        "pulled-forward work (Operations)."
    ),
}
