# Consilium

A forkable, open-source multi-agent back-office scaffold: a **master orchestrator** routes any
back-office decision to specialist function agents (Finance, Delivery, PMO, Operations), lets
them reason and **disagree**, and reconciles their positions into a defensible recommendation —
with the orchestration **visible on screen**.

Full design in [`docs/`](docs/): the [Build Brief](docs/00%20—%20Build%20Brief.md), [Agent
Profiles & Orchestration](docs/01%20—%20Agent%20Profiles%20&%20Orchestration.md), the
[Showcase & Distribution Plan](docs/02%20—%20Showcase%20&%20Distribution%20Plan.md), and the
[P2 Agent Logic Spec](docs/P2-Agent-Logic-Spec.md).

## Status: P2 — real, config-driven agent logic

The mechanism (P1) and the reasoning behind each agent's position (P2) are both proven
end-to-end in the terminal, on one seed scenario, with no UI yet (that's P3). No feature beyond
what P2 needs has been built — see [`CLAUDE.md`](CLAUDE.md) for the full phase list (P1 → P5).

**Consilium is a domain-agnostic decision framework**, not a finance/back-office product — see
the Build Brief's "Product position (Path A)". The four example agents below are the flagship
demo (Anuj's domain), shipped as **illustrative, user-overridable config**, not proprietary or
hardcoded rules. Depth is shown by how much complexity the framework can carry, not by whose
thresholds these are.

**What P1 proved (the mechanism):**
- A LangGraph supervisor topology: `route → N parallel specialists → reconcile`, hand-rolled with
  a plain `StateGraph` rather than the `langgraph-supervisor` prebuilt package (that package
  assumes an LLM-driven, tool-calling handoff loop, which fights a bounded, deterministic,
  single-pass design).
- **Bounded termination**, three independently-tested ways: the graph is an acyclic DAG (no edge
  loops back to `route` or between specialists), a tight `recursion_limit` is enforced by
  LangGraph itself, and an explicit `step_count` guard is checked before reconciliation runs.
- A structured **trace event schema**, designed so a future P3 streaming UI can render
  progressively from the trace log alone.

**What P2 adds (the reasoning):**
- **Every agent's rules/thresholds live in editable, serializable config**
  (`backend/agents/configs/*.json`), validated at load time by a Pydantic schema per agent kind
  (`backend/agents/{finance,delivery,pmo,operations}.py`) — never a Python literal in an
  evaluator. A future edit-agent UI (P4) reads and writes these files directly.
- **`backend/agents/manifest.json`** lists which agent instances are active and which config
  file backs each — the add/remove-agents-without-code seam. Disable or delete an entry to
  remove an agent from the roster with zero code changes (`tests/test_registry.py` proves this
  end-to-end, including a test that edits a config file on disk and gets a different stance for
  the same facts). Adding a genuinely new *kind* of reasoning still needs a Python evaluator
  registered in `agents/registry.py`'s `AGENT_KIND_REGISTRY` — that boundary is inherent to
  encoding new procedural logic from data alone, not something P2 tries to paper over.
- **Four real evaluators**, each an industry-standard spine with illustrative, editable values:
  Finance (margin-erosion and supplier-cost no-lines, a time-phased 3PP forecast flag weighted
  by month-elapsed in the FY, a qualitative cost-of-delay sub-lens), Delivery (EVM baseline —
  SPI/CPI/EAC — plus "effective RAG" that floors at amber for unresourced work and a Critical
  Revenue at Risk headline lens), PMO (PRINCE2/MSP tolerance breaches across six dimensions,
  contract-variation gate routing, a hard-reject threshold beyond ordinary change control), and
  Operations (four operational signals reduced to a **weakest-of-four** verdict, never an
  average — any red signal is a `blocker` regardless of the other three).
- A fourth stance, **`blocker`**, generalises P1's operations-specific hack: the reconcile engine
  now treats a `blocker` from *any* agent as decisive, independent of the cost/schedule
  trade-off — a disclosed policy, not a hidden judgement call.
- Every agent still runs with **zero live model calls** — routing and evaluation are
  deterministic rule/config evaluation, not LLM inference (verified by a test that makes the
  model client raise if anything on the seed's path ever calls it). The model-layer abstraction
  from P1 stays built and ready, unused until P4/beyond decides an agent needs it.

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

This is a scaffold, not a finished product. Two ways to make it yours:

- **Change the rules, not the code.** Edit `backend/agents/configs/*.json` — thresholds, gate
  names, lens descriptions — and disable/add entries in `backend/agents/manifest.json` to change
  which agents run. No Python changes needed for this.
- **Change the reasoning.** Replace `evaluate()` in any `backend/agents/*.py` with your own
  domain logic (and its matching `*Config`/`*Facts` Pydantic models), or add a wholly new agent
  kind and register it in `backend/agents/registry.py`'s `AGENT_KIND_REGISTRY`.

Wire in your own model endpoint via `.env` (`MODEL_PROVIDER` / `MODEL_NAME` / `BASE_URL` /
`API_KEY` — any OpenAI-compatible endpoint works, including self-hosted OSS models) if your
agent logic needs one; Consilium's own example agents don't.

## Licence

MIT — see [LICENSE](LICENSE).
