# Agent Profiles & Orchestration — Consilium
Owner: Anuj Upadhyay · Drafted with Claude · 2026-09-09 · v0.2 (agents: Finance / Delivery / PMO / Operations)

**Design principle:** each agent carries *real domain logic*, not a "you are a finance expert" prompt. This is the un-copyable layer — the same judgement you encode in your dashboards, "through Anuj's eyes." Fill the specifics in your own words during P2; the frames below are the skeleton, not the flesh.

---

## The master orchestrator
The intellect of the system. Four jobs, in order:

1. **Route** — read the input, decide which specialists are relevant and *why*, and say so out loud (this text renders in the trace). It must be willing to say "Operations isn't needed here" — selective routing is itself a sign of judgement.
2. **Clarify (conditional)** — if the input is too thin to route well (no numbers, no timeframe, no constraint), ask 1–2 sharp questions before dispatching. This behaviour separates "colleague" from "prompt box."
3. **Dispatch & collect** — run the chosen specialists in parallel; gather each one's *position* (recommendation + reasoning + the one number/constraint that drives it).
4. **Reconcile** — the money shot. Surface where specialists **disagree**, weigh the trade-off explicitly, and produce one recommendation that names what it optimises for and what it sacrifices. Never average the agents into mush; adjudicate.

**Output contract (every run):** Recommendation · Why · Key trade-off · Assumptions made · What this did NOT consider. The last two lines are the guardrail — honest, and themselves a maturity signal legible to a non-technical exec.

---

## Finance agent
- **Lens:** cost-of-service vs cost-of-delay, margin protection, 3PP budget mechanics.
- **Reasons about:** CoS impact of any change; whether a cost increase breaches margin thresholds; 3PP budget headroom; one-off vs recurring; who absorbs the variance.
- **Drives its position on:** the margin/budget number. Says no when the number breaks — and states the number.
- **Anuj to encode (P2):** real margin thresholds, CoD treatment, how a 3PP overspend cascades.

## Delivery agent
- **Lens:** critical path, milestone health, resourcing reality, revenue-at-risk.
- **Reasons about:** does the item touch the critical path; schedule benefit/harm; is the work *resourced*; what revenue is exposed if the milestone slips.
- **Drives its position on:** critical-path impact + revenue-at-risk. Says yes to things that de-risk the path even at a cost.
- **Anuj to encode (P2):** resourced-vs-unresourced flagging, critical-revenue-at-risk logic (from the Delivery Dashboard).

## PMO agent
- **Lens:** portfolio contention, governance/change-control route, RAID. *(Now also carries the contract-variation routing that Legal held — v1 folds "does this need a variation and via what governance gate" into PMO.)*
- **Reasons about:** does this cannibalise another workstream's resource; what governance/change route it must follow; which RAID items move; portfolio-level (not project-level) view.
- **Drives its position on:** portfolio trade-off + the correct governance path. Often the "yes, but via this route" voice.
- **Anuj to encode (P2):** change-control gates, cross-workstream contention adjudication.

## Operations agent
- **Lens:** operational capacity to absorb the work, process impact, licence & 3PP-kit inventory, SLA/run implications. *(Maps to your Operational Excellence dashboard.)*
- **Reasons about:** can the operation actually absorb a pulled-forward or added workload; process/handover impact; licence and kit availability; SLA/service-credit exposure in run.
- **Drives its position on:** the capacity/operational-readiness constraint. The "even if we agree, here's what breaks operationally" voice.
- **Anuj to encode (P2):** capacity model, licence/3PP-kit register logic, the operational health signals you actually watch.

---

## Seed scenarios (the demo rails + first-user on-ramp)
Each seed is chosen because it **forces conflict** — no single agent can answer it.

1. **Supplier milestone variation.** *"A 3rd-party supplier offers to pull a delivery milestone forward 3 weeks for a 15% cost increase and a contract variation."* → Finance: no (CoS/margin). Delivery: yes (critical path de-risked). PMO: depends — portfolio contention + the change-control/variation route. Operations: can we absorb the pulled-forward work — capacity + licence/kit hit. Master reconciles into a defensible call.
2. **Budget overrun.** A workstream is trending 12% over its 3PP budget mid-year — absorb, re-baseline, or cut scope?
3. **Resourcing clash.** Two programmes need the same scarce specialist in the same sprint — who wins, and what's the cost of the loser slipping?
4. **Project PME compliance.** *(Anuj to define PME scope in P2.)* A project is flagged non-compliant against the PME standard — what must change, who owns it, and what's the delivery/cost/operational impact of fixing vs the risk of not.

Each seed ships with a one-line "why this needs several functions" note so a viewer instantly sees the point of the orchestration.

---

## What makes the orchestration *visible* (non-negotiable for the ball)
The trace UI must show, in order and legibly: the master's **routing decision + reasoning** → the specialists working **in parallel** → each **position** side by side → the **disagreement** highlighted → the master's **reconciliation** with the trade-off named. Test: a non-technical business leader watches once and *sees the agents disagree and the master adjudicate.* If it looks like tabs of chatbots, it has failed.
