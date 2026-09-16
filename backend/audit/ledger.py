"""Tamper-evident, append-only audit ledger for trigger events.

Every inbound trigger (webhook or simulated email) is recorded here before
anything is convened -- including *rejected* attempts -- so the record of
"what asked the council to convene, and what we did about it" is complete
and independently checkable.

Why a hash chain, not just a log file: each entry stores the hash of the
previous entry (`prev_hash`) and a hash of its own contents (`entry_hash`).
Editing or deleting any past entry breaks every hash after it, so
`verify_chain()` can prove the log hasn't been altered since it was written.
This is a recommend-only system -- the ledger is the evidence trail a
reviewer (or a real audit) would ask for, not a control surface.

The log lives outside git (see .gitignore) since it holds inbound content;
a fork starts with an empty, valid chain.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

GENESIS_HASH = "0" * 64
from appdata import data_dir
_WRITE_LOCK = threading.Lock()


def _log_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get("CONSILIUM_AUDIT_LOG") or (data_dir() / "trigger_audit.jsonl"))


def _canonical(entry: dict) -> str:
    """Stable serialisation for hashing -- the entry WITHOUT its own
    entry_hash, keys sorted, no incidental whitespace, so the digest is
    reproducible on any machine and by any verifier."""
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(entry: dict) -> str:
    return hashlib.sha256(_canonical(entry).encode("utf-8")).hexdigest()


def _tail_state(path: Path) -> tuple[int, str]:
    """One pass over the log -> (next_seq, last_entry_hash). Cheap for the
    demo-scale volumes this sees; swap for an index if it ever grows."""
    if not path.exists():
        return 0, GENESIS_HASH
    count, last_hash = 0, GENESIS_HASH
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            count += 1
            last_hash = json.loads(line)["entry_hash"]
    return count, last_hash


def record(event: dict, path: Optional[Path] = None) -> dict:
    """Append one event to the chain and return the stored entry (with its
    seq, timestamp and hashes). Thread-safe; creates the file on first use."""
    path = _log_path(path)
    with _WRITE_LOCK:
        seq, prev_hash = _tail_state(path)
        entry = {
            "seq": seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "prev_hash": prev_hash,
            **event,
        }
        entry["entry_hash"] = _hash(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_entries(
    limit: int = 100,
    before_seq: Optional[int] = None,
    path: Optional[Path] = None,
) -> list[dict]:
    """Newest-first page of the ledger. `before_seq` pages backwards for the
    UI; `limit` caps the page."""
    path = _log_path(path)
    if not path.exists():
        return []
    entries: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    entries.sort(key=lambda e: e["seq"], reverse=True)
    if before_seq is not None:
        entries = [e for e in entries if e["seq"] < before_seq]
    return entries[: max(0, limit)]


def verify_chain(path: Optional[Path] = None) -> dict:
    """Independently recompute the chain and report whether it is intact.
    `ok` is false with `broken_at`/`reason` set the moment any entry's own
    hash or its link to the previous entry fails to reproduce -- i.e. the
    log was edited, reordered, or truncated after the fact."""
    path = _log_path(path)
    if not path.exists():
        return {"ok": True, "entries": 0, "broken_at": None, "reason": "empty ledger"}

    prev_hash = GENESIS_HASH
    count = 0
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return {"ok": False, "entries": count, "broken_at": count,
                        "reason": f"line {lineno + 1} is not valid JSON"}

            if entry.get("seq") != count:
                return {"ok": False, "entries": count, "broken_at": count,
                        "reason": f"seq out of order at position {count} (got {entry.get('seq')})"}
            if entry.get("prev_hash") != prev_hash:
                return {"ok": False, "entries": count, "broken_at": entry.get("seq"),
                        "reason": f"entry {entry.get('seq')} does not link to the previous entry"}
            if _hash(entry) != entry.get("entry_hash"):
                return {"ok": False, "entries": count, "broken_at": entry.get("seq"),
                        "reason": f"entry {entry.get('seq')} contents were altered after writing"}

            prev_hash = entry["entry_hash"]
            count += 1

    return {"ok": True, "entries": count, "broken_at": None, "reason": "chain intact"}
