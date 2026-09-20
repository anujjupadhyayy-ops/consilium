# --- Never touch the real per-user data directory ------------------------------
# The app keeps its writable state (model settings -- which can hold an API key --
# the Chief of Staff persona, run history, the profile, the audit ledger) in
# $CONSILIUM_DATA_DIR, default ~/.consilium. Two of those paths
# (model.runtime_settings.RUNTIME_SETTINGS_PATH, orchestrator.cos_settings.
# COS_SETTINGS_PATH) are computed ONCE, when their module is first imported, so a
# test that sets CONSILIUM_DATA_DIR afterwards does not redirect them -- and the
# suite silently overwrote a developer's real saved API key with a test dummy.
# So: before anything from the app is imported, point the data directory at a
# throwaway one (overriding whatever the developer has set), and guard below.
import os
import tempfile

os.environ["CONSILIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="consilium_test_data_")

import pytest

# --- Hermetic agent configs ----------------------------------------------------
# The app persists Council edits straight into backend/agents/configs/*.json, so
# a developer who has used the Council tab has a locally-modified copy there. The
# suite must test the SHIPPED configs, not whatever is on someone's disk: at
# collection time (before any test module binds the registry's paths) point the
# registry at a snapshot of the committed files -- `git show HEAD:<file>`, falling
# back to the working tree when git isn't available (e.g. an unpacked archive,
# where the working tree IS the shipped copy).
import subprocess
import tempfile
from pathlib import Path

from agents import registry as _registry


def _snapshot_shipped_configs() -> None:
    repo = Path(__file__).resolve().parents[2]
    dest = Path(tempfile.mkdtemp(prefix="consilium_shipped_configs_"))

    def shipped_bytes(path: Path) -> bytes:
        try:
            rel = path.resolve().relative_to(repo).as_posix()
            return subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{rel}"], stderr=subprocess.DEVNULL)
        except Exception:
            return path.read_bytes()

    configs = dest / "configs"
    configs.mkdir()
    for f in Path(_registry.DEFAULT_CONFIGS_DIR).glob("*.json"):
        (configs / f.name).write_bytes(shipped_bytes(f))
    manifest = dest / "manifest.json"
    manifest.write_bytes(shipped_bytes(Path(_registry.DEFAULT_MANIFEST_PATH)))
    _registry.DEFAULT_CONFIGS_DIR = configs
    _registry.DEFAULT_MANIFEST_PATH = manifest


_snapshot_shipped_configs()


@pytest.fixture(autouse=True)
def _blank_real_credentials(monkeypatch):
    """Never let a test accidentally talk to a real model or LangSmith endpoint."""
    for var in ("API_KEY", "LANGCHAIN_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture(autouse=True)
def _mock_llm_unavailable_by_default(monkeypatch):
    """P3.5: agents' extraction/narration and reconcile all call model.llm.call_structured.
    Every test gets a fast, deterministic run by default -- the model is
    "unavailable", which exercises the same graceful-fallback path a real
    outage would (engage everyone; deterministic reconcile). Tests that
    want to verify genuine LLM-driven behaviour (a subset selected, the
    blocker policy enforced against a misbehaving model, ...) override
    this explicitly with their own monkeypatch -- see test_chief_of_staff.py.
    """
    from model.llm import LLMUnavailableError

    def _raise(*args, **kwargs):
        raise LLMUnavailableError("mocked: no model in tests by default")

    monkeypatch.setattr("model.llm.call_structured", _raise)


@pytest.fixture
def seed_input() -> str:
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    return SUPPLIER_MILESTONE_SEED["scenario"]


@pytest.fixture
def seed_facts() -> dict:
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    return SUPPLIER_MILESTONE_SEED["facts"]


@pytest.fixture
def built_graph():
    from orchestrator.graph import build_graph

    return build_graph()


@pytest.fixture(autouse=True)
def _isolated_settings_files(tmp_path, monkeypatch):
    """Each test gets its own settings files, so nothing leaks between tests
    (and nothing can reach the real ~/.consilium even if the import-time
    paths above were ever computed before the override)."""
    from model import runtime_settings
    from orchestrator import cos_settings

    monkeypatch.setattr(runtime_settings, "RUNTIME_SETTINGS_PATH", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(cos_settings, "COS_SETTINGS_PATH", tmp_path / "cos_settings.json")


@pytest.fixture(autouse=True, scope="session")
def _test_suite_must_not_use_the_real_data_dir():
    """Fail the whole run loudly, before any test can write, if the suite is
    ever pointed at the real per-user data directory again."""
    from pathlib import Path

    from appdata import data_dir
    from model import runtime_settings
    from orchestrator import cos_settings

    real = (Path.home() / ".consilium").resolve()
    for label, path in (("data_dir()", data_dir()), ("RUNTIME_SETTINGS_PATH", runtime_settings.RUNTIME_SETTINGS_PATH),
                        ("COS_SETTINGS_PATH", cos_settings.COS_SETTINGS_PATH)):
        resolved = Path(path).resolve()
        assert resolved != real and real not in resolved.parents, (
            f"the test suite would write to the real data directory via {label}: {resolved}"
        )
