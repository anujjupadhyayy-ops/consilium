# Consilium

A forkable, open-source multi-agent back-office scaffold: a **master orchestrator** routes any
back-office decision to specialist function agents (Finance, Delivery, PMO, Operations), lets
them reason and **disagree**, and reconciles their positions into a defensible recommendation —
with the orchestration **visible on screen**.

Full design in [`docs/`](docs/): the [Build Brief](docs/00%20—%20Build%20Brief.md), [Agent
Profiles & Orchestration](docs/01%20—%20Agent%20Profiles%20&%20Orchestration.md), the
[Showcase & Distribution Plan](docs/02%20—%20Showcase%20&%20Distribution%20Plan.md), and the
[P2 Agent Logic Spec](docs/P2-Agent-Logic-Spec.md).

## Status: P3.5 — the council genuinely reasons, live, in the browser

Type a free-text back-office dilemma into the Decision desk, hit Convene, and watch it happen for
real: the **Chief of Staff** (an LLM call) decides who's relevant and who to skip, the engaged
specialists reason in parallel over their own computed hard signal (also an LLM call, in each
agent's voice), a genuine conflict surfaces, and the Chief of Staff (LLM again) adjudicates —
naming the real trade-off, applying the disclosed operational-blocker-wins policy. Every LLM step
has a deterministic fallback if the model is unreachable, so a flaky local model degrades a run
rather than crashing it. See [`CLAUDE.md`](CLAUDE.md) for the full phase list (P1 → P5).

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
**What P3 added (the trace UI):** a FastAPI SSE endpoint streaming the trace schema progressively,
and a first single-page trace viewer. **P3.5 replaced that viewer** with a locked, five-surface
UI (Dashboard, Decision desk, History, Council, Settings) and made every LLM step genuine:

- **`model/llm.py`** is the one seam every model call goes through (`call_structured`) — JSON-object
  mode with a bare-request fallback (verified against a local Ollama endpoint), a rescue for JSON a
  model wraps in prose, and `LLMUnavailableError` on any failure so callers degrade gracefully.
- **Agents narrate, they don't decide.** `evaluate()` is still the deterministic hard-signal
  computation (the guardrail, and the test target); a new `narrate()` step asks the model to write
  that position up in the agent's voice, constrained so it *cannot* change the stance —
  `NarrationResult` has no stance field, so pydantic drops one even if a model tries to include it
  (tested directly with an adversarial mock).
- **Routing is a real, selective LLM decision.** The Chief of Staff reads free text, decides which
  agents are relevant with a reason each, explicitly skips the rest, and extracts the facts an
  engaged agent needs where none were pre-supplied. `graph.py`'s fan-out is `add_conditional_edges`
  reading that decision at runtime — an unusable/unavailable model falls back to engaging everyone
  (the old P1/P2 behaviour, now the deliberate degraded path, not the only path).
- **Reconciliation is genuine deliberation, with an enforced floor.** The Chief of Staff weighs the
  actual positions and writes the verdict; a cheap, disclosed guardrail
  (`_enforce_blocker_policy`) checks the model's own text for decline/hold language whenever a
  `blocker` is present and overrides it with a guaranteed-compliant recommendation if the model
  didn't comply — a policy that holds regardless of the model's cooperation, not just its prompt.
- **The full pipeline runs on one real backend for both seeds and free text** —
  `/run/stream?text=...` (or `?seed_id=...`) — plus `/council/retest` (live rule-swap proof, no
  LLM), `/settings/model` (persists + real-tests a model connection), and
  `/trigger/inbound-email` (keyword-matches a simulated email against each agent's own
  `trigger_keywords`, then convenes the same real pipeline).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env   # MODEL_PROVIDER/MODEL_NAME/BASE_URL/API_KEY -- any OpenAI-compatible
                        # endpoint, including a local Ollama server (see .env.example)
```

## Run it

```bash
cd backend
uvicorn api.app:app --reload
```

Open `http://localhost:8000` — the FastAPI app serves the frontend and the API from the same
origin. No model reachable? Every run still completes via the deterministic fallback path.

`python cli.py` still runs the supplier-milestone seed straight through the same graph and prints
the full trace to the terminal — useful for a quick check without the browser.

## Run the tests

```bash
cd backend
pytest
```

Every LLM call is mocked by default (`conftest.py`) — the suite needs no reachable model and runs
in well under a second. Specific tests override the mock to verify genuine LLM-driven behaviour
(a subset selected, the blocker policy enforced against a misbehaving model, ...).

## Fork it

This is a scaffold, not a finished product. Three ways to make it yours:

- **Change the rules, not the code.** Edit `backend/agents/configs/*.json` — thresholds, gate
  names, lens descriptions — and disable/add entries in `backend/agents/manifest.json` to change
  which agents run. No Python changes needed for this (the Council tab does this live, for the
  supplier-milestone scenario, via `/council/retest`).
- **Change the reasoning.** Replace `evaluate()` in any `backend/agents/*.py` with your own domain
  logic (and its matching `*Config`/`*Facts` Pydantic models), or add a wholly new agent kind and
  register it in `backend/agents/registry.py`'s `AGENT_KIND_REGISTRY`. Adding a genuinely new
  *kind* of reasoning always needs this step — a JSON file alone can parameterise existing logic,
  not invent new procedural reasoning.
- **Change the model.** Any OpenAI-compatible endpoint works via `.env` or the Settings tab —
  OpenAI, Anthropic-via-gateway, OpenRouter, or a self-hosted OSS model (this repo was built and
  verified against a local Ollama server running `llama3.2`).

## Licence

MIT — see [LICENSE](LICENSE).
