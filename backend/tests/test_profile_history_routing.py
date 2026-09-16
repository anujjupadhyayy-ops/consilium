"""Profile, history, webhook and static-routing coverage -- the middleware/
routing and persistence layers the UI depends on."""
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


# -- profile --------------------------------------------------------------
def test_profile_default_is_generic(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    body = client.get("/settings/profile").json()
    assert body["name"] == ""          # ships with no baked-in person
    assert body["role"]                # a sensible default role


def test_profile_put_persists_and_survives(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    r = client.put("/settings/profile", json={"name": "Jordan Lee", "role": "Head of PMO"})
    assert r.status_code == 200 and r.json()["name"] == "Jordan Lee"
    # a fresh read (simulating reload) still has it
    assert client.get("/settings/profile").json() == {"name": "Jordan Lee", "role": "Head of PMO"}


def test_profile_rejects_empty_name(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    assert client.put("/settings/profile", json={"name": "   "}).status_code == 422


# -- history --------------------------------------------------------------
def test_history_empty_then_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    assert client.get("/history").json()["runs"] == []
    client.post("/history", json={"label": "Test", "q": "scenario", "verdict": "Decline", "positions": []})
    runs = client.get("/history").json()["runs"]      # a fresh read survives "reload"
    assert len(runs) == 1 and runs[0]["verdict"] == "Decline"


# -- webhook (the real trigger) -------------------------------------------
def test_webhook_matches_keywords_and_convenes(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CONSILIUM_WEBHOOK_TOKEN", raising=False)
    r = client.post("/trigger/webhook", json={"subject": "Milestone slip", "body": "licence and schedule at risk"})
    assert r.status_code == 200
    assert r.json()["convened"]        # at least one agent matched its keywords


def test_webhook_rejects_bad_token_but_still_records(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONSILIUM_WEBHOOK_TOKEN", "secret")
    r = client.post("/trigger/webhook", json={"body": "anything"}, headers={"X-Consilium-Token": "wrong"})
    assert r.status_code == 401
    assert "logged as event" in r.json()["detail"]   # rejected attempt is still audited


# -- static routing / middleware ------------------------------------------
def test_root_serves_the_app():
    r = client.get("/")
    assert r.status_code == 200 and "Consilium" in r.text


def test_audit_viewer_is_served():
    assert client.get("/audit.html").status_code == 200


def test_unknown_path_is_404():
    assert client.get("/no-such-route").status_code == 404


# -- hosted-provider default model ----------------------------------------
def test_blank_model_falls_back_to_provider_default(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    r = client.put("/settings/model", json={"provider": "groq", "model": "", "api_key": "gsk_x"})
    assert r.status_code == 200
    assert r.json()["model_name"] == "openai/gpt-oss-120b"        # standard-tier default, not blank
    assert r.json()["base_url"] == "https://api.groq.com/openai/v1"


# -- webhook actually runs the council and records a decision ---------------
def test_webhook_runs_council_and_records_to_history(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CONSILIUM_WEBHOOK_TOKEN", raising=False)
    assert client.get("/history").json()["runs"] == []
    r = client.post("/trigger/webhook", json={
        "subject": "Milestone slip",
        "body": "licence, schedule and budget at risk; supplier price increase and a contract variation",
    })
    assert r.status_code == 200
    d = r.json()
    assert d.get("decision") and d["decision"]["verdict"]      # a real verdict, not just a log line
    runs = client.get("/history").json()["runs"]
    assert len(runs) == 1                                        # the webhook decision landed in History
    assert runs[0]["label"].startswith("Webhook")
