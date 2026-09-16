# Architecture

How Consilium is built, and why each piece is shaped the way it is. See the [README](../README.md)
for what it does and how to run it; this is for someone evaluating the engineering.

## Orchestration: a bounded LangGraph, hand-rolled

The graph is three logical stages — `route → parallel specialists → reconcile` — built as a plain
LangGraph `StateGraph` (`backend/orchestrator/graph.py`), deliberately **not** the
`langgraph-supervisor` prebuilt package. That package assumes an LLM-driven, tool-calling handoff
loop, which fights a design that needs to be bounded and inspectable rather than open-ended.

```
START → route → { finance | delivery | pmo | operations, whichever are engaged } → reconcile → END
```

**Fan-out is conditional, not fixed.** `route_node` decides which agents to engage; `graph.py`
wires this with `add_conditional_edges`, keyed off `state["routed_agents"]` computed at runtime.
An agent the Chief of Staff didn't engage never runs — LangGraph's fan-in at `reconcile` correctly
waits only for the branches that actually fired, not for the full roster.

**Termination is bounded three independent ways**, so no single mechanism is load-bearing on its
own:
1. **The graph is acyclic.** There is no edge back into `route` or between specialists — a DAG
   cannot loop, by construction.
2. **`recursion_limit`** is passed on every invocation as a hard backstop from LangGraph itself.
3. **An explicit step counter** (`orchestrator/termination.py`) is checked before `reconcile` runs
   and raises if more than one prior step has occurred — independently testable without executing
   the graph at all.

**Shared state** (`orchestrator/state.py`) is a single `TypedDict`. Two fields —
`positions` and `trace` — are `Annotated[list[...], operator.add]`: when several specialist nodes
write in the same parallel step, LangGraph's default merge is "last write wins," which would
silently drop every write but one. The reducer makes each node's contribution additive instead.

## Agents: deterministic signal, narrated voice

Every agent (`backend/agents/{finance,delivery,pmo,operations}.py`) is two things layered
together, and the layering is the point:

- **`evaluate(facts) -> AgentPosition`** is pure, deterministic Python: given a config and a set of
  facts, it computes a `stance` (`yes` / `no` / `conditional` / `blocker`) and the constraint that
  drove it. This is the guardrail and the thing the test suite pins down — no LLM involved, so it's
  fast, reproducible, and it's what `Council`'s live re-test proves is "config, not code."
- **`narrate(facts, position) -> AgentPosition`** asks a model to write that already-decided
  position up in the agent's own voice. It cannot change the stance: `NarrationResult` (the
  structured response type) simply has no `stance` field, so even a model that tries to include
  one has it silently dropped by Pydantic before it ever reaches the position. This is enforced by
  the type system, not by asking nicely.

**Config, not code.** Every agent's thresholds and plain-English rules live in
`backend/agents/configs/*.json`, loaded through a Pydantic model per agent kind
(`backend/agents/registry.py`). `PUT /agents/{id}/config` validates and persists an edit straight
to that file — numeric fields carry `Field(ge=.., le=..)` bounds, and the rules list is capped in
count and length, so a malformed edit is rejected before it's ever written. The rules list isn't
decorative: it's interpolated directly into `narrate()`'s system prompt, so an edited rule
genuinely changes how the agent explains itself on the next run. `backend/agents/manifest.json`
lists which agent instances are active; disabling an entry removes that agent from the graph
entirely with no code change (only registering a genuinely new *kind* of reasoning — not a new
config for an existing one — needs a Python class in `AGENT_KIND_REGISTRY`).

## The Chief of Staff: routing and reconciliation

`backend/orchestrator/chief_of_staff.py` is the orchestrator's LLM-facing half.

**Routing** reads the free-text scenario plus every agent's `lens`, `rules_summary`, and facts
schema, and asks the model to decide who's engaged (with a reason), who's skipped (with a reason),
and — for each engaged agent — to extract the facts it needs from the scenario text. Facts that
don't validate against an agent's schema are dropped rather than crashing the run; pre-supplied
facts (a seed, a test) always win over anything extracted. If the model is unavailable or returns
nothing usable, routing falls back to engaging every configured agent — the honest degraded path,
not a hidden failure.

**Reconciliation** hands the model every position, the detected conflict, and the scenario, and
asks for one defensible recommendation naming the real trade-off. Two integrity mechanisms sit
around that call, both enforced in code rather than merely requested in the prompt:

