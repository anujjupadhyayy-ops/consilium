import json

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def _parse_sse(raw_text: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw_text.strip().split("\n\n"):
        if not block:
            continue
        event_line, data_line = block.split("\n", 1)
        event = event_line.removeprefix("event: ")
        data = json.loads(data_line.removeprefix("data: "))
        events.append((event, data))
    return events


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_seeds_lists_four_seeds_one_available():
    response = client.get("/seeds")

    seeds = response.json()
    assert len(seeds) == 4
    assert sum(1 for s in seeds if s["available"]) == 1
    assert next(s for s in seeds if s["id"] == "supplier_milestone")["available"] is True
    assert "facts" not in seeds[0]  # summaries only


def test_stream_unknown_seed_returns_404():
    response = client.get("/run/does-not-exist/stream")

    assert response.status_code == 404


def test_stream_unavailable_seed_emits_an_error_event():
    response = client.get("/run/budget_overrun/stream?pace=0")

    events = _parse_sse(response.text)
    assert events[0][0] == "error"


def test_stream_supplier_milestone_emits_the_full_trace_in_order(seed_facts):
    response = client.get("/run/supplier_milestone/stream?pace=0")

    events = _parse_sse(response.text)
    kinds = [data["kind"] for event, data in events if event == "trace"]

    assert kinds[0] == "route"
    assert kinds.count("position") == 4
    assert kinds[-2] == "conflict"
    assert kinds[-1] == "reconciliation"
    assert events[-1][0] == "done"


def test_stream_positions_match_the_designed_conflict():
    response = client.get("/run/supplier_milestone/stream?pace=0")

    events = _parse_sse(response.text)
    stances = {
        data["agent"]: data["payload"]["stance"]
        for event, data in events
        if event == "trace" and data["kind"] == "position"
    }

    assert stances == {"finance": "no", "delivery": "yes", "pmo": "conditional", "operations": "blocker"}
