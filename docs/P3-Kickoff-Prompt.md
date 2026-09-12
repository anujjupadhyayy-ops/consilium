# P3 Kickoff Prompt — paste into Claude Code (fresh session, in the repo)

Read CLAUDE.md, docs/00 — Build Brief.md, docs/P2-Agent-Logic-Spec.md, and docs/DESIGN-TOKENS.md before writing.

This is P3 — the ORCHESTRATION-TRACE UI (the hero). Success test: a NON-TECHNICAL business leader
watches ONE run and clearly sees the agents disagree and the master adjudicate. This phase produces
the recordable demo. Reuse the Voyij design system in docs/DESIGN-TOKENS.md.

Do, in order:
1. Backend — streaming: add a FastAPI endpoint that runs a scenario through the existing graph and
   emits the trace events (route, dispatch, position, conflict, reconciliation) PROGRESSIVELY via
   Server-Sent Events. Reuse the P1/P2 trace schema; do not change agent logic.
2. Frontend — one self-contained page (vanilla JS or minimal; inline CSS/JS; Voyij tokens + the three
   fonts + 3-state theme). It consumes the SSE stream and renders progressively.
3. The screen, in order:
   - Input: the four seed buttons (supplier / budget-overrun / resourcing / Project-PME). A visible
     but disabled "free-text — coming in v1" box (free-text is P4).
   - Run view, rendered as events arrive:
     a. Master's ROUTING decision + reasoning (which agents, and why — including any it skipped).
     b. The chosen specialists working IN PARALLEL (a visible working/pending state per agent).
     c. Each POSITION as a card: stance chip (yes/no/conditional/blocker, semantic colours per
        DESIGN-TOKENS), the lead figure (mono), reasoning, and the driving constraint.
     d. The CONFLICT made a visual focal point (the disagreeing stances highlighted against each other).
     e. The master's RECONCILIATION: recommendation (display font), the trade-off naming BOTH sides'
        real constraints, the operational-blocker-wins policy stated as a policy, and assumptions +
        what-it-did-not-consider.
4. Legibility is the acceptance bar: disagreement and adjudication are the visual focus, not a debug
   log. If it reads like tabs of chatbots, it fails.
5. Responsive (stacks ~400px), both themes, legible at rest (no content hidden behind scroll/animation).
   Respect prefers-reduced-motion.
6. LangSmith stays optional. Small commits; push if `gh auth status` is authed. Append a dated P3
   milestone to the Working Folder's memory/evolution-log.md.

Stop when a seed runs end-to-end in the browser with a legible, on-brand streaming trace — that is the
recordable demo. Capture screenshots of the disagreement and the reconciliation. Summarise what P4
(free-text + clarification + editable-agents UI + deploy) needs.
