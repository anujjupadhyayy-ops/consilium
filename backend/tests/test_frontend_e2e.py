"""Real browser end-to-end tests: a headless Chromium drives the actual served
UI against a live app, so wiring defects (a dead button, a fake 'Connected'
stub, history lost on reload) are caught -- the class of bug backend unit tests
structurally cannot see.

Skips cleanly if Playwright or its browser isn't installed (e.g. plain CI):
run `pip install playwright && playwright install chromium` to enable.
"""
import os
import shutil
import socket
import threading
import time
import urllib.request

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402
import uvicorn  # noqa: E402
from _pytest.monkeypatch import MonkeyPatch  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    os.environ["CONSILIUM_DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    # Force the deterministic fallback path (no model) so runs complete fast.
    os.environ["MODEL_PROVIDER"] = "oss"
    os.environ["BASE_URL"] = "http://127.0.0.1:1"

    # Isolate the live server's agent configs from the repo's tracked JSON --
    # test_agent_rule_editable_after_saving really does PUT /agents/pmo/config
    # against this server, and without this it silently dirties
    # backend/agents/configs/pmo.json on disk every time the suite runs
    # (module-scoped monkeypatch, since pytest's function-scoped `monkeypatch`
    # fixture can't be requested here).
    from agents import registry

    configs_dir = tmp_path_factory.mktemp("e2e_configs")
    shutil.copytree(registry.DEFAULT_CONFIGS_DIR, configs_dir, dirs_exist_ok=True)
    manifest_path = tmp_path_factory.mktemp("e2e_manifest") / "manifest.json"
    manifest_path.write_text(registry.DEFAULT_MANIFEST_PATH.read_text())
    mp = MonkeyPatch()
    mp.setattr(registry, "DEFAULT_CONFIGS_DIR", configs_dir)
    mp.setattr(registry, "DEFAULT_MANIFEST_PATH", manifest_path)

    from api.app import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield url
    server.should_exit = True
    time.sleep(0.3)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium not available (run 'playwright install chromium'): {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, base_url):
    pg = browser.new_page()
    pg.goto(base_url)
    yield pg
    pg.close()


def test_edit_profile_works_and_persists(page, base_url):
    page.click("#pfp")                       # open Settings
    page.click("#edit-profile")
    page.fill("#pf-name-in", "Jordan Lee")
    page.fill("#pf-role-in", "Head of PMO")
    page.click("#pf-save")
    page.wait_for_selector("#pf-name:has-text('Jordan Lee')")
    assert page.inner_text("#pfp").strip() == "JL"     # header avatar initials
    page.reload()                                       # survives reload (backed by server)
    page.click("#pfp")
    page.wait_for_selector("#pf-name:has-text('Jordan Lee')")


def test_no_fake_connect_and_webhook_records_to_ledger(page):
    page.click("#pfp")
    assert page.locator("#wh-send").count() == 1
    assert page.locator("a[href='/audit.html']").count() >= 1
    # the misleading fake connect buttons are gone
    assert "Connect with Google" not in page.content()
    assert page.locator("[data-conn]").count() == 0
    page.fill("#wh-body", "We can pull Milestone 4 forward; the licence, schedule and budget are at risk.")
    page.click("#wh-send")
    page.wait_for_selector("#wh-result:has-text('Verdict')")   # ran the council, not just logged
    page.click("[data-v='history']")
    page.wait_for_selector("#hgrid .hrow", timeout=20000)      # the webhook decision landed in History


def test_cos_defines_blocker_and_conflict(page):
    page.click("[data-v='council']")
    body = page.inner_text("#view-council")
    assert "unexecutable as scoped" in body      # blocker definition
    assert "adjudicates" in body                 # conflict definition
    assert "only if a stated condition" in body  # conditional definition


def test_history_survives_reload(page):
    page.click("[data-v='decision']")
    page.fill("#q", "Delivery wants to pull go-live forward 3 weeks; the new licence isn't provisioned for that date.")
    page.click("#run")
    page.click("[data-v='history']")
    page.wait_for_selector("#hgrid .hrow", timeout=20000)
    before = page.locator("#hgrid .hrow").count()
    assert before >= 1
    page.reload()
    page.click("[data-v='history']")
    page.wait_for_selector("#hgrid .hrow", timeout=10000)
    assert page.locator("#hgrid .hrow").count() >= before   # persisted, not lost


def test_agent_rule_editable_after_saving(page):
    page.click("[data-v='council']")
    rule = page.locator("#rl-pmo .rin").first
    rule.fill("Escalate any contract variation above tolerance to governance.")
    page.click("[data-save='pmo']")
    page.wait_for_selector("#res-pmo.show")
    # still editable after a save -- the reported bug
    rule2 = page.locator("#rl-pmo .rin").first
    rule2.fill("Escalate contract variations above tolerance to the governance gate.")
    page.click("[data-save='pmo']")
    page.wait_for_selector("#res-pmo:has-text('saved')")


def test_selecting_a_provider_sets_its_model_and_base_url(page):
    page.click("#pfp")                                  # Settings
    page.select_option("#s-prov", label="Anthropic")
    assert page.input_value("#s-model") == "claude-sonnet-4"
    assert page.input_value("#s-url") == "https://api.anthropic.com/v1"
    assert page.locator("#s-url").is_disabled()          # base URL locked for hosted providers
    page.select_option("#s-prov", label="Groq (free, fast)")
    assert page.input_value("#s-model") == "openai/gpt-oss-120b"
    assert page.input_value("#s-url") == "https://api.groq.com/openai/v1"
    assert page.input_value("#s-model").strip() != ""    # never a blank model for a hosted provider


def test_audit_viewer_loads(page, base_url):
    page.goto(base_url + "/audit.html")
    assert "ledger" in page.content().lower()


# ------------------------------------------------ P3.6 §6.8 additions --

def _run_seed_in_ui(page):
    page.click("[data-v='decision']")
    page.click(".chip[data-id='supplier_milestone']")
    page.wait_for_selector("#stage .verdict-block.show", timeout=20000)
    page.wait_for_function("!document.getElementById('run').disabled", timeout=20000)


def _real_stream_events(base_url, query):
    import json as _json

    raw = urllib.request.urlopen(f"{base_url}/run/stream?{query}&pace=0", timeout=20).read().decode()
    events = []
    for block in raw.strip().split("\n\n"):
        head, data = block.split("\n", 1)
        events.append((head.removeprefix("event: "), _json.loads(data.removeprefix("data: "))))
    return events


def _sse_body(events):
    import json as _json

    return "".join(f"event: {e}\ndata: {_json.dumps(d)}\n\n" for e, d in events)


def test_step_one_label_is_council_checks_its_rules(page):
    _run_seed_in_ui(page)
    stage = page.inner_text("#stage")
    assert "Council checks its rules" in stage
    assert "routes the decision" not in stage


def test_triggered_cards_show_stance_and_seeded_provenance(page):
    _run_seed_in_ui(page)
    ops = page.locator("#lane-operations")
    assert "blocker" in ops.inner_text().lower()  # badge is CSS-uppercased
    assert "seeded" in ops.inner_text().lower()
    assert "no" in page.locator("#lane-finance").inner_text().lower()


def test_all_agents_render_in_manifest_order_even_when_checks_arrive_reversed(page, base_url):
    events = _real_stream_events(base_url, "seed_id=supplier_milestone")
    checks = [ev for ev in events if ev[0] == "trace" and ev[1]["kind"] == "check"]
    rest = [ev for ev in events if not (ev[0] == "trace" and ev[1]["kind"] == "check")]
    reversed_events = list(reversed(checks)) + rest
    page.route("**/run/stream*", lambda route: route.fulfill(
        status=200, content_type="text/event-stream", body=_sse_body(reversed_events)))
    _run_seed_in_ui(page)
    order = page.eval_on_selector_all("#stage .lane", "els => els.map(e => e.id)")
    assert order == ["lane-finance", "lane-delivery", "lane-pmo", "lane-operations"]
    page.unroute("**/run/stream*")


def test_not_triggered_cards_say_no_rule_triggered_and_never_skipped_or_no_impact(page):
    page.click("[data-v='decision']")
    page.fill("#q", "Please advise on this vague request; no figures are given at all.")
    page.click("#run")
    page.wait_for_selector("#stage .verdict-block.show", timeout=20000)
    stage = page.inner_text("#stage")
    assert "No rule triggered" in stage and "Couldn't check:" in stage
    assert "skipped" not in stage.lower() and "no impact" not in stage.lower()
    assert page.locator("#rail .node").count() == 5  # four agents + reconcile, always present


def test_unclear_tripwire_renders_amber_and_verdict_panel_shows_the_cap(page):
    page.click("[data-v='decision']")
    page.fill("#q", "We are still checking whether the licence will be ready for the earlier date.")
    page.click("#run")
    page.wait_for_selector("#stage .verdict-block.show", timeout=20000)
    unclear = page.locator("#stage .unclear-line")
    assert unclear.count() >= 1
    assert "mentioned but not confirmed" in unclear.first.inner_text()
    same_amber = page.evaluate(
        """() => { const a = document.querySelector('#stage .unclear-line');
                   const t = document.createElement('span'); t.style.color = 'var(--amber)'; document.body.appendChild(t);
                   const r = getComputedStyle(a).color === getComputedStyle(t).color; t.remove(); return r; }"""
    )
    assert same_amber
    assert "Proceed only after confirming" in page.inner_text("#stage .verdict-block")


def test_dashboard_simulate_email_names_the_full_council_not_a_subset(page):
    page.click("#sim")
    page.wait_for_selector("#emailcard.show")
    text = page.inner_text("#emailcard")
    assert "full council" in text
    assert "Delivery, PMO" not in text and "convening Delivery" not in text


def test_council_tab_blocker_rules_read_only_and_threshold_edit_reflected_in_next_run(page):
    page.click("[data-v='council']")
    page.wait_for_selector(".blockerrule")
    assert "system-governed" in page.inner_text("#view-council")
    assert page.locator(".blockerrule input").count() == 0
    assert page.locator(".blockerrule").count() >= 1

    page.fill("#cf-supplier", "50")
    page.click("[data-retest='finance']")
    page.wait_for_selector("#res-finance.show")
    assert "all clear" in page.inner_text("#res-finance").lower()

    _run_seed_in_ui(page)  # next run reflects the edit: finance no longer triggers on 15%
    assert "All rules checked" in page.locator("#lane-finance").inner_text()

    page.click("[data-v='council']")
    page.fill("#cf-supplier", "7")
    page.click("[data-retest='finance']")
    page.wait_for_selector("#res-finance.show")


def test_history_renders_old_and_new_entries_without_a_page_error(page, base_url):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    import json as _json

    req = urllib.request.Request(
        base_url + "/history", method="POST", headers={"Content-Type": "application/json"},
        data=_json.dumps({"label": "Pre-P3.6 run", "q": "old", "verdict": "Decline",
                          "positions": [{"agent": "finance", "stance": "no"}]}).encode(),
    )
    urllib.request.urlopen(req)
    page.reload()
    page.click("[data-v='history']")
    page.wait_for_selector("#hgrid .hrow")
    assert "Pre-P3.6 run" in page.inner_text("#hgrid")
    assert errors == []


def test_council_shows_the_backend_validation_error_for_a_rejected_rule_edit(page):
    page.click("[data-v='council']")
    page.locator("#rl-pmo .rin").first.fill("x" * 300)  # over the 240-char rule limit
    page.click("[data-save='pmo']")
    page.wait_for_selector("#res-pmo.show")
    text = page.inner_text("#res-pmo")
    assert "240" in text and "not saved" in text.lower()  # the backend's own reason, readable
    assert "saved to config" not in text.lower()  # never claims success on a rejection
    assert "value_error" not in text and "pydantic" not in text.lower()


def test_council_shows_the_backend_validation_error_for_a_rejected_threshold_edit(page):
    page.click("[data-v='council']")
    page.evaluate("document.getElementById('cf-margin').removeAttribute('min')")  # bypass the browser's own bound
    page.fill("#cf-margin", "-5")
    page.click("[data-retest='finance']")
    page.wait_for_selector("#res-finance.show")
    text = page.inner_text("#res-finance")
    assert "margin_erosion_threshold_pts" in text and "not saved" in text.lower()
    assert "all clear" not in text.lower() and "saved to config" not in text.lower()
