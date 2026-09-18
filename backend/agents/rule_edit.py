"""Guided rule editing for the Council tab (no free-text expressions).

A user can (1) edit a shipped non-blocker rule's stance, description and
threshold, (2) add a rule from a guided form -- field, operator, typed value,
stance, description -- and (3) delete a rule they added. Everything else is
refused here, at the one seam every save goes through (registry.save_agent_
config), so a raw PUT gets exactly the same protection as the UI:

  * blocker rules are never added, removed or altered (checked in the registry);
  * a shipped rule's field/operator/expression never change;
  * a user-added rule's `when` is GENERATED from its structured condition, so
    no user-supplied text is ever parsed as an expression, let alone evaluated;
  * a user-written description is stored brace-escaped, so it is literal text
    under str.format() -- never a template.
"""
from __future__ import annotations

import ast
import math
from typing import Any, Optional, get_args, get_origin, Literal

from .base import ConfigurableAgent, RuleConfig, MAX_RULE_LENGTH

OPERATORS = (">", ">=", "<", "<=", "==", "!=")
OPERATOR_WORDS = {">": "is above", ">=": "is at least", "<": "is below", "<=": "is at most", "==": "is", "!=": "is not"}
EDITABLE_STANCES = ("yes", "conditional", "no")
MAX_USER_RULES = 10
DEFAULT_BOUNDS = (-1_000_000_000_000.0, 1_000_000_000_000.0)


class RuleEditError(ValueError):
    """A rule edit the policy refuses. The message is shown to the user as-is."""


