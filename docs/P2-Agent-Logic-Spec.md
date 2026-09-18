# Agent Logic Spec (reference example)

*Illustrative, user-definable example agents that demonstrate the framework's capability — the
sophistication of logic an agent can hold — not a prescribed or "correct" rule set. Consilium is a
domain-agnostic multi-agent decision framework; agent rules are swappable config a forker defines
for their own world. The depth is shown by how much complexity the framework can carry, not by
whose rules these are.*

**Architecture requirement (enables the editable-agents UI):** every agent's rules/instructions/
thresholds are stored as editable, serializable config (data or an editable prompt/policy object
loaded at runtime) — never hardcoded in Python. The reconcile engine reads structured stances, not
agent internals. (P3.6: those stances now come from `rules[]` — see "As shipped" at the end.) A user can change an agent's rules, and add/remove agents, without touching code.

---

## Finance agent

**No-line (hard triggers for a "No" stance):**
- Change erodes expected **project profit margin by more than 5 percentage points** → No.
- **Any single supplier's cost rises more than 7%** above its budgeted figure → No.

**Cost-of-delay vs cost-of-service:** don't hardcode a fixed cost-of-delay figure — it is
milestone-driven and too specific for a generic finance agent. Instead apply a deep-but-generic
finance sub-lens: reason qualitatively about the margin/revenue impact of a timeline change
(revenue-at-risk, margin/penalty exposure) without a fixed formula, and defer the milestone-specific
delay mechanics to the Delivery agent. Keep it defensible and general.

**3PP budget headroom (the distinctive, time-phased rule — flag the forecast, not spot spend):**
- Hard rule: never forecast full-year spend to exceed **100% of budget**.
- The flag is on the **full-year forecast**, weighted by **when in the FY it is read**. A forecast
  full-year utilisation **≥80% seen EARLY** in the FY (e.g. month 2) = red flag → monitor all year.
  The **same or higher seen LATE** (e.g. month 12), still within budget = **not** a concern. The
  point-in-time of the forecast is what matters.
- Encode as: concern rises with forecast utilisation and falls with months elapsed — high forecast
  early = red; high-but-within-budget late = fine.
- Generic overspend test threshold: treat **5% over budget** as the breach.

**Lead figure in a position:** cite whichever threshold the scenario trips — margin-erosion %,
supplier-cost-increase %, or forecast-utilisation % + the month it is read — so the position reads
as evidenced, e.g. *"No — erodes project margin ~6% (>5% line)."*

---

## Delivery agent

*Industry-standard EVM baseline plus a deliberate nuance. Illustrative; values/tags are
user-definable.*

**Baseline (industry standard):** earned value — `EV = budget × actual%`, `PV = budget ×
schedule%`, `SPI = EV/PV`, `CPI = EV/spend`, `EAC = budget/CPI`; `slip = forecast/actual date −
baseline`; per-milestone RAG (on-track / at-risk / slipped).

**Nuance (the non-generic edge):**
1. **Effective RAG** — an *unresourced* milestone cannot be green: `effective RAG = resourced ?
   RAG : max(RAG, amber)`. Delivery hard-flags unresourced work regardless of reported status.
2. **Criticality ≠ health** — the critical-path flag is *consequence if it slips*, not current
   status; a critical milestone can legitimately be green. Keep "important" and "in trouble"
   separate.
3. **Critical Revenue at Risk (headline lens):** `Revenue at Risk = Σ value of revenue-tagged
   milestones with effective RAG amber/red`; `Critical Revenue at Risk = that subset also on the
   critical path` = the money that threatens go-live. Delivery reasons from this exception number,
   not the full status board.

**Positions:**
- **Yes** — the change reduces Critical Revenue at Risk (de-risks a milestone that is on the
  critical path AND amber/red).
