# P2 Kickoff Prompt — paste into Claude Code (fresh session, in the repo)

Read CLAUDE.md, docs/00 — Build Brief.md, and docs/P2-Agent-Logic-Spec.md in full before writing.

This is P2 — replace the P1 stub agents with their REAL logic from the spec. Still no UI, no deploy.

Core architectural rule (from the spec): store each agent's rules/instructions/thresholds as
EDITABLE, SERIALIZABLE CONFIG (a data/policy object or editable prompt loaded at runtime) —
never hardcoded in Python. A future UI must be able to change an agent's rules and add/remove
agents without code changes. Design for that now; do NOT build the UI (that's P4).

Do, in order:
1. Define an agent-config schema (lens, rules/thresholds, stance logic, lead-figure) that is
   serializable (JSON/YAML or equivalent) and loaded at startup. Ship the four spec agents as
   the default config set. Values are illustrative defaults, clearly marked user-overridable.
2. Implement each agent to evaluate its config against the input and return a structured position:
   stance (yes | no | conditional | blocker), reasoning, driving_constraint, lead_figure — per
   docs/P2-Agent-Logic-Spec.md. Specifically:
   - Finance: >5pt project-margin erosion OR >7% supplier-cost = no; time-phased 3PP forecast flag
     (full-year forecast >= threshold weighted by month-elapsed); qualitative CoD sub-lens.
   - Delivery: EVM (SPI/CPI/EAC); effective RAG (unresourced can't be green); criticality != health;
     Critical Revenue at Risk as the deciding lens.
   - PMO: PRINCE2/MSP tolerances + gate/change-control routing; conditional "proceed via gate" as
     the common voice; carries contract-variation routing.
   - Operations: four signals (capacity/3PP-spend/savings/supplier-SLA); WEAKEST-of-four verdict;
     hard blocker when licence/kit/SLA not in place.
3. Update the reconcile engine to consume the structured stances (detect conflict on stance,
   build the trade-off from real driving_constraints, apply the disclosed operational-blocker-wins
   policy, always populate assumptions + not_considered).
4. Keep the supplier-milestone seed running end-to-end; positions now come from real config, not stubs.
5. Tests: each agent's config produces the right stance on the seed + edge cases (margin trip,
   forecast-early-vs-late, unresourced downgrade, weakest-of-four, tolerance breach); reconcile
   surfaces the conflict and applies the blocker policy; a config-swap test proves rules are data
   (load a modified config, get a different stance) — regression guard for editability.
6. LangSmith stays optional (skip if no key). Small commits; push if `gh auth status` is authed.
   Append a dated P2 milestone to the Working Folder's memory/evolution-log.md.

Stop when the seed runs through real config-driven agents with a legible trace and green tests;
summarise what's built and what P3 (the trace UI) and P4 (the edit-agent UI) will need.
