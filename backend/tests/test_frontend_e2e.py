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
    page.wait_for_selector("#resw-pmo.show")
    # still editable after a save -- the reported bug
    rule2 = page.locator("#rl-pmo .rin").first
    rule2.fill("Escalate contract variations above tolerance to the governance gate.")
    page.click("[data-save='pmo']")
    page.wait_for_selector("#resw-pmo:has-text('saved')")


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
    page.wait_for_selector("#resw-pmo.show")
    text = page.inner_text("#resw-pmo")
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


# ---------------------- verdict panel structure, list rendering, human labels --

import re as _re

_RAW = _re.compile(r"[a-z0-9]+_[a-z0-9_]+|\b(finance|delivery|pmo|operations)\.[a-z]")


def _free_text_run_in_ui(page, text):
    page.click("[data-v='decision']")
    page.fill("#q", text)
    page.click("#run")
    page.wait_for_selector("#stage .verdict-block.show", timeout=20000)
    page.wait_for_function("!document.getElementById('run').disabled", timeout=20000)


def test_three_assumptions_render_as_three_separate_items(page, base_url):
    events = _real_stream_events(base_url, "seed_id=supplier_milestone")
    for i, (kind, data) in enumerate(events):
        if kind == "trace" and data["kind"] == "reconciliation":
            data["payload"]["assumptions"] = ["First assumption.", "Second assumption.", "Third assumption."]
            data["payload"]["not_considered"] = ["Alpha.", "Beta."]
    page.route("**/run/stream*", lambda route: route.fulfill(
        status=200, content_type="text/event-stream", body=_sse_body(events)))
    _run_seed_in_ui(page)
    items = page.locator("#stage .verdict-block .assumptions li")
    assert items.count() == 3
    assert [items.nth(i).inner_text() for i in range(3)] == ["First assumption.", "Second assumption.", "Third assumption."]
    assert page.locator("#stage .verdict-block .notconsidered li").count() == 2
    page.unroute("**/run/stream*")


def test_no_raw_field_name_appears_in_user_facing_text(page):
    """Checked on the seed run, a nothing-stated run and a licence-mentioned-
    but-unconfirmed run: the stage (lanes + verdict panel) may show human
    labels only -- no `snake_case` identifier and no `agent.field`. (The
    developer inspector, a collapsed <details>, deliberately shows the raw
    trace and is outside this check.)"""
    _run_seed_in_ui(page)
    seed_text = page.inner_text("#stage")
    _free_text_run_in_ui(page, "Please advise on this vague request; no figures are given at all.")
    vague_text = page.inner_text("#stage")
    _free_text_run_in_ui(page, "We are still checking whether the licence will be ready for the earlier date.")
    unclear_text = page.inner_text("#stage")
    for name, text in (("seed", seed_text), ("vague", vague_text), ("unclear", unclear_text)):
        assert not _RAW.search(text), f"{name}: raw name leaked: {_RAW.search(text).group(0)!r}"
    assert "licence provisioned for the new date" in unclear_text.lower()
    assert "supplier cost increase (%)" in vague_text.lower()


def test_verdict_panel_headline_is_the_recommendation_only_and_facts_move_to_their_own_block(page):
    _free_text_run_in_ui(page, "We are still checking whether the licence will be ready for the earlier date.")
    panel = page.locator("#stage .verdict-block")
    headline = panel.locator(".rec").inner_text()
    assert headline == "Proceed only after confirming the blocker-related facts listed below."
    assert "licence" not in headline.lower()

    # DOM order: headline, then the not-checked block, then WHY / KEY TRADE-OFF / ASSUMPTIONS / NOT CONSIDERED
    order = panel.evaluate("""el => [...el.querySelectorAll('.rec, .notchecked, .kv')].map(n => n.className.split(' ')[0])""")
    assert order == ["rec", "notchecked", "kv"]
    assert panel.locator(".notchecked h4").inner_text().lower() == "could stop this — not stated in the brief"
    labels = [t.lower() for t in panel.locator(".kv dt").all_inner_texts()]
    assert labels == ["why", "key trade-off", "assumptions", "not considered"]

    # the confirm-first line leads the block (first thing after its heading)
    first_after_heading = panel.locator(".notchecked").evaluate("el => el.children[1].className")
    assert "confirmfirst" in first_after_heading
    assert "licence provisioned for the new date" in panel.locator(".confirmfirst").inner_text()
    assert "Operations" in panel.locator(".confirmfirst").inner_text()

    # only the agent that owns blocker rules is listed, named once as a group heading
    agents = panel.locator(".ncgroup .an").all_inner_texts()
    assert agents == ["Operations"]
    ops_items = panel.locator(".ncgroup").first.locator("li").all_inner_texts()
    assert ops_items[0].lower().startswith("licence provisioned for the new date")  # unclear one first
    assert "mentioned, not confirmed" in ops_items[0].lower()
    # no per-item "blocker-related" tag, and the marker is separated from its label by a space
    assert "blocker-related" not in panel.locator(".notchecked").inner_text().lower()  # (the headline sentence may say it)
    assert "(%)mentioned" not in panel.locator(".notchecked").inner_text().lower()
    assert "date mentioned, not confirmed" in ops_items[0].lower()


