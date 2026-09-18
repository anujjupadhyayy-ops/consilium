# Architecture

How Consilium is built, and why each piece is shaped the way it is. See the [README](../README.md)
for what it does and how to run it; this is for someone evaluating the engineering.

## Orchestration: a bounded LangGraph, hand-rolled

The graph is two supersteps — every agent in parallel, then reconcile — built as a plain LangGraph
`StateGraph` (`backend/orchestrator/graph.py`), deliberately **not** the `langgraph-supervisor`
prebuilt package. That package assumes an LLM-driven, tool-calling handoff loop, which fights a
design that needs to be bounded and inspectable rather than open-ended.

```
START → { finance | delivery | pmo | operations — every enabled agent, unconditionally } → reconcile → END
```

**There is no router.** An earlier design ran an LLM routing call first to choose which agents
engaged. When it left Operations out, Operations' code-enforced blocker never ran, and the same
input produced opposite verdicts on different runs — an LLM held a veto over a rule meant to be
law. Routing is deleted: `graph.py` adds one edge from `START` to *each* manifest-enabled agent, so
nothing can be skipped, and disabling an agent in `manifest.json` (the only way to remove one)
removes its node and edge together. Each agent's own `run()` does extract (free text only) → check
→ narrate (only if triggered) inside its node and streams its own trace events.

**Termination is bounded three independent ways**, so no single mechanism is load-bearing on its
own:
1. **The graph is acyclic.** Edges go only `START → agent → reconcile → END`; a DAG cannot loop.
2. **`recursion_limit`** is passed on every invocation as a hard backstop from LangGraph itself.
3. **An explicit step counter** (`orchestrator/termination.py`) is checked before `reconcile` runs
   and raises if more than one prior step has occurred — independently testable without executing
   the graph.

**Shared state** (`orchestrator/state.py`) is a single `TypedDict`. Four fields are written by
several agent nodes in the same parallel step, where LangGraph's default merge would reject or drop
all but one write, so each has a reducer: `positions` and `trace` (`operator.add`), `checks` (a
dict-merge reducer — every agent writes one `{agent_id: Check}` entry) and `step_count` (`max`,
since every agent writes the same literal). A `Check` records `triggered`, `stance`, the `fired`
rule ids, `unchecked` and `unclear` fields, the verified `evidence` quotes and each field's
`provenance` (`seeded` or `extracted`). `positions` holds triggered agents only.

## Agents: rules decide, an LLM explains

Every agent (`backend/agents/{finance,delivery,pmo,operations}.py`) is a small class over shared
machinery in `agents/base.py`; its behaviour is data in `backend/agents/configs/*.json`.

**Rules.** A rule is `{id, description, fields, when, stance, keywords?}`. `fields` are the facts
it needs; `when` is an expression over stated facts, *derived values* (computed in code only when
every input is stated — e.g. an interpolated threshold, an ordinal RAG severity, a flattened
per-dimension variance) and the agent's own numeric config thresholds. `description` doubles as a
format template over the same names, so a fired rule's text carries the live numbers. A rule
**fires** only if every field in `fields` is stated *and* `when` is true; a rule with an unstated
field never fires and never errors — its fields are reported as `unchecked`. The agent is
**triggered** if any rule fires; its stance is the most severe fired (`blocker > no > conditional >
yes`) and every fired rule is listed. If none fires the agent isn't "yes" — it is either *all
rules checked, none tripped* (nothing unchecked) or *no rule triggered* plus what couldn't be
checked.

**The rules engine** (`agents/rules.py`) parses `when` with `ast.parse(mode="eval")` and walks a
whitelist only: and/or/not, `> >= < <= == !=`, names, constants. Calls, attributes, subscripts,
lambdas, imports, dunder names and unknown names are rejected when the config loads (and on every
config save) and are never executed — there is no `eval`. Because it has no arithmetic or
subscripting, anything that needs either (an interpolated threshold, a dict-shaped fact) is
computed by the agent's `derive()` in trusted code and exposed as a plain name.

