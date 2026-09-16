# Consilium

Consilium is a forkable, open-source multi-agent decision framework: a **Chief of Staff**
orchestrator routes a free-text decision to specialist agents, lets them reason independently and
**disagree**, then reconciles their positions into one defensible recommendation — with the whole
process visible on screen, step by step. It ships with a back-office example (Finance, Delivery,
PMO, Operations) because that's a domain most people can sanity-check, but the framework itself is
domain-agnostic: the agents are editable config, not hardcoded logic.

![Dashboard: the Chief of Staff's morning briefing, flagged items needing a decision, and the council's latest signals from Finance, Delivery, PMO and Operations](docs/images/dashboard.png)

*The Dashboard — a Chief of Staff briefing, what's flagged for you, and each specialist's latest
signal at a glance.*

## The problem

A single chatbot asked "should we do this?" collapses cost, schedule, governance, and operational
reality into one undifferentiated answer. Real back-office decisions aren't like that — the
Finance view and the Delivery view can legitimately conflict, and the interesting part is *how*
that conflict gets resolved, not just the final word. Consilium makes that resolution process the
product: you watch the specialists disagree, and you watch a defined policy — not a vibe — decide
what wins.

## How it works

1. **Route.** The Chief of Staff reads the decision and picks which specialist agents are
   relevant, stating a reason for each — and explicitly states why it skipped the rest. Selective
   routing is itself a sign of judgement; it never dispatches to an agent that has nothing to add.
2. **Deliberate, in parallel.** Each engaged agent computes a deterministic **hard signal** —
   stance (`yes` / `no` / `conditional` / `blocker`) plus the one number or constraint driving it —
   from its own editable config. An LLM call then writes that position up in the agent's voice, but
   cannot change the stance: the narration model has no field to put one in.
3. **Reconcile.** The Chief of Staff weighs the positions and writes a verdict naming the real
   trade-off between them. One policy is non-negotiable: a `blocker` from *any* agent overrides a
   cost/schedule trade-off, full stop — see below for how that's enforced, not just prompted.

![The Chief of Staff card: routing, reconcile policy and guardrails, plus the Blocker/Conflict/Conditional glossary shown to the user](docs/images/council-glossary.png)

*The policy in plain English, not just in code — Blocker, Conflict and Conditional defined the way
the verdict actually uses them.*

**Recommend-only, always.** Nothing Consilium produces writes to a real system. Every verdict ends
with what was assumed and what wasn't considered, and the framework never claims more certainty
than its inputs support.

**Deterministic fallback, always.** Every LLM call — routing, narration, reconciliation — has a
non-LLM fallback path. No model reachable? Routing engages every configured agent instead of
guessing who to skip, and reconciliation falls back to rule-based logic over the same structured
positions. A run never crashes because a model is down; it degrades to a known, tested behaviour
instead, and the UI's **Fallback mode** indicator makes that state visible rather than silent.

## The standout engineering

- **Code-authoritative blocker enforcement.** When any agent raises a `blocker`, the final
  recommendation line is written by policy in code, not inferred from the model's phrasing. A
  keyword check on the model's own text would be defeatable by negation (*"do not hold back —
  approve"* contains the word "hold" but ships an approval); reconciliation avoids that trap
  entirely by authoring the verdict itself whenever a blocker is present, and confining the model's
  contribution to the *why* and the *trade-off*.
- **Abstention over fabrication.** If not one routed specialist evaluated on facts actually
  extracted from the scenario — a weak model, or genuinely ambiguous input — the council **abstains**
  ("insufficient grounding") rather than present a confident-looking verdict built on schema
  defaults. Looking authoritative while quietly ignoring the user's actual numbers is treated as a
  worse failure than saying "I don't have enough to go on."