def test_not_checked_block_without_an_unclear_blocker_fact_has_no_confirm_first_line(page):
    _free_text_run_in_ui(page, "Please advise on this vague request; no figures are given at all.")
    panel = page.locator("#stage .verdict-block")
    assert panel.locator(".notchecked").count() == 1
    assert panel.locator(".confirmfirst").count() == 0
    assert panel.locator(".rec").inner_text() == "No rule triggered on stated facts."


def test_fully_stated_seed_has_no_not_checked_block(page):
    _run_seed_in_ui(page)
    assert page.locator("#stage .verdict-block .notchecked").count() == 0
    assert page.locator("#stage .verdict-block .rec").inner_text().startswith("Decline as currently scoped")


# ------------------------ verdict panel: blocker facts only, collapse, cap --

_BLOCKER_LABELS = {
    "capacity utilisation if accepted (%)", "third-party spend (% of budget)", "savings delivered vs committed (ratio)",
    "licence provisioned for the new date", "supplier SLA in place",
}
_NON_BLOCKER_SAMPLE = [
    "supplier cost increase (%)", "project margin erosion (points)", "milestone is resourced",
    "the change is a contract variation", "reported RAG status after the change",
]


def test_verdict_panel_lists_only_blocker_related_facts_and_names_the_other_agents(page):
    _free_text_run_in_ui(page, "A 3rd-party supplier offers to pull a delivery milestone forward 3 weeks for a 15% cost increase and a contract variation.")
    panel = page.locator("#stage .verdict-block")
    listed = [t.split(" mentioned, not confirmed")[0].strip().lower() for t in panel.locator(".notchecked li").all_inner_texts()]
    assert listed and set(listed) <= {l.lower() for l in _BLOCKER_LABELS}
    panel_text = panel.inner_text().lower()
    for label in _NON_BLOCKER_SAMPLE:
        assert label.lower() not in panel_text, f"non-blocker fact leaked into the verdict panel: {label}"
    assert panel.locator(".notchecked .an").all_inner_texts() == ["Operations"]  # agent named once
    assert (
        "Finance, Delivery and PMO also needed facts the brief doesn't state — see their cards."
        in panel.locator(".othernote").inner_text()
    )
    # ...while the agent cards keep their full lists
    assert "supplier cost increase (%)" in page.locator("#lane-finance").inner_text().lower()
    assert "milestone is resourced" in page.locator("#lane-delivery").inner_text().lower()


def test_verdict_panel_has_no_raw_field_names_and_lists_render_as_items(page):
    _free_text_run_in_ui(page, "We are still checking whether the licence will be ready for the earlier date.")
    panel = page.locator("#stage .verdict-block")
    assert not _RAW.search(panel.inner_text())
    assert panel.locator(".notchecked li").count() >= 1
    assert panel.locator(".assumptions li").count() >= 1 and panel.locator(".notconsidered li").count() >= 1


def _stream_with_not_checked(base_url, not_checked, mutate_checks=None):
    events = _real_stream_events(base_url, "seed_id=supplier_milestone")
    for kind, data in events:
        if kind == "trace" and data["kind"] == "reconciliation":
            data["payload"]["not_checked"] = not_checked
    return events


def _item(label, unclear=False, blocker=True):
    return {"field": label.replace(" ", "_"), "label": label, "blocker": blocker, "unclear": unclear}


