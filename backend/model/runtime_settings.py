"""Server-side persistence for Settings' model config -- the "persists to
server-side env" behaviour the P3.5 spec asks for, implemented as a small
JSON file rather than rewriting .env from a running process (safer, and
survives a restart the same way env would). Never committed -- gitignored
alongside .env since it can hold an API key.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_PACKAGE_DIR = Path(__file__).parent
RUNTIME_SETTINGS_PATH = _PACKAGE_DIR / "runtime_settings.json"


def read_runtime_settings(path: Optional[Path] = None) -> dict:
    path = path or RUNTIME_SETTINGS_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_runtime_settings(data: dict, path: Optional[Path] = None) -> None:
    path = path or RUNTIME_SETTINGS_PATH
    path.write_text(json.dumps(data, indent=2))