def escape_text(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


# ------------------------------------------------------------- field meta --

def _annotation_kind(annotation: Any) -> tuple[Optional[str], list[str]]:
    if annotation is bool:
        return "boolean", []
    if annotation in (int, float):
        return "number", []
    if get_origin(annotation) is Literal:
        return "enum", [str(a) for a in get_args(annotation)]
    return None, []  # dict-shaped facts can't be compared with a single value


def scalar_fields(agent: ConfigurableAgent) -> list[dict]:
    """The facts a guided rule may compare: scalar ones only, with their
    human label, type, options and bounds."""
    out = []
    for name, info in agent.facts_model.model_fields.items():
        kind, options = _annotation_kind(info.annotation)
        if kind is None:
            continue
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        lo, hi = extra.get("min", DEFAULT_BOUNDS[0]), extra.get("max", DEFAULT_BOUNDS[1])
        out.append({
            "name": name, "label": agent.field_label(name), "type": kind, "options": options,
            "integer": info.annotation is int, "min": lo, "max": hi,
        })
    return out


def _field_meta(agent: ConfigurableAgent, name: str) -> dict:
    for f in scalar_fields(agent):
        if f["name"] == name:
            return f
    choices = ", ".join(f["label"] for f in scalar_fields(agent))
    raise RuleEditError(f"'{name}' is not a field this agent can compare. Choose one of: {choices}.")


def allowed_operators(kind: str) -> tuple[str, ...]:
    return OPERATORS if kind == "number" else ("==", "!=")


def validate_condition(agent: ConfigurableAgent, cond: Any) -> None:
    meta = _field_meta(agent, cond.field)
    label = meta["label"]
    if cond.op not in allowed_operators(meta["type"]):
        raise RuleEditError(
            f"'{cond.op}' can't be used with {label} (a {meta['type']} fact) -- use "
            + " or ".join(f"'{o}'" for o in allowed_operators(meta["type"])) + "."
        )
    v = cond.value
    if meta["type"] == "boolean":
        if not isinstance(v, bool):
            raise RuleEditError(f"{label} takes a yes/no value, not {v!r}.")
    elif meta["type"] == "enum":
        if v not in meta["options"]:
            raise RuleEditError(f"{label} must be one of {', '.join(meta['options'])}, not {v!r}.")
    else:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise RuleEditError(f"{label} takes a number, not {v!r}.")
        if not math.isfinite(v):
            raise RuleEditError(f"{label}: the value must be a finite number.")
        if meta["integer"] and float(v) != int(v):
            raise RuleEditError(f"{label} takes a whole number, not {v!r}.")
        if not (meta["min"] <= v <= meta["max"]):
            raise RuleEditError(f"{label}: {v:g} is out of range -- it must be between {meta['min']:g} and {meta['max']:g}.")


def build_when(cond: Any) -> str:
    """The rule expression, generated from validated structured parts only."""
    v = cond.value
    literal = repr(bool(v)) if isinstance(v, bool) else repr(v)
    return f"{cond.field} {cond.op} {literal}"


# ------------------------------------------------------------------ policy --

def _check_label(rule: RuleConfig) -> None:
    text = rule.label.strip()
    if not text:
        raise RuleEditError("A rule needs a plain-English description.")
    if len(text) > MAX_RULE_LENGTH:
        raise RuleEditError(f"The description is too long ({len(text)} characters) -- the limit is {MAX_RULE_LENGTH}.")
    if rule.description != escape_text(rule.label):
        raise RuleEditError(f"'{text[:40]}': a description is plain text, not a template.")


def _name(rule: RuleConfig) -> str:
    return rule.label or rule.id


def enforce_rule_policy(agent: ConfigurableAgent, current: list[dict], new: list[RuleConfig]) -> None:
    """Raise RuleEditError unless `new` is reachable from `current` by the
    permitted edits only. Blocker rules are guarded separately (and first) by
    registry.save_agent_config; they are skipped here."""
    cur = {r["id"]: RuleConfig.model_validate(r) for r in current}
    ids = [r.id for r in new]
    if len(ids) != len(set(ids)):
        raise RuleEditError("Two rules share the same id.")

    for rid, c in cur.items():
        if rid not in ids and c.stance != "blocker" and not c.user_added:
            raise RuleEditError(
                f"'{_name(c)}' is part of the agent's shipped config and can't be deleted -- edit it instead."
            )

    user_rules = 0
    for r in new:
        if r.user_added:
            user_rules += 1
        c = cur.get(r.id)
        if c is not None and c.stance == "blocker":
            continue
        if r.stance not in EDITABLE_STANCES:
            raise RuleEditError(f"'{_name(r)}': a rule's stance must be yes, conditional or no.")

        if c is not None:
            same = (r.fields == c.fields and r.keywords == c.keywords and r.user_added == c.user_added
                    and r.threshold == c.threshold)
            if not same:
                raise RuleEditError(f"'{_name(c)}': only a rule's stance, description and threshold can be edited.")
            if c.user_added:
                if r.condition is None or c.condition is None or (r.condition.field, r.condition.op) != (c.condition.field, c.condition.op):
                    raise RuleEditError(f"'{_name(c)}': the field and operator of an existing rule can't change.")
                validate_condition(agent, r.condition)
                if r.when != build_when(r.condition):
                    raise RuleEditError(f"'{_name(c)}': the condition can't be edited as text.")
            elif r.when != c.when or r.condition != c.condition:
                raise RuleEditError(f"'{_name(c)}': the condition of a shipped rule can't be changed, only its threshold.")
            if (r.label, r.description) != (c.label, c.description):
                _check_label(r)
            continue

        # a new rule
        if not (r.user_added and r.condition is not None and r.id.startswith("user_")):
            raise RuleEditError("New rules can only be added through the guided form (field, operator, value).")
        if r.threshold is not None or r.keywords:
            raise RuleEditError("A new rule can't declare a threshold or keywords.")
        validate_condition(agent, r.condition)
        if r.fields != [r.condition.field] or r.when != build_when(r.condition):
            raise RuleEditError("A new rule's condition can't be written as text.")
        _check_label(r)

    if user_rules > MAX_USER_RULES:
        raise RuleEditError(f"An agent can have at most {MAX_USER_RULES} rules you've added.")


# ---------------------------------------------------------- plain English --

def _num(v: float, prefix: str = "", suffix: str = "") -> str:
    body = f"{v:,.0f}" if abs(v) >= 1_000_000 else f"{v:g}"
    return f"{prefix}{body}{suffix}"


def _unit(label: str) -> tuple[str, str]:
    if "(£)" in label:
        return "£", ""
    if "(%" in label or "% of" in label:
        return "", "%"
    if "(points)" in label:
        return "", " pts"
    return "", ""


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def condition_text(agent: ConfigurableAgent, when: str) -> str:
    """A rule's `when` in plain English using field titles -- never an
    internal name. Thresholds that already have a value (config scalars and
    config-only derived lines) are shown as that value."""
    facts = agent.facts_model.model_fields
    env = agent._rule_env({})
    derived_labels = agent.derived_labels()

    def name_text(n: str, unit: tuple[str, str]) -> str:
        if n in facts:
            return agent.field_label(n)
        v = env.get(n)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return _num(v, *unit)
        if n in derived_labels:
            return derived_labels[n]
        return n.replace("_", " ")

    def operand(node: ast.AST, unit: tuple[str, str]) -> str:
        if isinstance(node, ast.Name):
            return name_text(node.id, unit)
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                return "yes" if v else "no"
            if isinstance(v, (int, float)):
                return _num(v, *unit)
            return str(v)
        return "?"

    def clause(node: ast.AST, skip_left: Optional[str] = None) -> tuple[str, str]:
        if isinstance(node, ast.Compare):
            left = operand(node.left, ("", ""))
            right = node.comparators[0]
            if isinstance(right, ast.Constant) and isinstance(right.value, bool) and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
                answer = (isinstance(node.ops[0], ast.Eq)) == right.value
                return f"{left}: {'yes' if answer else 'no'}", left
            unit = _unit(left)
            op_word = OPERATOR_WORDS[{ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=", ast.Eq: "==", ast.NotEq: "!="}[type(node.ops[0])]]
            text = f"{op_word} {operand(node.comparators[0], unit)}"
            return (text if skip_left == left else f"{left} {text}"), left
        if isinstance(node, ast.UnaryOp):
            inner, left = clause(node.operand)
            return f"not ({inner})", left
        if isinstance(node, ast.BoolOp):
            joiner = " and " if isinstance(node.op, ast.And) else " or "
            parts, prev = [], None
            for v in node.values:
                text, left = clause(v, skip_left=prev)
                parts.append(text)
                prev = left
            return joiner.join(parts), prev or ""
        return operand(node, ("", "")), ""

    tree = ast.parse(when, mode="eval")
    return _capital(clause(tree.body)[0])


# -------------------------------------------------------------- the view --

def _config_value(agent: ConfigurableAgent, key: str) -> Any:
    data = agent.config.model_dump()
    if "." in key:
        head, sub = key.split(".", 1)
        return data[head][sub]
    return data[key]


def _config_bounds(agent: ConfigurableAgent, key: str) -> tuple[Optional[float], Optional[float]]:
    if "." in key:
        return 0.0, 200.0   # PMOConfig validates every tolerance in 0-200
    lo = hi = None
    for m in agent.config_model.model_fields[key].metadata:
        lo = getattr(m, "ge", lo)
        hi = getattr(m, "le", hi)
    return lo, hi


def rules_view(agent: ConfigurableAgent) -> dict:
    """Everything the Council tab needs to draw one agent's rules in plain
    English and to offer exactly the edits the policy allows -- so the UI
    never has to know an internal name or an expression."""
    fields = scalar_fields(agent)
    by_name = {f["name"]: f for f in fields}
    rules = []
    for r in agent.config.rules:
        threshold = None
        if r.threshold is not None:
            lo, hi = _config_bounds(agent, r.threshold.key)
            threshold = {"kind": "config", "key": r.threshold.key, "label": r.threshold.label, "unit": r.threshold.unit,
                         "type": "number", "value": _config_value(agent, r.threshold.key), "min": lo, "max": hi}
        elif r.user_added and r.condition is not None:
            meta = by_name.get(r.condition.field, {})
            threshold = {"kind": "value", "key": None, "label": "value", "unit": "", "type": meta.get("type", "number"),
                         "options": meta.get("options", []), "value": r.condition.value,
                         "min": meta.get("min"), "max": meta.get("max")}
        rules.append({
            "id": r.id,
            "label": r.label or r.id.replace("_", " ").capitalize(),
            "stance": r.stance,
            "system_governed": r.stance == "blocker",
            "user_added": r.user_added,
            "deletable": r.user_added and r.stance != "blocker",
            "condition_text": condition_text(agent, r.when),
            "threshold": threshold,
        })
    return {
        "agent": agent.id,
        "fields": fields,
        "operators": {"number": list(OPERATORS), "boolean": ["==", "!="], "enum": ["==", "!="]},
        "operator_words": OPERATOR_WORDS,
        "stances": list(EDITABLE_STANCES),
        "max_user_rules": MAX_USER_RULES,
        "rules": rules,
    }