- **A tamper-evident audit ledger on the inbound trigger.** `POST /trigger/webhook` is a real,
  credential-free way to convene the council from an external event (a mail rule, Zapier, `curl`).
  Every call — including a rejected one — is appended to a hash-chained, append-only ledger before
  anything else happens: each entry stores the hash of the previous entry, so editing or deleting
  any past line breaks every hash after it. `/audit.html` is a governance viewer over the same
  chain — it recomputes the chain independently and flips visibly red the moment it's been altered.
- **Agents are edited, not redeployed.** Every agent's plain-English rules and numeric thresholds
  live in versioned JSON config, not Python literals. The Council UI edits them live —
  `PUT /agents/{id}/config` validates and persists to that file, and the very next run reasons with
  the change. Numeric limits stay hard, code-enforced signals; the plain-English rules are what
  feed the LLM's narration prompt, so a rule you add genuinely changes how an agent explains
  itself.

## Prerequisites

- **Python 3.10+.**
- **A model — optional.** Consilium is model-optional: with no model reachable it runs every
  decision through its deterministic fallback path, with a **Fallback mode** indicator so that
  state reads as intentional rather than broken. For genuine multi-agent reasoning, point it at any
  OpenAI-compatible endpoint. The simplest local option is [Ollama](https://ollama.com):

  ```bash
  # one-time, in a separate terminal — you run and own this, the app never starts it for you
  ollama serve                 # or launch the Ollama app (keeps the server alive in the menubar)
  ollama pull llama3.2
  ```

  The app deliberately does not start or manage Ollama. Your model server is yours to run;
  Consilium only *connects* to it — start it before or after launching, and Consilium picks it up
  on the next Save/refresh, no restart required.

### Providers & models

Consilium speaks the OpenAI HTTP shape, so any compatible endpoint drops in from **Settings →
Language model** — pick a provider and a sensible default model and base URL fill in automatically
(hosted providers require a key; the base URL is resolved server-side, not trusted from the client):

| Provider | Cost | Default model | Notes |
|---|---|---|---|
| **Groq** | free tier | `openai/gpt-oss-120b` | fast, strong reasoning; a good default for trying this out. Key: console.groq.com. |
| **Anthropic** | paid API credits | a current Claude Sonnet id | most reliable of the hosted options. Key: console.anthropic.com. |
| **OpenAI** | paid | `gpt-4o-mini` | cheap and reliable. |
| **Local (Ollama)** | free | `llama3.2` | fine for wiring checks; a 3B model is often too small for accurate free-text fact extraction. |

**Model quality drives free-text accuracy.** Reading the figures a decision turns on is only as
good as the model doing the reading — a small local model often can't, and Consilium abstains
rather than guess (see above). Seeds carry explicit facts and produce grounded verdicts on any
model, including the deterministic fallback.

## Setup & run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env   # MODEL_PROVIDER/MODEL_NAME/BASE_URL/API_KEY -- any OpenAI-compatible
                        # endpoint, including a local Ollama server (see .env.example)
```

One command handles all of the above plus Ollama detection and opening the app:

```bash
./start.sh
```

Or run it directly:

```bash
source .venv/bin/activate
uvicorn api.app:app --app-dir backend
```

Open the URL it prints (default `http://localhost:8000`) — the FastAPI app serves both the
frontend and the API from the same origin.

### AI-assisted launch

Don't want to run the commands above yourself? Point an AI coding assistant (Claude Code, Cursor,
etc.) at this repo and ask it to get Consilium running — for example:

> "Clone this repo, set up a Python virtual environment, install `backend/requirements.txt`, copy
> `.env.example` to `.env`, and run `./start.sh` so I can try it in my browser."

The whole point of `start.sh` and the deterministic fallback (no model required, see below) is that
this works with zero manual setup decisions — the assistant can have it running in one pass, and
you can try both a seed scenario and your own free-text decision immediately.

