"""P3.6-Rules-Trigger-Spec.md §6.1 -- the safe rules engine, the foundation
every agent's migration builds on."""
import pytest

from agents.rules import (
    CheckResult,
    Rule,
    RuleError,
    check_rules,
    evaluate_expression,
    most_severe,
    validate_expression,
)


# ------------------------------------------------------------------ operators --

@pytest.mark.parametrize("op,left,right,expected", [
    (">", 5, 3, True), (">", 3, 5, False), (">", 5, 5, False),
    (">=", 5, 5, True), (">=", 4, 5, False),
    ("<", 3, 5, True), ("<", 5, 3, False),
    ("<=", 5, 5, True), ("<=", 6, 5, False),
    ("==", 5, 5, True), ("==", 5, 6, False),
    ("!=", 5, 6, True), ("!=", 5, 5, False),
])
def test_each_comparison_operator_returns_the_correct_result(op, left, right, expected):
    validate_expression(f"x {op} y", {"x", "y"})
    assert evaluate_expression(f"x {op} y", {"x": left, "y": right}) is expected


def test_and_or_not_combine_correctly():
    env = {"a": True, "b": False}
    assert evaluate_expression("a and b", env) is False
    assert evaluate_expression("a or b", env) is True
    assert evaluate_expression("not b", env) is True
    assert evaluate_expression("a and not b", env) is True


def test_boolean_fields_used_directly_without_a_comparison():
    validate_expression("licence_ok", {"licence_ok"})
    assert evaluate_expression("licence_ok", {"licence_ok": True}) is True
    assert evaluate_expression("not licence_ok", {"licence_ok": False}) is True


# ---------------------------------------------------------- name resolution --

def test_names_resolve_against_whatever_the_caller_puts_in_env():
    """The engine itself doesn't distinguish facts/derived/config -- that
    tiering is the caller's (check_rules'/each agent's derive()) job; here
    we only prove a merged env resolves correctly regardless of which tier
    a name conceptually belongs to."""
    env = {"stated_fact": 10.0, "derived_value": 88.0, "config_threshold": 80.0}
    validate_expression("stated_fact < derived_value", {"stated_fact", "derived_value"})
    assert evaluate_expression("derived_value >= config_threshold", env) is True


def test_unknown_name_rejected_at_validation():
    with pytest.raises(RuleError):
        validate_expression("mystery_field > 5", {"known_field"})


# --------------------------------------------------------- unsafe expressions --

@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hi')",
    "os.system('echo hi')",
    "(lambda: 1)()",
    "x.some_attr",
    "x[0]",
    "x['key']",
    "print(x)",
    "x.__class__",
    "__class__",
    "x if y else z",
    "[x for x in range(3)]",
])
def test_unsafe_expressions_rejected_at_validation_never_executed(expr):
    with pytest.raises(RuleError):
        validate_expression(expr, {"x", "y", "z"})


def test_malformed_expression_rejected():
    with pytest.raises(RuleError):
        validate_expression("x >", {"x"})


def test_import_call_attribute_subscript_lambda_all_individually_rejected():
    cases = {
        "import": "import os",
        "call": "len(x)",
        "attribute": "x.y",
        "subscript": "x[0]",
        "lambda": "(lambda: x)()",
    }
    for _kind, expr in cases.items():
        with pytest.raises(RuleError):
            validate_expression(expr, {"x", "y"})


# -------------------------------------------------------------- missing data --

def test_rule_with_an_unstated_field_does_not_fire_does_not_error_reports_unchecked():
    rule = Rule(id="r1", description="x over 5", fields=("x",), when="x > 5", stance="no")
    result = check_rules([rule], env={}, stated_fields=set())
    assert result.fired == ()
    assert result.unchecked == ("x",)
    assert result.stance is None


def test_derived_value_with_unstated_input_is_itself_unstated():
    """A derived value (e.g. an interpolated threshold) that couldn't be
    computed because its own inputs were unstated must simply be ABSENT
    from stated_fields -- check_rules doesn't know or care that it's
    "derived" rather than a raw fact; the caller (derive()) is responsible
    for omitting it from stated_fields when its inputs are missing."""
    rule = Rule(id="r1", description="over the derived threshold", fields=("value", "derived_threshold"),
                when="value > derived_threshold", stance="conditional")
    # derived_threshold couldn't be computed (its own input was unstated) --
    # caller omits it from stated_fields even though it's present in env
    # with some placeholder; check_rules must still treat it as unchecked.
    result = check_rules([rule], env={"value": 10.0}, stated_fields={"value"})
    assert result.fired == ()
    assert "derived_threshold" in result.unchecked


# ---------------------------------------------------------- severity/firing --

def test_most_severe_stance_selected_across_multiple_fired_rules():
    rules = [
        Rule(id="a", description="a", fields=("x",), when="x > 0", stance="yes"),
        Rule(id="b", description="b", fields=("x",), when="x > 0", stance="conditional"),
        Rule(id="c", description="c", fields=("y",), when="y > 0", stance="blocker", keywords=("kw",)),
    ]
    result = check_rules(rules, env={"x": 1, "y": 1}, stated_fields={"x", "y"})
    assert {f.id for f in result.fired} == {"a", "b", "c"}
    assert result.stance == "blocker"


def test_most_severe_ordering_is_blocker_gt_no_gt_conditional_gt_yes():
    assert most_severe("yes", "conditional") == "conditional"
    assert most_severe("conditional", "no") == "no"
    assert most_severe("no", "blocker") == "blocker"
    assert most_severe("blocker", "yes") == "blocker"
    assert most_severe(None, "yes") == "yes"
    assert most_severe("yes", None) == "yes"
    assert most_severe(None, None) is None


def test_no_rule_fires_gives_none_stance_and_empty_fired():
    rule = Rule(id="r1", description="x over 100", fields=("x",), when="x > 100", stance="no")
    result = check_rules([rule], env={"x": 1}, stated_fields={"x"})
    assert result.fired == ()
    assert result.unchecked == ()
    assert result.stance is None


# ------------------------------------------------------------ Rule construction --

def test_blocker_rule_without_keywords_is_rejected():
    with pytest.raises(RuleError):
        Rule(id="r1", description="x", fields=("x",), when="x > 0", stance="blocker")


def test_blocker_rule_with_keywords_constructs_fine():
    rule = Rule(id="r1", description="x", fields=("x",), when="x > 0", stance="blocker", keywords=("kw",))
    assert rule.keywords == ("kw",)