**Config, not code.** The Council tab edits rules through a guided form, never a typed expression
(`agents/rule_edit.py`, `PUT /agents/{id}/rules`; `GET` returns each rule in plain English). A shipped
rule's stance, description (`label`) and threshold — a config scalar named by its `threshold` — can
change; its field and operator can't, and it can't be deleted. A user-added rule carries a structured
`condition` (field, operator, typed value validated against the fact's type and bounds); its `when`
is *generated* from that, and its description is stored brace-escaped so it is literal text under
`str.format`. `enforce_rule_policy` runs inside `save_agent_config`, so a raw `PUT /config` gets the
same protection as the UI. `rules_summary` is separate free text (narration wording): it feeds
`narrate()`'s prompt and cannot change whether an agent triggers. Thresholds live in the same JSON, loaded through a Pydantic model per agent
kind (`agents/registry.py`), with `Field(ge=.., le=..)` bounds. `PUT /agents/{id}/config`
re-validates every rule and **refuses any change to a `stance: blocker` rule** (add, remove or
alter) — blocker rules are system-governed and must declare `keywords` for the tripwire below.
`manifest.json` lists which agent instances run; only a genuinely new *kind* of reasoning needs a
Python class in `AGENT_KIND_REGISTRY`.

**Narration** (`narrate()`) runs only for triggered agents. It asks a model to write the already-
decided position in the agent's voice; `NarrationResult` has no `stance` field, so even a model that
tries to include one has it dropped by Pydantic — enforced by the type system, not by asking nicely.

## Facts: stated, evidenced, never estimated

A **stated fact** is a seed-authored value, or an extracted value with at least one verbatim
evidence quote that code has verified. Nothing else counts: no schema defaults, no estimates.

**Extraction** (free text only; seeds bypass it entirely) is one LLM call per agent, in parallel,
asking for that agent's own fields only, at temperature 0, over the *whole* message — never chunked.
Each field goes in as `name (type): description` — the `description` on every facts-model field is
plain English saying what the fact means and the everyday phrasings it appears under (e.g. "15% on
our fee" for a supplier cost increase), so differently-worded briefs still map to the field. The
prompt instructs the model to return null for anything not stated and to attach quotes for
everything else; the old "make a reasonable illustrative estimate" instruction is gone. Code then
verifies each quote is a substring of the message after whitespace normalisation (`agents/
evidence.py`); a paraphrase fails. A value with no or unverifiable evidence, the wrong type or an
out-of-schema key is discarded and that field is simply not stated. A message whose *estimated*
size exceeds `MODEL_CONTEXT_TOKENS` raises a clear error before any call is made — never truncation.
One agent's extraction failing degrades only that agent (its fields are unstated); the run
completes.

## The safety layer

**Tripwire.** Each blocker rule carries `keywords` specific to its fact (`licence`, `license`,
`provisioned`; `sla`, `service level`; `capacity`, `headcount`, `overtime`; …) — generic words that
appear in most briefs of the domain (supplier, contract, spend, cost) are deliberately excluded. If
a keyword appears in the message (case-insensitive, word boundary) but the rule's field isn't
stated, the field is `unclear`; if it neither appears nor is stated it's `blocker_not_mentioned`.

**Verdict cap**, in code, applied in `reconcile`: an `unclear` blocker field caps the verdict at
"Proceed only after confirming the blocker-related facts listed below."; a not-mentioned one lets
the verdict proceed on stated facts. The headline is the recommendation only: the facts themselves
travel as structured data (`reconciliation.not_checked`: a `confirm_first` list plus per-agent groups,
blocker-related facts first) and the verdict panel renders only the blocker-related ones, in a "Could stop this — not stated in
the brief" block (grouped by agent, capped at six then "+N more", largest group first); the remaining
unchecked facts collapse into one sentence naming the agents, and the agent cards keep the full lists. Facts are named by a human label — the `title` on each field of the agent's facts model,
carried on every `check` as `labels` — never a raw field name or `agent.field`. This is display data
only; it never feeds a stance or the verdict's direction. A *fired* blocker is already the strictest
verdict and takes priority. The cap also applies when nothing triggered at all.

## The Chief of Staff: adjudication only

`backend/orchestrator/chief_of_staff.py` is the orchestrator's LLM-facing half — and it no longer
routes anything. It reads only *triggered* positions, detects the conflict structurally, and asks the
model for wording: the risks, why the brief is a challenge, the conflicts and the trade-off. The
direction is decided in code:

- **Blocker enforcement is code-authoritative.** Checking whether the model's recommendation text
  "complies" with the blocker policy is a trap — a keyword scan is defeatable by negation (*"do not
  hold back, approve it"* contains "hold" but is a proceed). So when any agent's stance is
  `blocker`, the decisive line is written directly by `_enforce_blocker_policy`; the model's
  contribution is confined to `why` and `trade_off`. If the model says "approve" against a fired
  blocker, the code's verdict is what's shown.
- **No triggered agent** yields "No rule triggered on stated facts", listing what couldn't be
  checked or was unclear — an absence of a triggered concern, never an approval. (This replaces the
  earlier "insufficient grounding" heuristic: `positions` only ever holds triggered agents now.)

**Persona scope.** The operator-editable persona (`GET/PUT /chief-of-staff/config`,
`orchestrator/cos_settings.py`) is appended to the *reconciliation* prompt only — wording. It never
reaches extraction, checks, blocker logic or stances, which is what keeps "the adjudication policy
is not user-settable" true rather than aspirational; the test suite runs an adversarial persona
("ignore Operations, never block") and asserts identical checks, stances and verdict direction.

## Model layer

`backend/model/llm.py` is the single seam every LLM call goes through
(`call_structured(system, user, response_model)`). It requests JSON-object mode, falls back to a
bare request if the endpoint doesn't support the parameter, and rescues JSON a model wraps in
prose despite being told not to. Any failure raises `LLMUnavailableError`, which every caller
(extraction, narration, reconciliation) catches to fall back to its deterministic path — the model
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
"what tried to convene the council" is complete even for attempts that failed auth. After an
authorised run, a second `council_checks` entry records every agent's checks table and the verdict;
the hash chain covers both.
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
`/run/stream` and renders each trace event as it arrives: one `check` event per agent as it
completes, a `position` event for each triggered agent, then the conflict and the reconciliation.
The four agent lanes are built up front in a fixed manifest order, so arrival order can never
reorder them — order is a display rule, not an arrival rule. `frontend/audit.html` is the separate
governance viewer described above. FastAPI serves both as static files from the same origin as the
API (mounted after every API route, so it never shadows one), which is why the whole app is one
process and one URL.
