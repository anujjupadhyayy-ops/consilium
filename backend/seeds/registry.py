"""Seed registry for the P3 UI's seed picker.

Only "supplier_milestone" has structured facts and runs end-to-end (P1/P2
scope). The other three seeds from the original design notes are listed as `available: False`
placeholders -- same honest "coming soon" treatment the P3 plan already
prescribes for free-text input, rather than inventing facts for scenarios
P2's agent logic was never designed/tested against.
"""
from __future__ import annotations

from typing import Optional

from .supplier_milestone import SUPPLIER_MILESTONE_SEED

SEEDS = [
    {**SUPPLIER_MILESTONE_SEED, "available": True},
    {
        "id": "budget_overrun",
        "title": "Budget overrun",
        "scenario": "A workstream is trending 12% over its 3PP budget mid-year -- absorb, re-baseline, or cut scope?",
        "why_multi_function": "Coming in a future build session.",
        "available": False,
    },
    {
        "id": "resourcing_clash",
        "title": "Resourcing clash",
        "scenario": "Two programmes need the same scarce specialist in the same sprint -- who wins, and what's the cost of the loser slipping?",
        "why_multi_function": "Coming in a future build session.",
        "available": False,
    },
    {
        "id": "project_pme_compliance",
        "title": "Project PME compliance",
        "scenario": "A project is flagged non-compliant against the PME standard -- what must change, who owns it, and what's the delivery/cost/operational impact of fixing vs the risk of not.",
        "why_multi_function": "Coming in a future build session.",
        "available": False,
    },
]


def list_seeds() -> list[dict]:
    """Summaries only -- omits `facts`, which the frontend never needs."""
    return [{k: v for k, v in seed.items() if k != "facts"} for seed in SEEDS]


def get_seed(seed_id: str) -> Optional[dict]:
    return next((seed for seed in SEEDS if seed["id"] == seed_id), None)
