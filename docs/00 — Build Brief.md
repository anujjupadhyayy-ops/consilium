# Multi-Agent Back-Office — Build Brief
**Working name: Consilium** *(a council of specialist agents; the master adjudicates)*
Owner: Anuj Upadhyay · Drafted with Claude · 2026-09-09 · v0.2 (P0 frozen)

---

## The one line
A forkable, open-source multi-agent back-office scaffold: a **master orchestrator** routes any back-office decision to specialist function agents (Finance, Delivery, PMO, Operations), lets them reason and **disagree**, and reconciles their positions into a defensible recommendation — with the orchestration **visible on screen**.

## The ball — why this exists
Move Anuj's public signal from *"builds dashboards / vibe-codes"* → *"understands and can design a multi-agent user ecosystem."* Proven by **architecture + visible orchestration + the business depth of the agent profiles** — not by claiming an autonomous AI employee. Specific audience: **non-technical business leaders** who will remember Anuj because he made something technical legible *in their language*.

## Product position (Path A — LOCKED)
Consilium is a **domain-agnostic multi-agent decision framework**, not a finance/back-office product. What is generic and reusable is the **framework** (orchestration engine + trace UI) and the **agent-design method**; the specific agent rules are **user-definable, swappable config** a forker sets for their own world. Delivery/commercial is only the **flagship demo** because it is Anuj's domain. The demo agents ship **expert but illustrative** logic (not Anuj's literal/proprietary employer rules — a confidentiality line, and more generic besides). Depth is demonstrated by the **capability and complexity the agents can hold** (e.g. a time-phased forecast flag), not by whose thresholds they are. Reframe "back-office" throughout as "decision framework (demoed on a delivery/commercial back-office)."

**Generality check (Anuj, 2026-09-12):** the four example agents are industry-standard spines (commercial/finance discipline · EVM · PRINCE2/MSP · capacity/spend/savings/supplier) with illustrative, user-definable values — usable by the wider PMO/Ops/Delivery community, not just Anuj. Caveat: PMO leans PRINCE2/MSP (UK/enterprise/gov); editable rules let an Agile/SAFe shop swap it — which is exactly why user-editable agents are core.

## Framing decision (LOCKED)
**Forkable scaffold, not a finished autonomous back-office.** General-purpose multi-agent on arbitrary input degrades into generic mush, and over-claiming reads as naive to the senior audience. A clean, honest, forkable scaffold signals *someone who understands the system deeply enough to know its limits* — the mature signal, achievable solo.

## P0 — FROZEN (2026-09-09)
- **Name:** Consilium
- **Agents:** Finance · Delivery · PMO · Operations *(Legal dropped from v1 → roadmap; its contract-variation remit folds into PMO governance)*
- **Stack:** LangGraph (orchestration) + custom UI reusing the Voyij design system
- **Seeds (4):** supplier-milestone variation · budget overrun · resourcing clash · Project PME compliance

## Three entry points, one architecture
1. **Demo seed** — pre-loaded scenarios (one click) that guarantee visible conflict + reconciliation. Carries the recording; on-ramp for first-time users.
2. **Free-text** — user types their own situation; the master clarifies if thin, then routes.
3. **Fork** — a developer clones the repo, wires in their own context/model, extends the agents. The real distribution.

## Scope — IN (v1)
- Master orchestrator (supervisor): route → dispatch → collect → **reconcile** → recommend.
- 4 specialist agents — Finance, Delivery, PMO, Operations — with real domain logic ("through Anuj's eyes").
- General free-text input + a **clarification step** (1–2 questions when input is thin).
- 4 one-click seed scenarios.
- The **orchestration-trace UI** (the hero): routing decision, parallel specialist work, surfaced disagreement, reconciliation — all legible to a non-technical exec.
- **BYO-LLM**: OpenAI-compatible config; open demo on a cheap OSS model behind a rate limit.
- **Agent rules as editable config** (not hardcoded) — foundation for user-editable agents; the P4 UI reads/writes this.
- Public repo + README + fork guide + MIT licence.

## Scope — OUT (v1 — roadmap, stated openly)
- Legal / HR as separate agents.
- User-adds-own-agent UI (fork to add).
- Scenario library beyond the 4 seeds.
- Autonomous action / writing to real systems — **recommend-only**.
- Retrieval / RAG per agent (roadmap — the one ecosystem layer v1 leaves out).
- Auth, multi-user, persistence beyond a session.

## Architecture (v1)
- **Topology:** supervisor (hierarchical). Master = router + reconciler; specialists = leaf nodes, run in parallel where independent.
- **State:** a shared graph state carries input, each agent's position, the conflict set, the reconciliation.
- **Termination:** bounded — one routing pass, one specialist pass, one reconcile. **No open-ended agent-to-agent loops in v1** (stops runaway token burn).
- **Clarification:** if the master's input-completeness check fails, ask 1–2 questions before dispatch.
- **Guardrail:** recommend-only; every output states assumptions + what it did **not** consider. No certainty claims.

