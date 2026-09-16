# Agent Logic Spec (reference example)

*Illustrative, user-definable example agents that demonstrate the framework's capability — the
sophistication of logic an agent can hold — not a prescribed or "correct" rule set. Consilium is a
domain-agnostic multi-agent decision framework; agent rules are swappable config a forker defines
for their own world. The depth is shown by how much complexity the framework can carry, not by
whose rules these are.*

**Architecture requirement (enables the editable-agents UI):** every agent's rules/instructions/
thresholds are stored as editable, serializable config (data or an editable prompt/policy object
loaded at runtime) — never hardcoded in Python. The reconcile engine reads structured stances, not
agent internals. A user can change an agent's rules, and add/remove agents, without touching code.

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
