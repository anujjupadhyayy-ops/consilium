"""The API the Decision Desk, Council, Settings, and Trigger surfaces call.
Everything here is a thin layer over orchestrator/agents -- no domain logic
lives in this file."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
PACING_SECONDS = {"after_route": 0.5, "between_positions": 0.3, "before_reconcile": 0.7}


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
                    if event["kind"] == "position":
                        time.sleep((PACING_SECONDS["after_route"] if first_stage else PACING_SECONDS["between_positions"]) * pace)
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
    """The one real pipeline every run goes through -- routing, narration,
    and reconciliation are always genuine LLM calls (with a deterministic
    fallback if the model is unavailable). A seed additionally pre-supplies
    its engineered facts as a head start -- the scenario already comes
    with known figures, so there's nothing to estimate -- free text has
    none, so the Chief of Staff's routing call also extracts facts for
    whichever agents it engages."""
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
    """The live proof that rules are data: re-evaluate one agent's
    deterministic hard signal against the supplier-milestone scenario with
    the caller's config/fact overrides layered on -- no LLM, no persistence,
    just the same evaluate() every test in the suite already exercises."""
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
        position = agent.evaluate(facts)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid fact override: {exc}") from exc

    return dict(position)


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
    try:
        agent = save_agent_config(agent_id, body)
    except UnknownAgentError:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{agent_id}'.")
    except Exception as exc:  # pydantic.ValidationError or a bad value
        raise HTTPException(status_code=422, detail=f"Invalid config: {exc}") from exc
    return agent.config.model_dump()


# ------------------------------------------------------------ chief of staff --

class ChiefOfStaffConfigRequest(BaseModel):
    persona: str


@app.get("/chief-of-staff/config")
def get_chief_of_staff_config() -> dict:
    from orchestrator.cos_settings import read_cos_settings

    return read_cos_settings()


@app.put("/chief-of-staff/config")
def put_chief_of_staff_config(req: ChiefOfStaffConfigRequest) -> dict:
    """Persona/routing-guidance only -- the adjudication policy
    (operational-blocker-wins) and guardrails are not settable through
    this or any endpoint; see chief_of_staff._enforce_blocker_policy,
    which holds regardless of what this persona says."""
    from orchestrator.cos_settings import write_cos_settings

    try:
        return write_cos_settings(req.persona)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------- settings --

HOSTED_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
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

    data: dict[str, Any] = {"provider": provider, "base_url": base_url, "model_name": req.model}
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


# ---------------------------------------------------------------- trigger --

class InboundEmailRequest(BaseModel):
    from_: str = "Rahul Mehta · Delivery Partners Ltd (3PP supplier)"
    subject: str = "Re: proposal -- accelerate Milestone 4 by 3 weeks"
    body: str = (
        "We can pull Milestone 4 forward three weeks for a 15% uplift on our fee, "
        "subject to a contract variation. Let us know by Friday."
    )


@app.post("/trigger/inbound-email")
def trigger_inbound_email(req: InboundEmailRequest) -> dict:
    """Roadmap: real inbox = OAuth read-only (see Settings). This is the
    simulated version -- matches trigger_keywords from each agent's own
    config against the (simulated) email, same mechanism a real inbox
    connector would use."""
    text = f"{req.subject} {req.body}".lower()
    matched: dict[str, list[str]] = {}
    for agent in load_agents_from_manifest():
        hits = [kw for kw in agent.config.trigger_keywords if kw.lower() in text]
        if hits:
            matched[agent.id] = hits

    return {
        "from": req.from_,
        "subject": req.subject,
        "body": req.body,
        "matched": matched,
        "convened": list(matched.keys()),
        "run_text": req.body,
    }


# Mounted last so it never shadows the API routes above -- serves
# frontend/index.html at "/" and any sibling assets alongside it.
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
