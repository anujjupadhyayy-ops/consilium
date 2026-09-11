# Showcase & Distribution Plan — Consilium
Owner: Anuj Upadhyay · Drafted with Claude · 2026-09-09 · v0.1

The build is the proof; **the showcase is the reach.** Reach is the point (Arc A). This plan defines what ships around the scaffold so it converts a stranger into "this person understands multi-agent ecosystems."

---

## Asset 1 — The "how it was built" page (the centrepiece)
Single-file HTML, your house style ("developed with Claude · by Anuj Upadhyay"), theme-aware, mobile-stacked. Reading material that showcases **tech proficiency AND business foresight** in one scroll.

**Sections (in order):**
1. **Hero** — one line on what Consilium is + the demo link + the 90-sec video embedded/linked. The orchestration trace is the first thing seen.
2. **The problem it answers** — why a back-office decision is inherently multi-function, and why one chatbot can't do it. (Sets up the whole thesis.)
3. **The architecture** — an infographic of the supervisor topology: master → 4 specialists → reconcile. This is the tech-proficiency proof; make the diagram genuinely explanatory, not decorative.
4. **How the orchestration works** — routing, parallel dispatch, disagreement, reconciliation, termination. The techniques, named (LangGraph, supervisor pattern, shared state, bounded loops, OpenAI-compatible model layer). This is where you show you know the *primitives*, not just the tools.
5. **The agent profiles** — the business-depth layer. Each function's lens and the real judgement it encodes. This is the un-copyable part and the business-foresight proof.
6. **Honest limits** — recommend-only, scaffold-not-employee, where it degrades. This section *raises* your credibility with senior readers, not lowers it.
7. **Fork it** — repo link, one-paragraph "run it with your own model in 5 minutes."

**Infographics to build (keep them explanatory):** (a) the supervisor topology; (b) a single decision's flow through the graph (input → route → 4 positions → conflict → reconcile); (c) the model-layer abstraction (BYO-LLM). Three is enough — more becomes noise.

## Asset 2 — The video (90 seconds)
Screen-recording of one seed scenario running through the trace UI. Script: 10s problem → 15s master routes (show reasoning) → 20s specialists work in parallel → 15s the disagreement → 20s reconciliation → 10s "fork it, bring your own model." Visual > narration; captions over voiceover. This is the single highest-reach asset — recording > stills, learned from the Delivery Dashboard.

## Asset 3 — Screenshots
3–4 stills for LinkedIn/README: the trace mid-run, the disagreement moment, the reconciliation output, the architecture diagram. The disagreement moment is the thumbnail.

## Asset 4 — Live demo
Deployed, rate-limited, on a cheap OSS model you fund, with a BYO-key field. Seed buttons + free-text box. A visible "recommend-only · scaffold demo" banner sets expectations and doubles as the honesty signal.

## Asset 5 — The repo
Public, MIT. README = what it is, the architecture diagram, "run with your own model in 5 min," and a "how to add an agent" section (turns the OUT-scope into an invitation). Clean commit history is itself a proficiency signal.

---

## Distribution — the part that's actually Arc A
- **LinkedIn post** — *after* everything above ships, not before. Lead with the video. Link in the body, not comments. Tue–Thu ~08:30 BST.
- **The 5 inboxes** — the discipline rule: this is not "done" until it's in **5 named inboxes** — hiring managers / people in-lane from the Target Hitlist. The public post is reach; the 5 inboxes are the point. Send the demo link + one line on what it demonstrates about how you think.
- **Featured** — add to LinkedIn Featured alongside the Intentional AI Framework, Dexter, the dashboards. This is the piece that reframes the whole set from "dashboards" to "systems."

## Definition of done (showcase)
Page published · video live · demo link works (seed + free-text) · repo public with fork guide · in 5 named inboxes. Then, and only then, the LinkedIn post.

## Sequencing note
Build order is P1→P5 (see Build Brief). The showcase assets are P5 — **but** draft the page's section skeleton and the video script at P0, so every build phase points at a known destination. Destination before journey; it's the standing bottleneck fix.
