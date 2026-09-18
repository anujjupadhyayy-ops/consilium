"""Persisted Chief of Staff persona / wording guidance (P3.6).

The adjudication policy (operational-blocker-wins) and guardrails
(recommend-only, bounded termination) stay code-controlled -- see
chief_of_staff.py's OPERATIONAL_BLOCKER_POLICY and _enforce_blocker_policy.
This file only holds the user-editable *framing* layered on top of the
reconciliation prompt: tone, prioritisation, what to escalate (wording only). Tracked
in git (no secrets) so a fork ships with a sensible default persona, same
treatment as agents/configs/*.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from appdata import data_dir

_PACKAGE_DIR = Path(__file__).parent
# Git-tracked shipped default persona -- a fresh clone reads this until the
# user saves their own.
_PACKAGED_DEFAULT = _PACKAGE_DIR / "cos_settings.json"
# The user-writable copy lives outside the source tree (see appdata.data_dir)
# so a --reload dev server doesn't restart when the persona is saved.
COS_SETTINGS_PATH = data_dir() / "cos_settings.json"

MAX_PERSONA_LENGTH = 2000


def read_cos_settings(path: Optional[Path] = None) -> dict:
    path = path or COS_SETTINGS_PATH
    if path.exists():
        return json.loads(path.read_text())
    # Fresh clone / first run: fall back to the shipped default persona.
    if _PACKAGED_DEFAULT.exists():
        return json.loads(_PACKAGED_DEFAULT.read_text())
    return {"persona": ""}


def write_cos_settings(persona: str, path: Optional[Path] = None) -> dict:
    persona = persona.strip()
    if not persona:
        raise ValueError("persona cannot be empty")
    if len(persona) > MAX_PERSONA_LENGTH:
        raise ValueError(f"persona exceeds {MAX_PERSONA_LENGTH} characters")
    payload = {"persona": persona}
    path = path or COS_SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
