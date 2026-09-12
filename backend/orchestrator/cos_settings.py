"""Persisted Chief of Staff persona / routing-guidance (P3.6).

The adjudication policy (operational-blocker-wins) and guardrails
(recommend-only, bounded termination) stay code-controlled -- see
chief_of_staff.py's OPERATIONAL_BLOCKER_POLICY and _enforce_blocker_policy.
This file only holds the user-editable *framing* layered on top of the
routing/reconcile prompts: tone, prioritisation, what to escalate. Tracked
in git (no secrets) so a fork ships with a sensible default persona, same
treatment as agents/configs/*.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_PACKAGE_DIR = Path(__file__).parent
COS_SETTINGS_PATH = _PACKAGE_DIR / "cos_settings.json"

MAX_PERSONA_LENGTH = 2000


def read_cos_settings(path: Optional[Path] = None) -> dict:
    path = path or COS_SETTINGS_PATH
    return json.loads(path.read_text())


def write_cos_settings(persona: str, path: Optional[Path] = None) -> dict:
    persona = persona.strip()
    if not persona:
        raise ValueError("persona cannot be empty")
    if len(persona) > MAX_PERSONA_LENGTH:
        raise ValueError(f"persona exceeds {MAX_PERSONA_LENGTH} characters")
    payload = {"persona": persona}
    path = path or COS_SETTINGS_PATH
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
