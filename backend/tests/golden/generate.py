"""Golden baseline generator -- run against the CURRENT, unmigrated `evaluate()`
methods (P3.6-Rules-Trigger-Spec.md §5.3 step 1), before any rules-engine logic
exists. Produces:

  tests/golden/seed_supplier_milestone.json   -- every agent's stance + driving
                                                  constraint on the seed's facts.
  tests/golden/factsets_<agent>.json          -- >=200 generated COMPLETE fact
                                                  sets per agent (threshold edges,
                                                  boolean/enum combinations, and
                                                  random padding), each with the
                                                  current evaluate()'s output.

Re-run this only to regenerate the golden files from a still-unmigrated
`evaluate()` -- never after an agent has been migrated to rules, since the
migrated code is no longer a valid oracle (spec §5.3.5).

Usage: python tests/golden/generate.py   (from backend/, with the venv active)
"""
from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/ on sys.path

from agents.delivery import DeliveryAgent, DeliveryConfig  # noqa: E402
from agents.finance import FinanceAgent, FinanceConfig  # noqa: E402
from agents.operations import OperationsAgent, OperationsConfig  # noqa: E402
from agents.pmo import PMOAgent, PMOConfig  # noqa: E402

OUT_DIR = Path(__file__).parent
RNG = random.Random(20260917)  # fixed seed -- reproducible golden files
MIN_SETS = 200


def _record(agent, facts: dict) -> dict:
    position = agent.evaluate(facts)
    return {
        "facts": facts,
        "stance": position["stance"],
        "driving_constraint": position["driving_constraint"],
    }


def _sweep(center: float, eps: float) -> list[float]:
    return [round(center - eps, 6), center, round(center + eps, 6)]