def test_more_than_six_blocker_facts_shows_six_plus_n_more_biggest_agent_first(page, base_url):
    nc = {
        "confirm_first": [],
        "groups": [
            {"agent": "finance", "items": [_item("finance fact one"), _item("finance fact two")]},
            {"agent": "operations", "items": [_item(f"operations fact {n}") for n in range(1, 7)]},
        ],
    }
    events = _stream_with_not_checked(base_url, nc)
    page.route("**/run/stream*", lambda route: route.fulfill(
        status=200, content_type="text/event-stream", body=_sse_body(events)))
    _run_seed_in_ui(page)
    panel = page.locator("#stage .verdict-block")
    assert panel.locator(".notchecked li").count() == 6
    assert panel.locator(".ncmore").inner_text() == "+2 more"
    assert panel.locator(".notchecked .an").all_inner_texts() == ["Operations"]  # 6 fill the cap; Finance's fall under "+2 more"
    page.unroute("**/run/stream*")


def test_cap_spills_into_the_next_agent_and_orders_by_most_at_risk(page, base_url):
    nc = {
        "confirm_first": [],
        "groups": [
            {"agent": "finance", "items": [_item("finance fact one"), _item("finance fact two")]},
            {"agent": "operations", "items": [_item(f"operations fact {n}") for n in range(1, 6)]},
        ],
    }
    events = _stream_with_not_checked(base_url, nc)
    page.route("**/run/stream*", lambda route: route.fulfill(
        status=200, content_type="text/event-stream", body=_sse_body(events)))
    _run_seed_in_ui(page)
    panel = page.locator("#stage .verdict-block")
    assert panel.locator(".notchecked .an").all_inner_texts() == ["Operations", "Finance"]  # most facts at risk first
    assert panel.locator(".notchecked li").count() == 6
    assert panel.locator(".ncmore").inner_text() == "+1 more"
    page.unroute("**/run/stream*")


def test_single_other_agent_sentence_and_no_block_when_no_blocker_fact_is_unchecked(page, base_url):
    nc = {"confirm_first": [], "groups": [{"agent": "finance", "items": [_item("supplier cost increase (%)", blocker=False)]}]}
    events = _stream_with_not_checked(base_url, nc)
    page.route("**/run/stream*", lambda route: route.fulfill(
        status=200, content_type="text/event-stream", body=_sse_body(events)))
    _run_seed_in_ui(page)
    panel = page.locator("#stage .verdict-block")
    assert panel.locator(".notchecked").count() == 0  # nothing that could stop it -> no block
    assert panel.locator(".othernote").inner_text() == "Finance also needed facts the brief doesn't state — see its card."
    assert "supplier cost increase" not in panel.locator(".othernote").inner_text().lower()  # named by agent only, never by fact
    page.unroute("**/run/stream*")


# ------------------- Council: real rule editing, wording box kept honest --

def _council_finance(page):
    page.click("[data-v='council']")
    page.wait_for_selector("#xr-finance .xrule")


def _rules_of(base_url, agent):
    import json as _json

    with urllib.request.urlopen(f"{base_url}/agents/{agent}/rules") as r:
        return _json.loads(r.read())["rules"]


def _rule_descriptions(page, agent):
    """The editable descriptions on a card (they live in inputs, so not in inner_text)."""
    return page.eval_on_selector_all(f"#xr-{agent} .rlabel", "els => els.map(e => e.value)")


def _save_rules(page, agent):
    page.click(f"[data-retest='{agent}']")
    page.wait_for_selector(f"#res-{agent}.show")
    return page.inner_text(f"#res-{agent}")


def _restore_finance(page):
    """These tests share one live server; leave Finance exactly as shipped."""
    page.reload()
    _council_finance(page)
    for row in page.locator("#xr-finance .rdel").all():
        row.click()
    page.fill("#cf-supplier", "7")
    page.locator("#xr-finance .xrule:has(#cf-supplier) .rstance").select_option("no")
    page.click("[data-retest='finance']")
    page.wait_for_selector("#res-finance.show")


def test_council_rules_read_in_plain_english_no_raw_names_or_placeholders(page):
    import re

    page.click("[data-v='council']")
    page.wait_for_selector(".xrule")
    page.locator(".addbox summary").first.click()
    shown = page.inner_text("#view-council")
    # what a person sees -- an option's visible text, not its hidden value
    shown += " ".join(page.eval_on_selector_all(
        "#view-council input, #view-council option", "els => els.map(e => e.tagName === 'OPTION' ? e.textContent : e.value)"))
    assert not re.search(r"\b[a-z]+_[a-z_]+\b", shown), re.findall(r"\b[a-z]+_[a-z_]+\b", shown)   # no raw field names
    assert not re.search(r"[{}\u2039\u203a]|<[a-z ]+>", shown)                                            # no {template} / <placeholder>
    for junk in ("undefined", "NaN", "[object"):
        assert junk not in shown
    assert "Supplier cost increase (%) is above 7%" in shown        # a condition, in words, with its value
    assert "Licence provisioned for the new date: no" in shown


