"""Safe expression evaluator for agent rules (P3.6-Rules-Trigger-Spec.md §5.1).

No `eval`/`exec` anywhere: a rule's `when` expression is parsed with
`ast.parse(mode="eval")` and only ever walked through a whitelisted node set
(BoolOp and/or, UnaryOp not, Compare >,>=,<,<=,==,!=, Name, Constant).
Anything else -- Call, Attribute, Subscript, Lambda, Import, a dunder name,
an unknown field name -- is rejected at validation time (config load or
Council-UI save) and is never executed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Stance = Literal["yes", "conditional", "no", "blocker"]
_STANCE_SEVERITY = {"yes": 0, "conditional": 1, "no": 2, "blocker": 3}

_COMPARE_OPS = {
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}


class RuleError(ValueError):
    """A rule expression failed validation -- unsafe, malformed, or references
    an unknown name. Raised at config load/save time; a rule that passed
    validation cannot raise this during evaluation."""


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    fields: tuple[str, ...]
    when: str
    stance: Stance
    keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.stance == "blocker" and not self.keywords:
            raise RuleError(f"rule {self.id!r}: blocker rules must declare `keywords` (tripwire, spec §5.5)")


def validate_expression(expr: str, allowed_names: set[str]) -> None:
    """Raise RuleError unless `expr` is a safe boolean expression referencing
    only names in `allowed_names`. Call this at config load and on every
    Council-UI save -- never skip it before evaluate_expression."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise RuleError(f"malformed rule expression {expr!r}: {exc}") from exc
    _validate_node(tree.body, allowed_names, expr)


def _validate_node(node: ast.AST, allowed_names: set[str], expr: str) -> None:
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise RuleError(f"unsupported boolean operator in {expr!r}")
        for value in node.values:
            _validate_node(value, allowed_names, expr)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):
            raise RuleError(f"unsupported unary operator in {expr!r}")
        _validate_node(node.operand, allowed_names, expr)
        return
    if isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _COMPARE_OPS:
                raise RuleError(f"unsupported comparison operator in {expr!r}")
        _validate_node(node.left, allowed_names, expr)
        for comparator in node.comparators:
            _validate_node(comparator, allowed_names, expr)
        return
    if isinstance(node, ast.Name):
        if node.id not in allowed_names:
            raise RuleError(f"unknown name {node.id!r} in rule expression {expr!r}")
        return
    if isinstance(node, ast.Constant):
        if node.value is not None and not isinstance(node.value, (bool, int, float, str)):
            raise RuleError(f"unsupported constant type in {expr!r}")
        return
    raise RuleError(f"disallowed expression element ({type(node).__name__}) in {expr!r}")


def evaluate_expression(expr: str, env: dict[str, Any]) -> bool:
    """Evaluate a PRE-VALIDATED expression. Every name `expr` references must
    already be present in `env` -- the caller (check_rules) is responsible
    for the "is every field stated" gate before calling this; a KeyError
    here means the caller didn't gate correctly, not a data problem."""
    tree = ast.parse(expr, mode="eval")
    return bool(_eval_node(tree.body, env))


def _eval_node(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v, env) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp):
        return not _eval_node(node.operand, env)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, env)
        result = True
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, env)
            result = result and _COMPARE_OPS[type(op)](left, right)
            left = right
        return result
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    raise RuleError(f"disallowed expression element at evaluation: {type(node).__name__}")


@dataclass(frozen=True)
class FiredRule:
    id: str
    description: str
    stance: Stance


@dataclass(frozen=True)
class CheckResult:
    fired: tuple[FiredRule, ...]
    unchecked: tuple[str, ...]  # fields referenced by >=1 rule, not stated
    stance: Optional[Stance]    # most severe fired stance, or None if nothing fired


def most_severe(a: Optional[Stance], b: Optional[Stance]) -> Optional[Stance]:
    """blocker > no > conditional > yes. Either side may be None (absent)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if _STANCE_SEVERITY[a] >= _STANCE_SEVERITY[b] else b


def check_rules(rules: list[Rule], env: dict[str, Any], stated_fields: set[str]) -> CheckResult:
    """Check every rule against `env` (stated facts + derived values + config
    scalars, already merged). `stated_fields` is the subset of `env`'s keys
    that are genuinely STATED facts/derived values -- config scalars are
    always "known" and never contribute to `unchecked`.

    A rule fires only when every one of its `fields` is in `stated_fields`
    AND `when` evaluates true. A rule with any unstated field never fires
    and never raises; its unstated fields are reported in `unchecked`
    regardless of whether some other rule on the same agent fired.
    """
    fired: list[FiredRule] = []
    unchecked: set[str] = set()
    for rule in rules:
        missing = [f for f in rule.fields if f not in stated_fields]
        if missing:
            unchecked.update(missing)
            continue
        if evaluate_expression(rule.when, env):
            fired.append(FiredRule(id=rule.id, description=rule.description, stance=rule.stance))

    stance: Optional[Stance] = None
    for f in fired:
        stance = most_severe(stance, f.stance)

    return CheckResult(fired=tuple(fired), unchecked=tuple(sorted(unchecked)), stance=stance)
