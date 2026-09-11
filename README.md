# Consilium

A forkable, open-source multi-agent back-office scaffold: a **master orchestrator** routes any
back-office decision to specialist function agents (Finance, Delivery, PMO, Operations), lets
them reason and **disagree**, and reconciles their positions into a defensible recommendation —
with the orchestration **visible on screen**.

Full design in [`docs/`](docs/): the [Build Brief](docs/00%20—%20Build%20Brief.md), [Agent
Profiles & Orchestration](docs/01%20—%20Agent%20Profiles%20&%20Orchestration.md), and the
[Showcase & Distribution Plan](docs/02%20—%20Showcase%20&%20Distribution%20Plan.md).

## Status: P1 — orchestration spine

This is **P1**: the mechanism proven end-to-end in the terminal, on one seed scenario, with no UI
and no real per-agent domain logic yet (that's P2). No feature beyond what P1 needs has been
built — see [`CLAUDE.md`](CLAUDE.md) for the full phase list (P1 → P5).

**What P1 proves:**
- A LangGraph supervisor topology: `route → 4 parallel specialists → reconcile`, hand-rolled with
  a plain `StateGraph` rather than the `langgraph-supervisor` prebuilt package (that package
  assumes an LLM-driven, tool-calling handoff loop, which fights a bounded, deterministic,
  single-pass design).
- **Bounded termination**, three independently-tested ways: the graph is an acyclic DAG (no edge
  loops back to `route` or between specialists), a tight `recursion_limit` is enforced by
  LangGraph itself, and an explicit `step_count` guard is checked before reconciliation runs.
- Four **stub** agents — hard-coded, not LLM-generated — each returning a realistic position
  (recommendation + reasoning + the one driving number/constraint) for the "supplier milestone
  variation" seed, engineered so real conflict exists to reconcile.
- A **rule-based reconciliation** step that detects conflicting stances structurally, names the
  trade-off using each side's actual constraint text, and applies one disclosed P1 policy (a hard
  operational blocker wins by default) — stated as a policy, not a hidden judgement call.
- A structured **trace event schema**, designed so a future P3 streaming UI can render
  progressively from the trace log alone.
- A **model-layer abstraction** (OpenAI-compatible client, config from env) — built and tested,
  but never called at runtime in P1. P1's routing and agent positions are deterministic; P2 is
  where real domain logic (and, if warranted, live model calls) lands.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env   # optional in P1 -- only LangSmith tracing reads it at runtime
```

## Run the seed

```bash
cd backend
python cli.py
```

Prints the full trace: routing reasoning → all 4 specialist positions → the disagreement →
the reconciliation with the trade-off named → assumptions and what it did not consider.

## Run the tests

```bash
cd backend
pytest
```

## Fork it

This is a scaffold, not a finished product. Fork it, wire in your own model endpoint via
`.env` (`MODEL_PROVIDER` / `MODEL_NAME` / `BASE_URL` / `API_KEY` — any OpenAI-compatible
endpoint works, including self-hosted OSS models), and replace `position_for()` in each
`backend/agents/*.py` with your own domain logic. `backend/agents/base.py`'s `StubAgent`
interface is the seam designed for exactly this.

## Licence

MIT — see [LICENSE](LICENSE).
