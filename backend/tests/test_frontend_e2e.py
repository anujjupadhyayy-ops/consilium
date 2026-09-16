"""Real browser end-to-end tests: a headless Chromium drives the actual served
UI against a live app, so wiring defects (a dead button, a fake 'Connected'
stub, history lost on reload) are caught -- the class of bug backend unit tests
structurally cannot see.

Skips cleanly if Playwright or its browser isn't installed (e.g. plain CI):
run `pip install playwright && playwright install chromium` to enable.
"""
import os
import socket
import threading
import time
import urllib.request

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402
import uvicorn  # noqa: E402


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
