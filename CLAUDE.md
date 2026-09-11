# CLAUDE.md — Consilium
*Multi-agent back-office scaffold. Read this first, every session.*

## What this is
A forkable, open-source multi-agent back-office: a master orchestrator (supervisor topology)
routes a back-office decision to specialist agents — Finance, Delivery, PMO, Operations —
lets them reason and DISAGREE, and reconciles their positions into one defensible recommendation.
The orchestration must be VISIBLE to a non-technical business leader. Recommend-only; never acts on real systems.

Full spec in `docs/` — read in this order before building:
1. `docs/00 — Build Brief.md`  (scope, architecture, phases, definition of done — the spine)
2. `docs/01 — Agent Profiles & Orchestration.md`  (master + 4 agents + 4 seeds)
3. `docs/02 — Showcase & Distribution Plan.md`  (what ships around the build)

## Stack (LOCKED)
- Orchestration: **LangGraph** (Python), supervisor pattern. Prebuilt supervisor where it fits.
- Backend: **FastAPI**, async, server-sent events / streaming so agent output reaches the UI live.
- Model layer: **OpenAI-compatible client** — OpenAI / Anthropic / OSS (Kimi, Qwen, Llama) by config only. No hard-coded provider.
- Frontend: **custom, single-page, no framework required** (or minimal). Reuse the Voyij design system — see below.
- Observability: **LangSmith** tracing from day one.
- Config via `.env`; never commit keys. Ship `.env.example`.

## Non-negotiable design rules
- **Bounded termination.** One routing pass → one specialist pass (parallel) → one reconcile. NO open-ended agent-to-agent loops in v1. Guard every graph path against runaway iteration.
- **Recommend-only.** No tool that writes to a real system. Every final output ends with `Assumptions made` and `What this did NOT consider`.
- **Selective routing.** The master may route to a subset of agents and must state why (this reasoning renders in the trace).
- **Clarification step.** If input is too thin to route, the master asks 1–2 questions before dispatch.
- **The trace is a first-class product surface**, not a debug log. Routing reasoning, parallel work, each agent's position, the disagreement, the reconciliation — all rendered legibly.

## UI/UX standard
Reuse the Voyij design system wholesale — tokens (coral #FF5D3A, teal, warm ground #FBF6F0, surface/shadow/radius scales, categorical --c1..c4), fonts (Bricolage Grotesque display / Figtree body / JetBrains Mono data), 3-state theme handling (bare :root light, prefers-color-scheme dark guarded, [data-theme] override). Success = a non-technical exec watches once and SEES the agents disagree and the master adjudicate.

## Engineering standards
Follow Anuj's Eng Standards v1.3 (tests alongside features, typed, small commits, clear module boundaries). Agents live behind a common interface so adding one later is a single file. Keep orchestration, agents, model-layer, and API as separate modules.

## Suggested structure
```
consilium/
  docs/            # the three planning briefs
  backend/
    orchestrator/  # LangGraph graph, supervisor, state, termination
    agents/        # finance.py, delivery.py, pmo.py, operations.py + base.py
    model/         # OpenAI-compatible provider abstraction
    seeds/         # the 4 seed scenarios as data
    api/           # FastAPI app + streaming endpoint
    tests/
  frontend/        # custom trace UI (Voyij design system)
  .env.example
  README.md
```

## Source control (local-first)
- Git from the first commit — local version control needs NO GitHub login. Small, meaningful commits per logical step.
- Push to GitHub only once auth exists: run `gh auth status`. If authenticated, `gh repo create consilium --public --source=. --push`; if not, keep committing locally and tell Anuj to run `gh auth login` once, then push. Never block build progress on the remote.
- `.gitignore` covers `.env`, venv, caches, node_modules, build output.
- Commit message attribution as configured for this account.

## Milestone logging (feeds Anuj's dashboards)
At the end of each phase, append a dated one-line milestone to the Cowork working folder's
`memory/evolution-log.md` (confirm the path with Anuj). This is how build progress flows back to the trackers.

## Phases (stop-points — Arc A protected)
P1 spine (this session) · P2 real agent profiles · P3 trace UI (recordable demo exists here) ·
P4 free-text + clarification + model config + rate-limited deploy · P5 showcase.
Stop cleanly at any phase boundary if asked — P3 already yields a demo.

## Definition of done (v1)
Page published · demo works (seed + free-text) · repo public with fork guide · in 5 named inboxes.
