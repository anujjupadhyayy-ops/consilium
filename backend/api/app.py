"""The API the Decision Desk, Council, Settings, and Trigger surfaces call.
Everything here is a thin layer over orchestrator/agents -- no domain logic
lives in this file."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from audit import ledger

from agents.registry import get_agent, get_agent_config_raw, load_agents_from_manifest, save_agent_config, UnknownAgentError
from orchestrator.graph import build_graph
from orchestrator.state import initial_state
from seeds.registry import get_seed, list_seeds

app = FastAPI(title="Consilium", version="0.4.0")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND_DIR = _REPO_ROOT / "frontend"

# Pauses inserted between streamed stages so a human watching the run can
# actually register each stage. With a real model this mostly just adds a
# floor on top of genuine inference latency; with a very fast provider (or
# a mocked/offline fallback) it's what keeps the run from flashing past in
# one imperceptible tick. Pure UI pacing -- lives here, never in
# orchestrator/graph.py, and never touches agent logic or trace content.
# `pace=0` (used by tests) disables it.
PACING_SECONDS = {"first_check": 0.5, "between_checks": 0.3, "before_reconcile": 0.7}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/seeds")
def seeds() -> list[dict]:
    return list_seeds()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_run(text: str, pace: float, facts: Optional[dict] = None) -> Iterator[str]:
    compiled = build_graph()
    state = initial_state(text, facts or {})

    try:
        first_stage = True
        for chunk in compiled.stream(state, config={"recursion_limit": 10}, stream_mode="updates"):
            for _node_name, update in chunk.items():
                for event in update.get("trace", []):
                    if event["kind"] == "check":
                        time.sleep((PACING_SECONDS["first_check"] if first_stage else PACING_SECONDS["between_checks"]) * pace)
                        first_stage = False
                    elif event["kind"] == "conflict":
                        time.sleep(PACING_SECONDS["before_reconcile"] * pace)
                    yield _sse("trace", event)
    except Exception as exc:  # recommend-only demo: surface the failure, never half-render a wrong answer
        # Named "stream_error", not "error" -- EventSource treats "error" as
        # its own reserved connection-status event, and a server-sent named
        # event sharing that name is easy to conflate with a real dropped
        # connection on the client.
        yield _sse("stream_error", {"message": str(exc)})
        return

    yield _sse("done", {})


@app.get("/run/stream")
def run_stream(text: str = "", seed_id: str = "", pace: float = 1.0) -> StreamingResponse:
    """The one real pipeline every run goes through -- every agent checks
    its own rules (no routing; nothing can be skipped), triggered agents are
    narrated, and reconciliation writes the wording (each an LLM call with a
    deterministic fallback if the model is unavailable). A seed supplies its
    authored facts and bypasses extraction; free text has none, so each
    agent runs its own evidence-verified extraction over the whole message."""
    facts = None
    if seed_id:
        seed = get_seed(seed_id)
        if seed is None:
            raise HTTPException(status_code=404, detail=f"Unknown seed '{seed_id}'.")
        if not seed.get("available", True):
            raise HTTPException(status_code=409, detail=f"Seed '{seed_id}' isn't built yet.")
        text = seed["scenario"]
        facts = seed["facts"]
    if not text.strip():
        raise HTTPException(status_code=422, detail="Provide `text` (or an available `seed_id`).")

    return StreamingResponse(
        _stream_run(text, pace, facts),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- council --

class RetestRequest(BaseModel):
    agent_id: str
    config_overrides: dict[str, Any] = {}
    fact_overrides: dict[str, Any] = {}


@app.post("/council/retest")
def council_retest(req: RetestRequest) -> dict:
    """The live proof that rules are data: re-check one agent's rules
    against the supplier-milestone scenario with the caller's config/fact
    overrides layered on -- no LLM, no persistence, just check() the same
    way every run does."""
    base_agent = get_agent(req.agent_id)
    if base_agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{req.agent_id}'.")

    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    config_data = {**base_agent.config.model_dump(), **req.config_overrides}
    try:
        config = type(base_agent.config).model_validate(config_data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid config override: {exc}") from exc

    facts = {**SUPPLIER_MILESTONE_SEED["facts"].get(req.agent_id, {}), **req.fact_overrides}

    agent = type(base_agent)(agent_id=base_agent.id, config=config)
    try:
        agent.validate_rules()
        result = agent.check(facts)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid fact override: {exc}") from exc

    if result.stance is None:
        return {
            "agent": agent.id,
            "stance": None,
            "triggered": False,
            "recommendation": "All rules checked, none tripped" if not result.unchecked else "No rule triggered",
            "reasoning": (
                "No rule fired on these facts."
                + (f" Couldn't check: {', '.join(result.unchecked)}." if result.unchecked else "")
            ),
            "driving_constraint": "",
            "lead_figure": "",
        }

    position = agent._position_from_check(facts, result)
    return {**dict(position), "triggered": True}


@app.get("/agents/{agent_id}/config")
def get_agent_config(agent_id: str) -> dict:
    """The Council UI hydrates its rule list and numeric fields from this,
    not a hardcoded copy -- so a page reload always shows what's actually
    persisted."""
    try:
        return get_agent_config_raw(agent_id)
    except UnknownAgentError:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{agent_id}'.")


@app.put("/agents/{agent_id}/config")
def put_agent_config(agent_id: str, body: dict[str, Any]) -> dict:
    """P3.6's persistence seam: rules list + numeric thresholds together,
    validated and written to agents/configs/*.json. A malformed body
    (a rule too long, too many rules, a threshold out of range, ...) is
    rejected with 422 and never applied -- see AgentConfig's validators
    and each agent's Field(ge=.., le=..) bounds."""
    agent = _save_or_reject(agent_id, lambda: save_agent_config(agent_id, body))
    return agent.config.model_dump()


def _save_or_reject(agent_id: str, save):
    """Run a config save; turn every refusal into a readable 422 and never
    a partial write (the registry validates before it writes)."""
    try:
        return save()
    except UnknownAgentError:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{agent_id}'.")
    except ValidationError as exc:
        # Readable "field: reason" lines for the Council UI, not pydantic's
        # multi-line dump (with its docs URL and repr of the rejected input).
        reasons = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors()
        )
        raise HTTPException(status_code=422, detail=f"Rejected -- {reasons}") from exc
    except Exception as exc:  # RuleError, RuleEditError, BlockerRuleImmutableError, ...
        raise HTTPException(status_code=422, detail=f"Rejected -- {exc}") from exc


@app.get("/agents/{agent_id}/rules")
def get_agent_rules(agent_id: str) -> dict:
    """The Council tab's view of one agent's rules: plain-English conditions,
    the editable threshold of each, and what a guided new rule may use."""
    from agents.rule_edit import rules_view

    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{agent_id}'.")
    return rules_view(agent)


@app.put("/agents/{agent_id}/rules")
def put_agent_rules(agent_id: str, body: dict[str, Any]) -> dict:
    """Guided rule edits -- see registry.apply_rules_request. Validates with
    the rules engine and the registry's policy; on any refusal nothing is
    saved. Returns the saved view."""
    from agents.registry import apply_rules_request
    from agents.rule_edit import rules_view

    agent = _save_or_reject(agent_id, lambda: apply_rules_request(agent_id, body))
    return rules_view(agent)


# ------------------------------------------------------------ chief of staff --

class ChiefOfStaffConfigRequest(BaseModel):
    persona: str


@app.get("/chief-of-staff/config")
def get_chief_of_staff_config() -> dict:
    from orchestrator.cos_settings import read_cos_settings

    return read_cos_settings()


@app.put("/chief-of-staff/config")
def put_chief_of_staff_config(req: ChiefOfStaffConfigRequest) -> dict:
    """Persona/wording guidance only -- the adjudication policy
    (operational-blocker-wins) and guardrails are not settable through
    this or any endpoint; see chief_of_staff._enforce_blocker_policy,
    which holds regardless of what this persona says."""
    from orchestrator.cos_settings import write_cos_settings

    try:
        return write_cos_settings(req.persona)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ----------------------------------------------------------------- profile --

class ProfileRequest(BaseModel):
    name: str
    role: Optional[str] = None


@app.get("/settings/profile")
def get_profile() -> dict:
    from profile_store import read_profile

    return read_profile()


@app.put("/settings/profile")
def put_profile(req: ProfileRequest) -> dict:
    """The display name/role shown in the header, greeting and profile card.
    Ships blank (no baked-in person) so a fork is usable as-is."""
    from profile_store import write_profile

    try:
        return write_profile(req.name, req.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ----------------------------------------------------------------- history --

class HistoryEntry(BaseModel):
    label: str
    q: str
    positions: list[dict] = []
    verdict: str
    when: str = "just now"


@app.get("/history")
def get_history() -> dict:
    from history_store import read_runs

    return {"runs": read_runs()}


@app.post("/history")
def post_history(entry: HistoryEntry) -> dict:
    """Persist a completed decision run so History survives a page reload."""
    from history_store import append_run

    runs = append_run(entry.model_dump())
    return {"runs": runs}


# --------------------------------------------------------------- settings --

HOSTED_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

# Sensible default model per hosted provider, used when a caller sends a blank
# model (keeps the API robust independent of the frontend). Groq's Llama models
# are enterprise-tier -> gpt-oss-120b is the standard-tier reasoning default.
HOSTED_PROVIDER_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4",
    "openrouter": "deepseek/deepseek-chat",
    "groq": "openai/gpt-oss-120b",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "gemini": "gemini-2.0-flash",
}


class ModelSettingsRequest(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None


@app.get("/settings/model")
def get_model_settings() -> dict:
    from model.config import ModelConfig

    config = ModelConfig.current()
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "model_name": config.model_name,
        "api_key_set": bool(config.api_key and config.api_key != "not-needed-for-local"),
    }


@app.put("/settings/model")
def put_model_settings(req: ModelSettingsRequest) -> dict:
    """Hosted providers (openai/anthropic/openrouter) get their canonical
    base URL resolved server-side -- a client-supplied base_url for one of
    these is ignored, not trusted -- and require a key. Local/self-hosted
    keeps the client's base_url and doesn't require a key."""
    from model.runtime_settings import write_runtime_settings

    provider = req.provider.strip().lower()
    if provider in HOSTED_PROVIDER_BASE_URLS:
        if not req.api_key:
            raise HTTPException(status_code=422, detail=f"An API key is required for provider '{provider}'.")
        base_url = HOSTED_PROVIDER_BASE_URLS[provider]
    else:
        base_url = req.base_url or None

    model = req.model.strip() or HOSTED_PROVIDER_DEFAULT_MODELS.get(provider, req.model)
    data: dict[str, Any] = {"provider": provider, "base_url": base_url, "model_name": model}
    if req.api_key:
        data["api_key"] = req.api_key
    write_runtime_settings(data)

    return get_model_settings()


@app.post("/settings/model/test")
def test_model_settings() -> dict:
    from model.config import ModelConfig
    from model.llm import test_connection

    ok, message = test_connection(ModelConfig.current())
    return {"connection_ok": ok, "message": message}


@app.get("/settings/model/status")
def model_status() -> dict:
    """Lightweight status for the header banner: what model is configured and
    whether it is reachable right now. Drives the "deterministic fallback --
    no model connected" indicator so an unconnected app reads as intentional,
    not broken."""
    from model.config import ModelConfig
    from model.llm import probe_model

    cfg = ModelConfig.current()
    return {"model": cfg.model_name, "base_url": cfg.base_url, "reachable": probe_model(cfg)}


# ---------------------------------------------------------------- trigger --

def _match_agents(text: str) -> dict[str, list[str]]:
    """Which agents each config's own trigger_keywords convene for this
    inbound text -- the same mechanism a real inbox/webhook connector feeds."""
    lowered = text.lower()
    matched: dict[str, list[str]] = {}
    for agent in load_agents_from_manifest():
        hits = [kw for kw in agent.config.trigger_keywords if kw.lower() in lowered]
        if hits:
            matched[agent.id] = hits
    return matched


def _record_trigger_decision(text: str, label: str) -> dict:
    """Run the real council pipeline on a triggered inbound and persist the
    decision to History, so a trigger actually produces a verdict (visible on
    the dashboard and in History) rather than only a ledger line. Recommend-
    only: this runs the recommendation pipeline; it never acts on a real system.
    Falls back / abstains exactly like a desk run when the model is weak/absent."""
    from datetime import datetime
    from orchestrator.graph import build_graph
    from orchestrator.state import initial_state
    from history_store import append_run

    result = build_graph().invoke(initial_state(text, {}), config={"recursion_limit": 10})
    positions = [dict(p) for p in result.get("positions", [])]
    rec = result.get("reconciliation", {}) or {}
    entry = {
        "label": label,
        "q": text,
        "when": datetime.now().strftime("%H:%M"),
        "positions": positions,
        "verdict": rec.get("recommendation", "(run did not complete)"),
    }
    append_run(entry)
    # The checks table (every agent's triggered/fired/unchecked/unclear/
    # evidence/provenance) goes to the tamper-evident ledger as its own
    # entry after the run -- the trigger itself was already recorded first,
    # before anything ran, so a rejected or crashed run still leaves a trace.
    return {**entry, "checks": {k: dict(v) for k, v in (result.get("checks") or {}).items()}}


def _convene_and_record(*, source: str, actor: str, subject: str, body: str, auth_ok: bool) -> dict:
    """The one path every trigger goes through. Matches keywords, then writes
    the event to the tamper-evident audit ledger BEFORE returning -- so a
    rejected (auth_ok=False) attempt is recorded too. Recommend-only: this
    convenes/flags the relevant specialists, it never auto-executes a run or
    touches a real system."""
    matched = _match_agents(f"{subject} {body}") if auth_ok else {}
    entry = ledger.record({
        "kind": "trigger",
        "source": source,
        "actor": actor,
        "subject": subject,
        "body": body,
        "auth_ok": auth_ok,
        "matched": matched,
        "convened": list(matched.keys()),
        "run_text": body,
        "recommend_only": True,
    })
    return {
        "event_id": entry["seq"],
        "entry_hash": entry["entry_hash"],
        "recorded_at": entry["ts"],
        "auth_ok": auth_ok,
        "source": source,
        "actor": actor,
        "subject": subject,
        "body": body,
        "matched": matched,
        "convened": list(matched.keys()),
        "run_text": body,
    }


class InboundEmailRequest(BaseModel):
    from_: str = "Rahul Mehta · Delivery Partners Ltd (3PP supplier)"
    subject: str = "Re: proposal -- accelerate Milestone 4 by 3 weeks"
    body: str = (
        "We can pull Milestone 4 forward three weeks for a 15% uplift on our fee, "
        "subject to a contract variation. Let us know by Friday."
    )


@app.post("/trigger/inbound-email")
def trigger_inbound_email(req: InboundEmailRequest) -> dict:
    """Simulated-inbox demo trigger (real inbox = OAuth, roadmap -- see
    Settings). Kept for the Dashboard's built-in demo; delegates to the same
    audited core as the webhook, so it too lands in the ledger."""
    return _convene_and_record(
        source="inbound-email (simulated)", actor=req.from_,
        subject=req.subject, body=req.body, auth_ok=True,
    )


class WebhookRequest(BaseModel):
    """A real, credential-free inbound. Point a mail-forwarding rule, an
    Apps Script, Zapier/Make, or `curl` at this endpoint -- the sender's own
    tool owns the auth, so Consilium never stores anyone's mailbox
    credentials (a cleaner posture than OAuth for a recommend-only demo)."""
    source: str = "webhook"
    actor: str = ""
    subject: str = ""
    body: str


@app.post("/trigger/webhook")
def trigger_webhook(
    req: WebhookRequest,
    x_consilium_token: Optional[str] = Header(default=None),
) -> dict:
    """Optional shared-secret gate: set CONSILIUM_WEBHOOK_TOKEN and callers
    must send it as the X-Consilium-Token header. Every call is recorded to
    the audit chain first -- including a rejected one -- then an unauthorised
    call gets a 401. With no token configured the endpoint is open (fine for
    a local demo)."""
    expected = os.environ.get("CONSILIUM_WEBHOOK_TOKEN")
    auth_ok = expected is None or x_consilium_token == expected

    result = _convene_and_record(
        source=req.source or "webhook", actor=req.actor,
        subject=req.subject, body=req.body, auth_ok=auth_ok,
    )
    if not auth_ok:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or missing X-Consilium-Token (rejected attempt logged as event #{result['event_id']}).",
        )
    # A real trigger runs the council and records the verdict -- not just a log.
    decision = _record_trigger_decision(req.body, f"Webhook: {req.subject or 'inbound email'}")
    checks = decision.pop("checks", {})
    ledger.record({
        "kind": "council_checks",
        "trigger_event_id": result["event_id"],
        "checks": checks,
        "verdict": decision["verdict"],
        "recommend_only": True,
    })
    result["decision"] = decision
    return result


@app.get("/trigger/audit")
def get_trigger_audit(limit: int = 100, before_seq: Optional[int] = None) -> dict:
    """The audit surface: newest-first trigger events plus the chain's
    verification status, so the log can be read and independently checked in
    one call."""
    return {
        "chain": ledger.verify_chain(),
        "entries": ledger.read_entries(limit=limit, before_seq=before_seq),
    }


@app.get("/trigger/audit/verify")
def verify_trigger_audit() -> dict:
    """Recompute the whole chain and report whether it's intact -- the
    tamper-evidence check on its own."""
    return ledger.verify_chain()


# Mounted last so it never shadows the API routes above -- serves
# frontend/index.html at "/" and any sibling assets alongside it.
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