> **Don't add `--reload` for normal use.** The app persists its own state (model config, the
> Chief-of-Staff persona, the audit ledger) to a per-user data directory *outside* the source tree
> (`~/.consilium`, override with `CONSILIUM_DATA_DIR`), specifically so `--reload` is safe if you
> want it for development — but it isn't needed for normal use, and an earlier design that wrote
> settings *into* the source tree would reload the whole process (and drop the in-flight request)
> on every save.

## How to use it

- **Seed scenarios** on the Decision desk are one-click, pre-written dilemmas with engineered
  facts — the fastest way to see a genuine disagreement and a blocker-overrides-trade-off verdict.
- **Free-text decisions** run through the same real pipeline: type your own scenario, the Chief of
  Staff decides who's relevant and extracts the facts each engaged agent needs from your text.
- **The inbound webhook** (`POST /trigger/webhook`) convenes the council from an external event —
  point a mail rule or `curl` at it — and the resulting decision lands in History exactly like a
  desk run, with every call (accepted or rejected) recorded to the audit ledger first. `/audit.html`
  shows the chain and its verification status. The Dashboard's "Simulate inbound email" button
  exercises the same audited path without needing anything wired up.

  ![History: three past runs, each showing every engaged specialist's stance and the Chief of Staff's verdict](docs/images/history.png)

  *History — every run the council has made, with each specialist's stance and the verdict it led to.*

- **Council** is where you edit the agents: add, edit, or remove a plain-English rule for any of
  the four specialists, adjust a numeric threshold, and re-test live against the seed scenario to
  watch the stance move. The Chief of Staff's own persona (tone, routing guidance) is editable the
  same way; its adjudication policy and guardrails are not.

  ![The specialists grid: Finance, Delivery, PMO and Operations, each with an editable rules list](docs/images/council-specialists.png)

  *Finance, Delivery, PMO, Operations — plain-English rules and numeric thresholds, editable live,
  no redeploy.*

## Testing

```bash
cd backend
pytest
```

112 backend/routing tests, plus 7 real-browser Playwright end-to-end tests that drive the actual
served UI (catching wiring defects — a dead button, a stubbed-not-real connection, state lost on
reload — that backend unit tests structurally can't see). Every LLM call is mocked by default, so
the suite needs no reachable model and runs in a few seconds; specific tests override the mock to
verify genuine LLM-driven behaviour (a subset of agents selected, the blocker policy enforced
against a deliberately misbehaving model, and so on).

The Playwright tests skip cleanly if Playwright isn't installed. To enable them:

```bash
pip install playwright
playwright install chromium
```

## Architecture

LangGraph orchestrates a bounded, three-stage graph (`route → parallel specialists → reconcile`)
with `add_conditional_edges` fanning out only to the agents actually engaged that run — no
open-ended agent-to-agent loops, ever. FastAPI streams the run over Server-Sent Events so the
frontend renders each stage as it happens rather than waiting for the whole thing. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full technical narrative — the state shape,
the termination guarantees, the config-driven agent design, and why each of the standout-engineering
pieces above is built the way it is.

## Fork it

This is a scaffold, not a finished product. Three ways to make it yours:

- **Change the rules, not the code.** Edit `backend/agents/configs/*.json` — thresholds, gate
  names, lens descriptions — and disable/add entries in `backend/agents/manifest.json` to change
  which agents run. No Python changes needed (the Council tab does exactly this, live).
- **Change the reasoning.** Replace `evaluate()` in any `backend/agents/*.py` with your own domain
  logic (and its matching `*Config`/`*Facts` Pydantic models), or add a wholly new agent kind and
  register it in `backend/agents/registry.py`'s `AGENT_KIND_REGISTRY`. A JSON file alone can
  parameterise existing logic; a genuinely new *kind* of reasoning needs this step.
- **Change the model.** Any OpenAI-compatible endpoint works via `.env` or the Settings tab —
  OpenAI, Anthropic, Groq, OpenRouter, or a self-hosted OSS model.

## Licence

MIT — see [LICENSE](LICENSE).
