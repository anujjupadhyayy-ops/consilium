"""P3.6 §6.10. The fixture-shape test runs in the normal suite; the measured
run is `live` (owner-run) and never asserts a number -- it prints the
report; the owner confirms the expected answers before any result counts."""
import json
from pathlib import Path

import pytest

DATA = json.loads((Path(__file__).parent / "emails.json").read_text())


def test_fixture_is_well_formed_and_flagged_unconfirmed():
    emails = DATA["emails"]
    assert 20 <= len(emails) <= 30
    assert {"stated", "negated", "implied", "split", "absent"} <= {e["category"] for e in emails}
    assert DATA["expected_answers_confirmed_by_owner"] is False
    from agents.operations import OperationsFacts

    fields = set(OperationsFacts.model_fields)
    for e in emails:
        assert set(e["expected"]) == fields
        if e["category"] in ("implied", "absent"):
            assert all(v is None for v in e["expected"].values())


@pytest.mark.live
def test_measured_extraction_run_prints_the_report():
    from tests.extraction_eval.run_eval import run

    report = run()
    print(json.dumps(report, indent=2))
    assert report["emails"] == len(DATA["emails"])
