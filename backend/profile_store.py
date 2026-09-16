"""User profile (display name + role) persisted outside the source tree.

Ships generic -- no real person's name baked in -- so a fork is usable as-is.
The name is user-set via Settings -> Edit profile and drives the header avatar,
greeting, profile card and footer.
"""
from __future__ import annotations

import json
from typing import Optional

from appdata import data_dir

_DEFAULT = {
    "name": "",
    "role": "Owner · configures the council and the Chief of Staff's briefing preferences",
}
MAX_NAME_LENGTH = 80
MAX_ROLE_LENGTH = 160


def _path():
    return data_dir() / "profile.json"


def read_profile() -> dict:
    p = _path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return {"name": data.get("name", ""), "role": data.get("role", _DEFAULT["role"])}
        except (json.JSONDecodeError, OSError):
            return dict(_DEFAULT)
    return dict(_DEFAULT)


def write_profile(name: str, role: Optional[str] = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("name cannot be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"name exceeds {MAX_NAME_LENGTH} characters")
    role = (role or _DEFAULT["role"]).strip()
    if len(role) > MAX_ROLE_LENGTH:
        raise ValueError(f"role exceeds {MAX_ROLE_LENGTH} characters")
    payload = {"name": name, "role": role}
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
