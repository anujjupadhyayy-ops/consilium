"""Webhook trigger + tamper-evident audit ledger."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from audit import ledger


@pytest.fixture
def log(tmp_path):
    """Isolate every test on its own empty ledger file."""
    return tmp_path / "audit.jsonl"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient whose endpoints write to a throwaway ledger + no token."""
    monkeypatch.setenv("CONSILIUM_AUDIT_LOG", str(tmp_path / "api_audit.jsonl"))
    monkeypatch.delenv("CONSILIUM_WEBHOOK_TOKEN", raising=False)
    from api.app import app

    return TestClient(app)


# ------------------------------------------------------------------ ledger --

def test_record_appends_and_returns_entry(log):
    entry = ledger.record({"kind": "trigger", "actor": "a", "subject": "s", "body": "b"}, path=log)
    assert entry["seq"] == 0
    assert entry["prev_hash"] == ledger.GENESIS_HASH
    assert len(entry["entry_hash"]) == 64
    assert log.read_text().strip().count("\n") == 0  # exactly one line


def test_chain_links_each_entry_to_the_previous(log):
    a = ledger.record({"body": "one"}, path=log)
    b = ledger.record({"body": "two"}, path=log)
    assert b["seq"] == 1
    assert b["prev_hash"] == a["entry_hash"]


def test_verify_passes_on_an_untampered_chain(log):
    for i in range(4):
        ledger.record({"body": f"event {i}"}, path=log)
    result = ledger.verify_chain(path=log)
    assert result["ok"] is True
    assert result["entries"] == 4
    assert result["broken_at"] is None


def test_verify_detects_content_tampering(log):
    ledger.record({"body": "genuine"}, path=log)
    ledger.record({"body": "also genuine"}, path=log)

    # Edit a past entry's content in place, leaving its stored hash unchanged.
    lines = log.read_text().splitlines()
    first = json.loads(lines[0])
    first["body"] = "TAMPERED"
    lines[0] = json.dumps(first, ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n")

    result = ledger.verify_chain(path=log)
    assert result["ok"] is False
    assert result["broken_at"] == 0


def test_verify_detects_a_deleted_entry(log):
    for i in range(3):
        ledger.record({"body": f"e{i}"}, path=log)
    lines = log.read_text().splitlines()
    del lines[1]  # drop the middle entry
    log.write_text("\n".join(lines) + "\n")

    result = ledger.verify_chain(path=log)
    assert result["ok"] is False  # seq gap / broken link exposes the deletion


def test_verify_on_empty_ledger_is_ok(log):
    assert ledger.verify_chain(path=log)["ok"] is True


# ----------------------------------------------------------------- webhook --

def test_webhook_convenes_and_records(client):
    r = client.post("/trigger/webhook", json={
        "source": "zapier", "actor": "ops@corp",
        "subject": "supplier cost increase", "body": "3PP wants a 15% uplift on the contract",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["auth_ok"] is True
    assert "finance" in data["convened"]  # 'cost'/'supplier'/'3pp' are finance keywords
    assert isinstance(data["event_id"], int)

    audit = client.get("/trigger/audit").json()
    assert audit["chain"]["ok"] is True
    # Rewrite: a webhook run now appends TWO ledger entries (the trigger,
    # recorded first, then a council_checks entry with the checks table),
    # newest first -- so the trigger is no longer entries[0].
    trigger = next(e for e in audit["entries"] if e.get("kind") == "trigger")
    assert trigger["actor"] == "ops@corp"


def test_webhook_without_token_when_one_is_required_is_rejected_but_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSILIUM_AUDIT_LOG", str(tmp_path / "a.jsonl"))
    monkeypatch.setenv("CONSILIUM_WEBHOOK_TOKEN", "s3cret")
    from api.app import app
    c = TestClient(app)

    r = c.post("/trigger/webhook", json={"body": "approve the supplier variation"})
    assert r.status_code == 401

    # the rejected attempt is still in the audit trail, marked auth_ok=False
    audit = c.get("/trigger/audit").json()
    assert audit["chain"]["ok"] is True
    assert audit["entries"][0]["auth_ok"] is False
    assert audit["entries"][0]["convened"] == []  # nothing convened on a rejected call


def test_webhook_with_correct_token_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSILIUM_AUDIT_LOG", str(tmp_path / "a.jsonl"))
    monkeypatch.setenv("CONSILIUM_WEBHOOK_TOKEN", "s3cret")
    from api.app import app
    c = TestClient(app)

    r = c.post("/trigger/webhook", json={"body": "budget overspend on the programme"},
               headers={"X-Consilium-Token": "s3cret"})
    assert r.status_code == 200
    assert r.json()["auth_ok"] is True


def test_inbound_email_still_works_and_is_audited(client):
    """Back-compat: the original demo trigger routes through the same core."""
    r = client.post("/trigger/inbound-email", json={})  # uses the built-in defaults
    assert r.status_code == 200
    assert r.json()["convened"]
    assert client.get("/trigger/audit/verify").json()["ok"] is True


def test_webhook_run_records_the_checks_table_and_chain_still_verifies(client):
    r = client.post("/trigger/webhook", json={"subject": "s", "body": "The licence is not provisioned for the new date."})
    assert r.status_code == 200
    audit = client.get("/trigger/audit").json()
    checks_entry = next(e for e in audit["entries"] if e.get("kind") == "council_checks")
    assert set(checks_entry["checks"]) == {"finance", "delivery", "pmo", "operations"}
    for check in checks_entry["checks"].values():
        assert {"triggered", "stance", "fired", "unchecked", "unclear", "evidence", "provenance"} <= set(check)
    assert audit["chain"]["ok"] is True


def test_tampering_with_a_recorded_checks_entry_is_still_detected(client, tmp_path, monkeypatch):
    import json as _json
    from pathlib import Path

    log = Path(tmp_path / "api_audit.jsonl")
    client.post("/trigger/webhook", json={"subject": "s", "body": "budget overspend"})
    lines = log.read_text().splitlines()
    idx = next(i for i, ln in enumerate(lines) if _json.loads(ln).get("kind") == "council_checks")
    entry = _json.loads(lines[idx])
    entry["verdict"] = "TAMPERED"
    lines[idx] = _json.dumps(entry, ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n")
    assert client.get("/trigger/audit/verify").json()["ok"] is False