- **Conditional** — helps schedule but the milestone is unresourced (can't go green until staffed)
  or is off the critical path.
- **No** — doesn't touch critical-path revenue exposure, or worsens SPI/CPI without protecting
  go-live revenue.

**Lead figure:** Critical Revenue at Risk (£ + direction), backed by SPI / slip days.

---

## PMO agent

*PRINCE2/MSP governance baseline plus a four-pillar operating model. Illustrative;
standards/gates user-definable.*

**Baseline (industry standard):** PRINCE2 / MSP governance — stage gates, change control,
continued business-case justification, tolerances (time / cost / scope / quality / risk /
benefit), RAID.

**Nuance — the four-pillar model, one consistent yardstick applied up and down:**
1. **Portfolio** — enforces PRINCE2/PM standards across the portfolio; owns commercials (cost,
   billing, revenue), forecast & delivery, portfolio health & performance.
2. **Delivery** — the same discipline, deeper, at programme level.
3. **PMs** — deliver the projects to the *same* standard/PRINCE2 yardstick the Portfolio PMO
   enforces (consistency of standard across every level is itself the control).
4. **Reporting** — produces the decks/reports; owns the decision's visibility, escalation and
   reporting implications.

**How it reasons on a decision:** is it compliant with the PM standard; is a tolerance breached
(and does that require escalation); what governance/change-control gate must it pass; portfolio
contention/health impact; reporting/visibility consequence. This pillar also carries
contract-variation routing — "does this need a variation, and via what gate."

**Positions:**
- **Conditional (its most common voice)** — "proceed, but via the correct gate": needs a change
  request / stage-gate / tolerance-breach escalation before it can go ahead.
- **No / flag** — breaches the PRINCE2 standard, exceeds a tolerance without escalation, or lacks
  continued business-case justification.
- **Yes** — compliant, within tolerance, no gate required.

**Lead consideration:** the governance route + tolerance status (which tolerance, breached or
not; which gate applies), plus portfolio-health/contention impact.

---

## Operations agent

*Four-signal operational-health model plus a weakest-of-four verdict. Illustrative; thresholds
user-definable.*

**Lens — four operational signals:**
1. **Capacity** — billable vs business-overhead utilisation; can the operation absorb the work
   (capacity → cost-of-delivery).
2. **Third-party spend** — is 3PP spend on budget (budget → cost-of-service).
3. **Savings** — are committed savings actually landing, not just planned.
4. **Supplier / SLA & licence-kit control** — are supplier contracts, SLAs, and licence/3PP-kit
   inventory in place and under control.

**Nuance (the distinctive synthesis rule):** **Operational Health = the WEAKEST of the four
signals, not an average** — "focus-first" framing. One red signal governs the verdict regardless
of the other three. (Mirrors the reconcile engine's operational-blocker-wins policy.)

**Positions:**
- **Blocker / No** — a hard operational constraint: capacity can't absorb it, or licence/3PP-kit/SLA
  isn't in place (e.g. an early-cutover licence not provisioned until the original date).
  Independent of cost/schedule merit.
- **Conditional** — feasible but degrades a signal (utilisation past threshold, savings at risk,
  SLA strained).
- **Yes** — the operation can absorb it and all four signals hold.

**Lead figure:** the weakest of the four signals (the binding constraint) + its RAG.

---

## As shipped: each agent's logic as rules

*The rules-engine form of the logic above (`backend/agents/configs/*.json`). `fields` are the facts a rule needs — if any is unstated the rule can't fire and is reported "couldn't check". Thresholds are editable config scalars; blocker rules are system-governed and carry tripwire `keywords`. The agent's stance is the most severe fired rule.*


### Finance

Derived values: `hard_breach_threshold_pct` = 100 + `generic_overspend_test_pct`; `forecast_concern_threshold_pct` = the early/late anchors linearly interpolated at `fy_month_elapsed` (unstated if `fy_month_elapsed` is). No rule for "yes": nothing tripping is the *all rules checked — none tripped* state.

| id | fields | when | stance | keywords |
|---|---|---|---|---|
| `supplier_cost_high` | `supplier_cost_increase_pct` | `supplier_cost_increase_pct > supplier_cost_increase_threshold_pct` | no | — |
| `margin_erosion_high` | `margin_erosion_pts` | `margin_erosion_pts > margin_erosion_threshold_pts` | no | — |
| `forecast_hard_breach` | `budget_forecast_utilisation_pct` | `budget_forecast_utilisation_pct > hard_breach_threshold_pct` | no | — |
| `forecast_early_warning` | `budget_forecast_utilisation_pct`, `fy_month_elapsed` | `budget_forecast_utilisation_pct >= forecast_concern_threshold_pct` | conditional | — |

### Delivery

Derived values: `rag_{before,after}_severity` (green 0 / amber 1 / red 2) and `crar_*` (Critical Revenue at Risk before/after/reduction, using the configured unresourced floor) — the latter only when all six fields are stated. All three rules share one description, so the driving constraint always reads "Critical Revenue at Risk <reduced|unchanged|increased> by £X (£a -> £b)".

| id | fields | when | stance | keywords |
|---|---|---|---|---|
| `reduces_critical_revenue_at_risk` | `is_resourced`, `is_on_critical_path`, `is_revenue_tagged`, `revenue_value`, `reported_rag_before`, `reported_rag_after` | `crar_reduction > 0` | yes | — |
| `schedule_improves_but_does_not_reduce_crar` | `is_resourced`, `is_on_critical_path`, `is_revenue_tagged`, `revenue_value`, `reported_rag_before`, `reported_rag_after` | `rag_after_severity < rag_before_severity and crar_reduction <= 0` | conditional | — |
| `no_schedule_improvement` | `is_resourced`, `is_on_critical_path`, `is_revenue_tagged`, `revenue_value`, `reported_rag_before`, `reported_rag_after` | `rag_after_severity >= rag_before_severity` | no | — |

### PMO

Derived values flatten the dict-shaped variance fact and tolerance config into scalars: `tv_<dim>` (0 for an omitted dimension *within a stated* `tolerance_variances_pct`; absent if the dict itself is unstated), `tol_<dim>`, `tol_<dim>_hard_reject` (tolerance × `hard_reject_multiple_of_tolerance`) and negated `neg_tol_*` variants (the evaluator has no unary minus). `portfolio_contention` has **no rule**: when PMO triggers, "It also re-sequences shared resource against another workstream's plan" is appended to its reasoning. The conditional driving constraint collapses every breaching dimension onto at most two gate names ("Requires <gate>, <gate> sign-off before proceeding").

| id | fields | when | stance | keywords |
|---|---|---|---|---|
| `missing_business_case` | `continued_business_case_justified` | `continued_business_case_justified == False` | no | — |
| `cost_tolerance_hard_reject` | `tv_cost` | `tv_cost > tol_cost_hard_reject` | no | — |
| `time_tolerance_hard_reject` | `tv_time` | `tv_time > tol_time_hard_reject` | no | — |
| `scope_tolerance_hard_reject` | `tv_scope` | `tv_scope > tol_scope_hard_reject` | no | — |
| `risk_tolerance_hard_reject` | `tv_risk` | `tv_risk > tol_risk_hard_reject` | no | — |
| `quality_tolerance_hard_reject` | `tv_quality` | `tv_quality < neg_tol_quality_hard_reject` | no | — |
| `benefit_tolerance_hard_reject` | `tv_benefit` | `tv_benefit < neg_tol_benefit_hard_reject` | no | — |
| `cost_tolerance_breach` | `tv_cost` | `tv_cost > tol_cost` | conditional | — |
| `time_tolerance_breach` | `tv_time` | `tv_time > tol_time` | conditional | — |
| `scope_tolerance_breach` | `tv_scope` | `tv_scope > tol_scope` | conditional | — |
| `risk_tolerance_breach` | `tv_risk` | `tv_risk > tol_risk` | conditional | — |
| `quality_tolerance_breach` | `tv_quality` | `tv_quality < neg_tol_quality` | conditional | — |
| `benefit_tolerance_breach` | `tv_benefit` | `tv_benefit < neg_tol_benefit` | conditional | — |
| `contract_variation_gate` | `is_contract_variation` | `is_contract_variation == True` | conditional | — |

### Operations

Each threshold rule names its own config scalar directly. Five *independent* single-field blocker rules — any one alone triggers — is what lets "licence not provisioned" fire even when capacity, spend and savings are never mentioned. Licence and SLA are two fields but one signal ("Supplier/SLA & licence-kit control"); the driving constraint joins every signal tied at the top severity: "Weakest signal: Capacity, Third-party spend (RED)". Tripwire keywords are specific to each fact — no generic domain words.

| id | fields | when | stance | keywords |
|---|---|---|---|---|
| `capacity_red` | `capacity_utilisation_pct_if_accepted` | `capacity_utilisation_pct_if_accepted >= capacity_red_threshold_pct` | blocker | capacity, headcount, overtime |
| `spend_red` | `third_party_spend_pct_of_budget` | `third_party_spend_pct_of_budget >= spend_red_threshold_pct` | blocker | third-party spend, third party spend, 3pp |
| `savings_red` | `savings_delivery_ratio` | `savings_delivery_ratio < savings_red_threshold_ratio` | blocker | savings, cost reduction |
| `licence_not_provisioned` | `licence_provisioned_for_new_date` | `licence_provisioned_for_new_date == False` | blocker | licence, license, provisioned |
| `supplier_sla_not_in_place` | `supplier_sla_in_place` | `supplier_sla_in_place == False` | blocker | sla, service level |
| `capacity_amber` | `capacity_utilisation_pct_if_accepted` | `capacity_utilisation_pct_if_accepted >= capacity_amber_threshold_pct and capacity_utilisation_pct_if_accepted < capacity_red_threshold_pct` | conditional | — |
| `spend_amber` | `third_party_spend_pct_of_budget` | `third_party_spend_pct_of_budget >= spend_amber_threshold_pct and third_party_spend_pct_of_budget < spend_red_threshold_pct` | conditional | — |
| `savings_amber` | `savings_delivery_ratio` | `savings_delivery_ratio < savings_amber_threshold_ratio and savings_delivery_ratio >= savings_red_threshold_ratio` | conditional | — |