def test_blocker_rules_render_read_only_with_no_edit_controls_but_an_editable_threshold(page):
    page.click("[data-v='council']")
    page.wait_for_selector(".blockerrule")
    blockers = page.locator(".xrule:has(.blockerrule)")
    assert blockers.count() == 5                                   # Operations' five blockers
    for i in range(blockers.count()):
        row = blockers.nth(i)
        assert row.locator(".blockerrule input, .blockerrule select, .blockerrule button, .blockerrule textarea").count() == 0
        assert row.locator(".rlabel, .rstance, .rdel").count() == 0     # no edit, restance or delete control
        assert "system-governed" in row.inner_text().lower() and "blocker" in row.inner_text().lower()
    # the threshold of a threshold-driven blocker is still editable
    assert page.locator("#xr-operations .xrule:has(.blockerrule) input[data-tkey]").count() == 3


def test_editing_a_finance_rule_so_it_triggers_on_the_15pct_supplier_uplift(page):
    try:
        _council_finance(page)
        page.fill("#cf-supplier", "50")                             # relax it: 15% no longer trips
        assert "saved" in _save_rules(page, "finance").lower()
        _run_seed_in_ui(page)
        assert "All rules checked" in page.locator("#lane-finance").inner_text()

        _council_finance(page)                                      # now edit the rule: line 10%, softer stance
        page.locator("#xr-finance .xrule:has(#cf-supplier) .rstance").select_option("conditional")
        page.fill("#cf-supplier", "10")
        result = _save_rules(page, "finance")
        assert "Saved. The next Decision-desk run checks with these rules" in result and "conditional" in result.lower()
        _run_seed_in_ui(page)
        lane = page.locator("#lane-finance").inner_text()
        assert "All rules checked" not in lane and "conditional" in lane.lower()   # Finance now triggers, at the edited stance
    finally:
        _restore_finance(page)


def test_adding_a_rule_through_the_form_persists_and_fires_in_the_next_run(page, base_url):
    try:
        _council_finance(page)
        page.fill("#cf-supplier", "50")                             # so only the new rule can trip Finance
        page.locator("#ab-finance summary").click()
        page.select_option("#af-field-finance", label="Supplier cost increase (%)")
        page.select_option("#af-op-finance", value=">")
        page.fill("#af-value-finance", "12")
        page.select_option("#af-stance-finance", "conditional")
        page.fill("#af-label-finance", "Fee uplift above twelve per cent")
        page.click("[data-addgo='finance']")
        assert "new · unsaved" in page.inner_text("#xr-finance").lower()
        assert not any(r["user_added"] for r in _rules_of(base_url, "finance"))   # not saved until Save
        assert "Saved." in _save_rules(page, "finance")
        assert any(r["label"] == "Fee uplift above twelve per cent" for r in _rules_of(base_url, "finance"))

        page.reload()                                               # survives a reload: it came from the backend
        _council_finance(page)
        assert "Supplier cost increase (%) is above 12" in page.inner_text("#xr-finance")

        _run_seed_in_ui(page)
        lane = page.locator("#lane-finance").inner_text()
        assert "Fee uplift above twelve per cent" in lane and "conditional" in lane.lower()
    finally:
        _restore_finance(page)


def test_only_rules_you_added_can_be_deleted(page, base_url):
    try:
        _council_finance(page)
        assert page.locator("#xr-finance .rdel").count() == 0            # shipped rules: no delete control
        page.locator("#ab-finance summary").click()
        page.fill("#af-value-finance", "3")
        page.fill("#af-label-finance", "Mine")
        page.click("[data-addgo='finance']")
        assert page.locator("#xr-finance .rdel").count() == 1
        _save_rules(page, "finance")
        assert any(r["user_added"] for r in _rules_of(base_url, "finance"))
        page.locator("#xr-finance .rdel").click()
        _save_rules(page, "finance")
        assert not any(r["user_added"] for r in _rules_of(base_url, "finance"))
        assert len(_rules_of(base_url, "finance")) == 4
    finally:
        _restore_finance(page)


