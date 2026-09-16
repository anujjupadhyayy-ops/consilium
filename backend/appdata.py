"""Per-user writable data directory.

Runtime settings, the Chief of Staff persona, and the audit ledger are all
written here -- deliberately OUTSIDE the source tree. When the app persisted
into its own package directory (as it first did), running the dev server with
``uvicorn --reload`` restarted the process on every save and killed the
in-flight request (a "Save & test connection" would report the server as
unreachable). Keeping writable state here makes --reload safe and means a
fresh clone needs no assumptions about a writable package directory.

Location: ``$CONSILIUM_DATA_DIR`` if set, else ``~/.consilium``.
"""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("CONSILIUM_DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / ".consilium"