def _dedupe(records: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in records:
        key = json.dumps(r["facts"], sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# --------------------------------------------------------------------- finance --

def finance_factsets() -> list[dict]:
    agent = FinanceAgent(agent_id="finance", config=FinanceConfig(lens="test", rules_summary=[]))
    cfg = agent.config
    base = {
        "margin_erosion_pts": 1.0,
        "supplier_cost_increase_pct": 1.0,
        "budget_forecast_utilisation_pct": 50.0,
        "fy_month_elapsed": 6,
    }
    records = []

    # Threshold edges: hold everything else at baseline, sweep one field.
    for v in _sweep(cfg.margin_erosion_threshold_pts, 0.01):
        records.append(_record(agent, {**base, "margin_erosion_pts": v}))
    for v in _sweep(cfg.supplier_cost_increase_threshold_pct, 0.01):
        records.append(_record(agent, {**base, "supplier_cost_increase_pct": v}))
    hard_breach = 100.0 + cfg.generic_overspend_test_pct
    for v in _sweep(hard_breach, 0.01):
        records.append(_record(agent, {**base, "budget_forecast_utilisation_pct": v}))
    # Early-warning concern threshold interpolated at every sampled month.
    for month in range(1, 13):
        threshold = agent._early_late_threshold(month)
        for v in _sweep(threshold, 0.01):
            records.append(_record(agent, {**base, "budget_forecast_utilisation_pct": v, "fy_month_elapsed": month}))
    # Anchor months exactly.
    for month in (cfg.early_forecast_month, cfg.late_forecast_month):
        records.append(_record(agent, {**base, "fy_month_elapsed": month}))

    # Random complete padding.
    for _ in range(220):
        records.append(_record(agent, {
            "margin_erosion_pts": round(RNG.uniform(0, 15), 2),
            "supplier_cost_increase_pct": round(RNG.uniform(0, 25), 2),
            "budget_forecast_utilisation_pct": round(RNG.uniform(40, 130), 2),
            "fy_month_elapsed": RNG.randint(1, 12),
        }))

    return _dedupe(records)


# -------------------------------------------------------------------- delivery --

def delivery_factsets() -> list[dict]:
    agent = DeliveryAgent(agent_id="delivery", config=DeliveryConfig(lens="test", rules_summary=[]))
    base = {
        "budget": 1_000_000,
        "actual_pct": 0.55,
        "schedule_pct": 0.65,
        "spend_to_date": 600_000,
        "slip_days_before_change": 15,
        "is_resourced": True,
        "is_on_critical_path": True,
        "is_revenue_tagged": True,
        "revenue_value": 420_000,
        "reported_rag_before": "amber",
        "reported_rag_after": "green",
    }
    records = []
    rags = ["green", "amber", "red"]

    # Every boolean combination x every RAG-before/after pair.
    bool_fields = ["is_resourced", "is_on_critical_path", "is_revenue_tagged"]
    for bools in itertools.product([True, False], repeat=len(bool_fields)):
        overlay = dict(zip(bool_fields, bools))
        for before, after in itertools.product(rags, rags):
            records.append(_record(agent, {**base, **overlay, "reported_rag_before": before, "reported_rag_after": after}))

    # Random complete padding over the cosmetic/EVM fields too.
    for _ in range(140):
        records.append(_record(agent, {
            "budget": round(RNG.uniform(100_000, 5_000_000), 2),
            "actual_pct": round(RNG.uniform(0, 1), 3),
            "schedule_pct": round(RNG.uniform(0, 1), 3),
            "spend_to_date": round(RNG.uniform(10_000, 3_000_000), 2),
            "slip_days_before_change": round(RNG.uniform(0, 60), 1),
            "is_resourced": RNG.choice([True, False]),
            "is_on_critical_path": RNG.choice([True, False]),
            "is_revenue_tagged": RNG.choice([True, False]),
            "revenue_value": round(RNG.uniform(0, 1_000_000), 2),
            "reported_rag_before": RNG.choice(rags),
            "reported_rag_after": RNG.choice(rags),
        }))

    return _dedupe(records)


# ------------------------------------------------------------------------ pmo --

def pmo_factsets() -> list[dict]:
    agent = PMOAgent(agent_id="pmo", config=PMOConfig(lens="test", rules_summary=[]))
    cfg = agent.config
    base = {
        "is_contract_variation": False,
        "continued_business_case_justified": True,
        "portfolio_contention": False,
        "tolerance_variances_pct": {},
    }
    records = []

    # Per-dimension breach + hard-reject edges, one dimension varied at a time.
    for dim, tolerance in cfg.tolerances_pct.items():
        direction = cfg.adverse_direction.get(dim, "over")
        hard_reject = tolerance * cfg.hard_reject_multiple_of_tolerance
        if direction == "over":
            breach_center, reject_center = tolerance, hard_reject
        else:
            breach_center, reject_center = -tolerance, -hard_reject
        for center in (breach_center, reject_center):
            for v in _sweep(center, 0.01):
                records.append(_record(agent, {**base, "tolerance_variances_pct": {dim: v}}))

    # Multi-dimension simultaneous breach.
    records.append(_record(agent, {**base, "tolerance_variances_pct": {"cost": 15.0, "time": 12.0}}))
    records.append(_record(agent, {**base, "tolerance_variances_pct": {"cost": 25.0, "quality": -8.0}}))

    # Every boolean combination (tolerance dict held empty).
    bool_fields = ["is_contract_variation", "continued_business_case_justified", "portfolio_contention"]
    for bools in itertools.product([True, False], repeat=len(bool_fields)):
        overlay = dict(zip(bool_fields, bools))
        records.append(_record(agent, {**base, **overlay}))
        # ... and crossed with a real (non-breaching) variance dict, and a breaching one.
        records.append(_record(agent, {**base, **overlay, "tolerance_variances_pct": {"cost": 3.0}}))
        records.append(_record(agent, {**base, **overlay, "tolerance_variances_pct": {"cost": 15.0}}))

    # Random complete padding.
    dims = list(cfg.tolerances_pct.keys())
    for _ in range(220):
        n_dims = RNG.randint(0, 3)
        variances = {d: round(RNG.uniform(-30, 30), 2) for d in RNG.sample(dims, n_dims)} if n_dims else {}
        records.append(_record(agent, {
            "is_contract_variation": RNG.choice([True, False]),
            "continued_business_case_justified": RNG.choice([True, False]),
            "portfolio_contention": RNG.choice([True, False]),
            "tolerance_variances_pct": variances,
        }))

    return _dedupe(records)


# ------------------------------------------------------------------ operations --

def operations_factsets() -> list[dict]:
    agent = OperationsAgent(agent_id="operations", config=OperationsConfig(lens="test", rules_summary=[]))
    cfg = agent.config
    base = {
        "capacity_utilisation_pct_if_accepted": 70.0,
        "third_party_spend_pct_of_budget": 80.0,
        "savings_delivery_ratio": 0.95,
        "licence_provisioned_for_new_date": True,
        "supplier_sla_in_place": True,
    }
    records = []

    for v in _sweep(cfg.capacity_amber_threshold_pct, 0.01):
        records.append(_record(agent, {**base, "capacity_utilisation_pct_if_accepted": v}))
    for v in _sweep(cfg.capacity_red_threshold_pct, 0.01):
        records.append(_record(agent, {**base, "capacity_utilisation_pct_if_accepted": v}))
    for v in _sweep(cfg.spend_amber_threshold_pct, 0.01):
        records.append(_record(agent, {**base, "third_party_spend_pct_of_budget": v}))
    for v in _sweep(cfg.spend_red_threshold_pct, 0.01):
        records.append(_record(agent, {**base, "third_party_spend_pct_of_budget": v}))
    for v in _sweep(cfg.savings_amber_threshold_ratio, 0.001):
        records.append(_record(agent, {**base, "savings_delivery_ratio": v}))
    for v in _sweep(cfg.savings_red_threshold_ratio, 0.001):
        records.append(_record(agent, {**base, "savings_delivery_ratio": v}))

    # Every licence/SLA boolean combination, including the "one red, others
    # unstated-elsewhere-but-complete" cases the migration's bug regression cares about.
    for lic, sla in itertools.product([True, False], repeat=2):
        records.append(_record(agent, {**base, "licence_provisioned_for_new_date": lic, "supplier_sla_in_place": sla}))

    # Multiple simultaneous red/amber signals.
    records.append(_record(agent, {**base, "capacity_utilisation_pct_if_accepted": 101.0, "third_party_spend_pct_of_budget": 101.0}))
    records.append(_record(agent, {**base, "capacity_utilisation_pct_if_accepted": 92.0, "savings_delivery_ratio": 0.85}))

    # Random complete padding.
    for _ in range(190):
        records.append(_record(agent, {
            "capacity_utilisation_pct_if_accepted": round(RNG.uniform(0, 150), 2),
            "third_party_spend_pct_of_budget": round(RNG.uniform(0, 150), 2),
            "savings_delivery_ratio": round(RNG.uniform(0, 1.5), 3),
            "licence_provisioned_for_new_date": RNG.choice([True, False]),
            "supplier_sla_in_place": RNG.choice([True, False]),
        }))

    return _dedupe(records)


# ------------------------------------------------------------------------ seed --

def seed_golden() -> dict:
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    agents = {
        "finance": FinanceAgent(agent_id="finance", config=FinanceConfig(lens="test", rules_summary=[])),
        "delivery": DeliveryAgent(agent_id="delivery", config=DeliveryConfig(lens="test", rules_summary=[])),
        "pmo": PMOAgent(agent_id="pmo", config=PMOConfig(lens="test", rules_summary=[])),
        "operations": OperationsAgent(agent_id="operations", config=OperationsConfig(lens="test", rules_summary=[])),
    }
    out = {}
    for agent_id, agent in agents.items():
        position = agent.evaluate(SUPPLIER_MILESTONE_SEED["facts"][agent_id])
        out[agent_id] = {"stance": position["stance"], "driving_constraint": position["driving_constraint"]}
    return out


def main() -> None:
    generators = {
        "finance": finance_factsets,
        "delivery": delivery_factsets,
        "pmo": pmo_factsets,
        "operations": operations_factsets,
    }
    for agent_id, generator in generators.items():
        records = generator()
        assert len(records) >= MIN_SETS, f"{agent_id}: only {len(records)} unique fact sets, need >= {MIN_SETS}"
        for r in records:
            assert set(r["facts"].keys()), f"{agent_id}: empty fact set generated"
        path = OUT_DIR / f"factsets_{agent_id}.json"
        path.write_text(json.dumps(records, indent=2, default=str) + "\n")
        print(f"wrote {path} ({len(records)} fact sets)")

    seed_path = OUT_DIR / "seed_supplier_milestone.json"
    seed_path.write_text(json.dumps(seed_golden(), indent=2) + "\n")
    print(f"wrote {seed_path}")


if __name__ == "__main__":
    main()
