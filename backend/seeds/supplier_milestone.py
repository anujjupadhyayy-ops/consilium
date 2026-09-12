"""The one seed in scope for P1/P2: "supplier milestone variation" (docs/01).

`facts` are structured, per-agent decision inputs -- P2's config-driven
agents evaluate these deterministically (no LLM parsing of free text).
Values are engineered to reproduce the designed conflict via real rule
evaluation, not by hand-writing the verdict: Finance=no (supplier-cost
no-line), Delivery=yes (de-risks Critical Revenue at Risk), PMO=conditional
(tolerance breach + contract-variation gate), Operations=blocker (licence
not provisioned for the pulled-forward date).

The other 3 seeds from the Agent Profiles doc (budget overrun, resourcing
clash, Project PME compliance) are P3+ scope -- not stubbed here.
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
    "facts": {
        "finance": {
            "margin_erosion_pts": 3.0,
            "supplier_cost_increase_pct": 15.0,
            "budget_forecast_utilisation_pct": 60.0,
            "fy_month_elapsed": 6,
        },
        "delivery": {
            "budget": 1_000_000,
            "actual_pct": 0.55,
            "schedule_pct": 0.65,
            "spend_to_date": 600_000,
            "slip_days_before_change": 15,
            "is_resourced": True,
            "is_on_critical_path": True,
            "is_revenue_tagged": True,
            "revenue_value": 420_000,
            "reported_rag_before": "amber",
            "reported_rag_after": "green",
        },
        "pmo": {
            "is_contract_variation": True,
            "continued_business_case_justified": True,
            "portfolio_contention": True,
            "tolerance_variances_pct": {"cost": 15.0},
        },
        "operations": {
            "capacity_utilisation_pct_if_accepted": 85.0,
            "third_party_spend_pct_of_budget": 92.0,
            "savings_delivery_ratio": 0.95,
            "licence_provisioned_for_new_date": False,
            "supplier_sla_in_place": True,
        },
    },
}
