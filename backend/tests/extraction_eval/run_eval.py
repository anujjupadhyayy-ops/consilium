"""Extraction evaluation (P3.6 §6.10). Runs Operations' real per-agent
extraction (agents/base.py extract_facts) over tests/extraction_eval/
emails.json against whatever model is configured, and reports the
blocker-field hit rate and false-positive rate.

  hit rate            = expected-stated fields extracted with the right value
                        / expected-stated fields
  false-positive rate = fields extracted with a value that is wrong, or where
                        the expected answer is "not stated" / total fields
                        where expected is "not stated" or a value was extracted

Owner-run only:  cd backend && pytest -m live tests/extraction_eval
Expected answers in emails.json are UNCONFIRMED by the owner until
`expected_answers_confirmed_by_owner` is set true -- the report says so and
the result must not be recorded in the README until then.
"""
from __future__ import annotations

import json
from pathlib import Path

EMAILS = Path(__file__).parent / "emails.json"


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


def run() -> dict:
    from agents.registry import get_agent
    from model.config import ModelConfig

    data = json.loads(EMAILS.read_text())
    agent = get_agent(data["agent"])
    expected_stated = hits = 0
    fp_denominator = false_positives = 0
    per_category: dict[str, dict] = {}
    for email in data["emails"]:
        raw, _evidence = agent.extract_facts(email["text"])
        cat = per_category.setdefault(email["category"], {"hits": 0, "expected": 0, "false_positives": 0})
        for field, want in email["expected"].items():
            got = raw.get(field)
            if want is not None:
                expected_stated += 1
                cat["expected"] += 1
                if got is not None and _same(got, want):
                    hits += 1
                    cat["hits"] += 1
            if want is None or got is not None:
                fp_denominator += 1
            if got is not None and (want is None or not _same(got, want)):
                false_positives += 1
                cat["false_positives"] += 1
    cfg = ModelConfig.current()
    return {
        "model": f"{cfg.provider}/{cfg.model_name}",
        "emails": len(data["emails"]),
        "blocker_field_hit_rate": round(hits / expected_stated, 3) if expected_stated else None,
        "false_positive_rate": round(false_positives / fp_denominator, 3) if fp_denominator else None,
        "per_category": per_category,
        "expected_answers_confirmed_by_owner": data["expected_answers_confirmed_by_owner"],
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