## Ecosystem coverage (the proficiency proof)
Built this way, Consilium legitimately spans **5 of the 6** agentic-stack layers, each pointable-to as Anuj's own work:
Orchestration (LangGraph supervisor) · LLMs (BYO/OSS model layer) · Memory & State (shared graph + session state) · Safety/Governance (recommend-only guardrail, stated assumptions, LangSmith tracing) · Backend/Serving (deployed API + model endpoint). **Retrieval** is the deliberate v1 omission → roadmap.

## Tech stack (LOCKED)
- **Orchestration: LangGraph (Python).** Explicit control over routing/termination; the honest "I understand the primitives" signal. Prebuilt supervisor keeps custom orchestration small.
- **Frontend: custom, lightweight**, reusing the Voyij design system (see UI/UX standard). Deliberate: no-code canvases give a builder view, not a branded end-user *trace UI* — and the trace UI **is** the differentiator.
- **Model layer:** OpenAI-compatible client — OpenAI / Anthropic / OSS (Kimi, Qwen, Llama) drop in by config.
- **Deploy:** backend on Render/Railway/Fly; frontend on Vercel. Open demo rate-limited on a cheap OSS model; BYO-key field.
- **Observability:** LangSmith (or equivalent) tracing from P1 — you cannot debug multi-agent blind, and the traces become showcase screenshots.
- **Fallback (only if the custom build threatens Arc A):** build the crew in LangFlow/Flowise, export, ship recording + export. Weaker showcase; use as escape hatch, not plan.

## UI/UX standard (LOCKED)
Bar = the **Voyij prototype** (`Voyji Traveller/Mobile View - Deployment 3/index.html`): warm token-driven design system, full light/dark, multi-screen SPA with real flows and microcopy that has a voice.

- **Reuse, don't rebuild.** Lift the Voyij design system wholesale: tokens (coral `#FF5D3A`, teal, warm ground `#FBF6F0`, surface/shadow/radius scales, categorical `--c1..c4`, chart tokens), fonts (**Bricolage Grotesque** display / **Figtree** body / **JetBrains Mono** data), the `icon()`/`money()` helper pattern, the 3-state theme handling. Buys Voyij-grade polish cheaply; gives the portfolio **one visual family** (Voyij + dashboards + Consilium).
- **UX success = orchestration legibility, for a non-technical exec.** The bar is NOT "as beautiful as Voyij" — it is "a business leader watches once and *sees* the agents disagree and the master adjudicate, and remembers it." Spend the design hours on the trace UI, not on re-deriving a look. A pretty chatbot-with-tabs is the exact bucket this project exists to escape.
- **Honest scope flag.** Voyij is a front-end prototype on mock data (~830 lines JS). Consilium adds a live async backend (LangGraph, streaming, real latency). Voyij polish + real orchestration + deploy is MORE than Voyij was. Reusing the design system is what keeps it affordable.

## Build phases (timeboxed — Arc A protected)
- **P0 — Design freeze.** ✅ Done (this brief + agent profiles + 4 seeds).
- **P1 — Orchestration spine + repo.** Git init + GitHub remote; LangGraph supervisor + 4 stub agents + bounded termination + LangSmith tracing; one seed running end-to-end in the terminal. Proves the mechanism.
- **P2 — Real agent profiles.** Domain logic per agent; genuine conflict emerges on the supplier seed.
- **P3 — Trace UI.** The hero screen. *The recordable demo exists at the end of this phase.*
- **P4 — Free-text + clarification + model config + rate-limited demo deploy + user-editable agents UI (Copilot-style edit/create-an-agent; the headline "plug in your own brain" feature).**
- **P5 — Showcase.** Page, video, screenshots, README; ship + 5 inboxes.

Each phase is a **stopping point.** If the role hunt (Arc A) needs the weeks, stop after **P3** — you already have a recordable demo — and build the showcase around it.

## Definition of done
Page published · demo link works (seed + free-text) · repo public with fork guide · **in 5 named inboxes.** Not "done when the 5th agent is added."

## Risks & mitigations
- *Generic mush on real input* → recommend-only + clarification + honest scaffold framing.
- *Cost/abuse on demo* → cheap OSS model + rate limit + BYO-key; no Anthropic account exposed.
- *Scope creep (Arc-B trap)* → phases are stopping points; OUT-list explicit; P3 already yields a demo.
- *Token burn* → bounded single-pass topology, no open agent loops in v1.
- *Streaming-to-UI is the hard part* → prove the spine in the terminal (P1) before touching the UI (P3).