def test_invalid_input_shows_the_backends_reason_and_does_not_save(page, base_url):
    try:
        before = _rules_of(base_url, "finance")
        _council_finance(page)
        page.locator("#ab-finance summary").click()
        page.select_option("#af-field-finance", label="Financial-year month the forecast is read in")
        page.fill("#af-value-finance", "99")                        # a month can't be 99
        page.fill("#af-label-finance", "Impossible month")
        page.click("[data-addgo='finance']")
        text = _save_rules(page, "finance")
        assert "not saved" in text.lower() and "out of range" in text and "between 1 and 12" in text
        assert "Saved." not in text and "checks with these rules" not in text     # never claims a save
        assert _rules_of(base_url, "finance") == before
        assert "Impossible month" in _rule_descriptions(page, "finance")          # the draft stays so it can be fixed
        page.reload()
        _council_finance(page)
        assert "Impossible month" not in _rule_descriptions(page, "finance")      # and it really wasn't stored
    finally:
        _restore_finance(page)


def test_a_rejected_threshold_on_a_rule_row_is_not_saved(page, base_url):
    try:
        _council_finance(page)
        page.evaluate("document.getElementById('cf-supplier').removeAttribute('min')")
        page.fill("#cf-supplier", "-3")
        text = _save_rules(page, "finance")
        assert "not saved" in text.lower() and "Saved." not in text
        assert next(r for r in _rules_of(base_url, "finance") if r["id"] == "supplier_cost_high")["threshold"]["value"] == 7
    finally:
        _restore_finance(page)


def test_changing_a_rule_changes_the_verdict_you_get_for_the_same_decision(page):
    try:
        _run_seed_in_ui(page)
        before = page.inner_text("#stage .verdict-block")
        assert "supplier cost increase" in before.lower()            # Finance's 15% objection is in the verdict

        _council_finance(page)
        page.fill("#cf-supplier", "50")
        _save_rules(page, "finance")
        _run_seed_in_ui(page)                                        # same decision, re-run
        after = page.inner_text("#stage .verdict-block")
        assert after != before and "supplier cost increase" not in after.lower()   # the objection is gone from the verdict
    finally:
        _restore_finance(page)


def test_council_wording_box_is_labelled_narration_only_and_messages_match(page):
    page.click("[data-v='council']")
    page.wait_for_selector("#rl-pmo .rin")
    body = page.inner_text("#view-council").lower()
    assert "narration wording" in body
    assert "never changes whether the agent triggers" in body
    assert "rules — edit, add or remove" not in body            # the old, false label

    page.locator("#rl-pmo .rin").first.fill("Escalate variations above tolerance to the governance gate.")
    page.click("[data-save='pmo']")
    page.wait_for_selector("#resw-pmo.show")
    saved = page.inner_text("#resw-pmo").lower()
    assert "wording" in saved and "not whether it triggers" in saved
    assert "checks with these rules" not in saved               # a wording save never claims changed reasoning


def test_editing_wording_never_changes_the_executable_rules(page, base_url):
    before = _rules_of(base_url, "pmo")
    page.click("[data-v='council']")
    page.wait_for_selector("#rl-pmo .rin")
    page.locator("#rl-pmo .rin").first.fill("Reworded note that must not touch the rules.")
    page.click("[data-save='pmo']")
    page.wait_for_selector("#resw-pmo.show")
    assert _rules_of(base_url, "pmo") == before


def test_saving_with_no_changes_says_nothing_was_saved(page):
    _council_finance(page)
    text = _save_rules(page, "finance")
    assert "nothing was saved" in text.lower() and "checks with these rules" not in text


# ------------- the Council tab must degrade, never go blank ---------------

def test_council_still_renders_when_the_rules_endpoint_is_unavailable(page):
    """Regression: a backend that predates /agents/{id}/rules (e.g. an app
    started before an upgrade and never restarted) 404s it. The whole Council
    tab used to render nothing -- not even the Chief of Staff card."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/agents/*/rules", lambda route: route.fulfill(status=404, content_type="application/json",
                                                              body='{"detail":"Not Found"}'))
    page.reload()
    page.click("[data-v='council']")
    page.wait_for_selector(".ccard")
    text = page.inner_text("#view-council")
    assert page.locator(".mastercard").count() == 1                       # Chief of Staff card is there
    assert page.locator(".ccard").count() == 4                            # so are all four specialists
    assert page.locator(".rulelist .rin").count() > 0                     # and their narration wording
    assert "couldn't load" in text.lower() and "restart" in text.lower()  # with a visible, actionable reason
    assert page.locator("[data-retest]").count() == 0                     # no save button that can't work
    assert errors == []
