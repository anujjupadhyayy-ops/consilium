"""Persisted decision-run history, kept outside the source tree so it survives
a page reload (the earlier UI held runs only in browser memory and lost them
on refresh). Capped to the most recent runs -- this is a demo desk, not an
archive.
"""
from __future__ import annotations

import json
from typing import Optional

from appdata import data_dir

MAX_RUNS = 50


def _path():
    return data_dir() / "run_history.json"


def read_runs(limit: int = MAX_RUNS) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        runs = json.loads(p.read_text())
        return runs[:limit] if isinstance(runs, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def append_run(entry: dict) -> list[dict]:
    """Prepend a completed run (newest first) and cap the list."""
    runs = read_runs(MAX_RUNS)
    runs.insert(0, entry)
    runs = runs[:MAX_RUNS]
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(runs, indent=2))
    return runs
