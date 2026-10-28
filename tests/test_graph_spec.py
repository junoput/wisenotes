"""The graph block's spec language, run against the cases the JS parser will share (20261022-064)."""

import json
import math
import re
import sys
from pathlib import Path

import pytest

from app import graph_spec

CASES = json.loads((Path(__file__).parent / "graph_spec_cases.json").read_text())
SPECIAL = {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}


def same(got: float, want) -> bool:
    want = SPECIAL.get(want, want)
    if math.isnan(want):
        return math.isnan(got)
    if math.isinf(want):
        return got == want
    return math.isclose(got, want, rel_tol=1e-12, abs_tol=1e-12)


def test_the_cases_file_is_not_empty():
    # premise: a parametrize over an empty list passes vacuously
    assert len(CASES["values"]) >= 60
    assert len(CASES["rejected"]) >= 40
    assert sum(1 for s in CASES["specs"] if s["errors"]) >= 20
    assert sum(1 for s in CASES["specs"] if not s["errors"]) >= 5


@pytest.mark.parametrize("case", CASES["values"], ids=lambda c: c["expr"])
def test_an_expression_has_its_value(case):
    got = graph_spec.evaluate(case["expr"], case.get("env"))
    assert same(got, case["value"]), (case["expr"], got)


@pytest.mark.parametrize("case", CASES["rejected"], ids=lambda c: c["expr"][:30] or "empty")
def test_an_expression_is_refused_with_its_code(case):
    with pytest.raises(ValueError) as refused:
        graph_spec.evaluate(case["expr"], case.get("env"))
    assert refused.value.code == case["code"]


@pytest.mark.parametrize("case", CASES["specs"], ids=lambda c: c["name"])
def test_a_definition_is_refused_on_exactly_its_lines(case):
    spec = graph_spec.parse(case["spec"])
    assert [[e.line, e.code] for e in spec.errors] == case["errors"]
    for check in case.get("checks", []):
        env = check.get("env", {})
        if "view" in check:
            assert [list(spec.view.x), list(spec.view.y)] == [
                check["view"]["x"],
                check["view"]["y"],
            ]
        elif "curve" in check:
            curve = spec.curves[check["curve"]]
            if "range" in check:
                assert [curve.lo, curve.hi] == check["range"]
            else:
                got = [curve.x(check["t"], env), curve.y(check["t"], env)]
                assert all(same(g, w) for g, w in zip(got, check["value"], strict=True)), got
        elif "function" in check:
            assert same(spec.functions[check["function"]](check["x"], env), check["value"])
        else:
            got = [c(env) for c in spec.points[check["point"]]]
            assert all(same(g, w) for g, w in zip(got, check["value"], strict=True)), got


def test_an_error_message_names_the_line():
    (err,) = graph_spec.validate("\n\nb = slider(5, 1)")
    assert str(err) == "line 3: the slider must go from low to high"


def test_a_message_never_carries_the_expression():
    # The page shows these; at most an identifier from the line may appear in one.
    secret = "Zq7"
    for text in (f"f(x) = {secret}x + 1", f"P = (1, {secret}*2)", f"view 2d x {secret}..1"):
        (err,) = graph_spec.validate(text)
        assert "+ 1" not in err.message and "*2" not in err.message and ".." not in err.message


def test_the_slider_and_view_values_are_kept():
    spec = graph_spec.parse("view 2d x -2*pi..2*pi\nk = slider(0, 2, step 0.5, value 1.5, play)")
    assert spec.view.x == (-2 * math.pi, 2 * math.pi)
    assert spec.view.y == (-5.0, 5.0)
    k = spec.sliders["k"]
    assert (k.lo, k.hi, k.step, k.value, k.play) == (0, 2, 0.5, 1.5, True)
    assert graph_spec.parse("k = slider(1, 2)").sliders["k"].value == 1  # defaults to its low end


def test_user_text_never_reaches_eval():
    # The parser builds closures; nothing in it may call eval, exec or compile.
    source = Path(graph_spec.__file__).read_text()
    calls = re.findall(r"(?<![\w.])(eval|exec|compile|__import__|getattr)\s*\(", source)
    assert calls == []
    assert re.findall(r"(?<![\w.])(eval)\s*\(", "x = eval(t)") == ["eval"]  # the check can see one


def test_a_stack_overflow_is_an_error_on_its_line_and_never_escapes(monkeypatch):
    # The safety net behind MAX_TOKENS: with the cap lifted, a 5000-term sum overflows
    # the evaluator's stack on save. That must be a reported line, not a 500.
    chain = "+".join(["1"] * 5000)
    monkeypatch.setattr(graph_spec, "MAX_TOKENS", 10**6)
    monkeypatch.setattr(graph_spec, "MAX_COST", 10**6)
    errors = graph_spec.validate(f"a = slider(0, 1)\nb = slider(0, {chain})\nc = slider(0, 2)")
    assert [(e.line, e.code) for e in errors] == [(2, "too_deep")]


def test_the_token_cap_is_far_below_the_stack_it_protects():
    # The longest chain the cap allows evaluates, with room to spare under the recursion
    # limit; if the cap is raised past what Python can walk, this fails before a user does.
    n = graph_spec.MAX_TOKENS // 2
    assert graph_spec.evaluate("+".join(["1"] * n)) == n
    assert n * 4 < sys.getrecursionlimit()