- **Blocker enforcement is code-authoritative.** Checking whether the model's own recommendation
  text "complies" with the blocker policy is a trap — a keyword scan is defeatable by negation
  (*"do not hold back, approve it"* contains "hold" but is a proceed). So when any agent's stance
  is `blocker`, the decisive recommendation line is written directly by
  `_enforce_blocker_policy`, not inferred from the model's wording; the model's contribution is
  confined to the explanatory `why` and `trade_off`.
- **Abstention over a confident guess.** Before asking the model to reconcile at all,
  `reconcile_node` checks whether *any* routed specialist evaluated on facts that were actually
  extracted from the scenario, as opposed to schema defaults. If none did, the council returns an
  explicit "insufficient grounding" verdict instead of reconciling positions that were never really
  about the user's numbers. A verdict that looks authoritative but quietly ignored the actual input
  is treated as strictly worse than declining to answer.

Both the routing and reconciliation prompts also accept an operator-editable **persona** string
(`GET/PUT /chief-of-staff/config`, `orchestrator/cos_settings.py`) — tone and priority framing
only. It's appended after the mandatory instructions in each prompt and never substituted for
them; the blocker-enforcement code path above runs unconditionally regardless of what the persona
says, which is what keeps "the adjudication policy is not user-settable" true rather than aspirational.

## Model layer

`backend/model/llm.py` is the single seam every LLM call goes through
(`call_structured(system, user, response_model)`). It requests JSON-object mode, falls back to a
bare request if the endpoint doesn't support the parameter, and rescues JSON a model wraps in
prose despite being told not to. Any failure raises `LLMUnavailableError`, which every caller
(routing, narration, reconciliation) catches to fall back to its deterministic path — the model
layer's job is to fail predictably, not to fail loudly.

`ModelConfig` is OpenAI-compatible by design: `provider`/`model_name`/`base_url`/`api_key`, read
from `.env` and overridable at runtime via `Settings`. Hosted providers (OpenAI, Anthropic, Groq,
OpenRouter, ...) get their base URL resolved server-side from a fixed table — a client-supplied
base URL for one of these is ignored, not trusted — and require a key; local/self-hosted keeps
whatever base URL the caller supplies and needs no key. This is why swapping providers is a
one-field change everywhere else in the codebase: nothing downstream of `model/llm.py` knows or
cares which provider is configured.

## The audit ledger

`backend/audit/ledger.py` is an append-only, hash-chained log (`backend/trigger_audit.jsonl`,
outside git — see `.gitignore`). Every entry stores `prev_hash` (the previous entry's hash) and its
own `entry_hash` (a SHA-256 of its own canonicalised contents). Editing, reordering, or deleting
any past entry breaks every hash after it, so `verify_chain()` can independently prove the log is
intact by recomputing the whole chain from scratch — it doesn't trust any stored "verified" flag.

`POST /trigger/webhook` is the real, credential-free inbound this protects: point a mail rule,
Zapier, or `curl` at it, and the caller's own tool owns authentication (an optional shared-secret
header, `X-Consilium-Token`), so Consilium never stores a mailbox credential. Every call is
recorded to the ledger *before* anything else happens — including a rejected one, so the record of
"what tried to convene the council" is complete even for attempts that failed auth.
`frontend/audit.html` is a read-only governance viewer over the same chain: it reads the entries,
recomputes the verification independently, and turns visibly red the instant tampering is detected.

## Persistence

State that needs to survive a restart (model settings, the Chief of Staff persona, run history,
the audit ledger, the user's display name) is written outside the source tree, to a per-user data
directory (`~/.consilium`, overridable via `CONSILIUM_DATA_DIR`; see `backend/appdata.py`). This
is what makes `uvicorn --reload` safe during development: an earlier design that wrote this state
*into* the package directory caused `--reload` to restart the whole process — killing the
in-flight request — every time a setting was saved.

## Frontend

`frontend/index.html` is a single self-contained page (inline CSS/JS, no build step) with five
surfaces — Dashboard, Decision desk, History, Council, Settings — consuming the backend purely
over `fetch`/`EventSource`. The Decision desk opens a Server-Sent Events connection to
`/run/stream` and renders each trace event as it arrives (routing → each position as it's narrated
→ the conflict → the reconciliation), rather than waiting for the whole run to finish before
showing anything. `frontend/audit.html` is the separate governance viewer described above. FastAPI
serves both as static files from the same origin as the API (mounted after every API route, so it
never shadows one), which is why the whole app is one process and one URL.
