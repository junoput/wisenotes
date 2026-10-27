"""The graph block's definition: a line-based, GeoGebra-flavoured spec (20261022-064).

A graph block stores its definition as text in Chapter.content. This module
parses and checks it, so that a save can be refused with line-numbered reasons
instead of storing something the graph cannot draw. Slice 1 of the plan on
20261022-064 covers:

    # a comment
    view 2d  x -5..5  y -3..3
    a = slider(0, 5, step 0.1, value 1, play)
    f(x) = a*sin(x)
    P = (1, 2)
    Q = (3, f(3))

One statement per line. Expressions allow numbers, + - * / ^ and parentheses, the
functions in FUNCTIONS, the constants pi and e, the sliders and functions already
defined above the line, and, inside f(x) = ..., the variable x. Nothing else:
no attribute access, no implicit multiplication (write 2*x, not 2x).

USER TEXT IS NEVER EVALUATED AS CODE. An expression is parsed by the recursive
descent below and compiled to Python closures over the math module. The JS
side (slice 2) implements the same grammar, and both run the shared cases in
tests/graph_spec_cases.json, which pin values, error codes and their lines.

The language is ASCII. A digit is 0-9, a name is A-Za-z0-9_, and whitespace is a
space, a tab or a carriage return (a form posts a textarea with CRLF). Lines are
split on the newline character only. Anything else outside a "#" comment is refused: as
"character" inside an expression, and as "statement" between the parts of a statement
(a U+00A0 after f, or before the parenthesis of slider), where no pattern matches the line. The JS
parser can match this with no Unicode tables; Python's isspace, regex digit class,
float() and splitlines() all accept more than JS does.

Values are IEEE-754 doubles and every operator and function gives what the JS
operator or Math function of the same name gives for the same doubles, including
Infinity and NaN (exp(1000) is Infinity, ln(0) is -Infinity, a domain error is NaN,
1^Infinity is NaN), and the sign of a zero (1/ceil(-0.5) and 1/min(0, -0) are -Infinity).
tests/graph_spec_cases.json pins the cases.

Size is bounded as nesting is: an expression longer than MAX_TOKENS tokens is
refused ("too_long"), so the closure tree, and the stack of any parser or
evaluator that walks it, stays shallow. What one evaluation costs is bounded the same way:
an expression's tokens plus the cost of each user function it calls may not exceed MAX_COST
("too_costly"), which bounds a chain of functions calling functions, and a function that
calls another twice at every level. A view line splits on whitespace, so a
range is written without spaces: x -2*pi..2*pi, not x -2 * pi..2*pi. A definition
has one view line, which is its default view; a second is refused.

Each error carries a stable code (the shared cases assert it) and a message
for the person editing. A message names the line and the rule, and at most an
identifier from the line, never a whole expression.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

MAX_DEPTH = 64  # nesting of parentheses and calls; deeper is refused, not recursed into
# A chain such as 1+1+1+... nests no parentheses but still builds a tree as deep as it
# is long, and the checker evaluates constants on save. 256 tokens is a long formula
# and a closure tree under ~260 frames, well inside Python's 1000 and JS's thousands.
MAX_TOKENS = 256
# What one evaluation may cost: the tokens of an expression plus, for each call of a user
# function, that function's own cost. Chains f1..fN that each call the one above, and
# f(x) = g(x) + g(x) doubling at every level, would otherwise evaluate as deep or as long as
# the definition lets them (the evaluator draws a curve by calling it hundreds of times).
MAX_COST = 512
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?|\.[0-9]+")
BLANK = " \t\r"  # the whitespace of the language


@dataclass(frozen=True)
class SpecError:
    line: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


class _Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class View:
    kind: str
    x: tuple[float, float] = (-5.0, 5.0)
    y: tuple[float, float] = (-5.0, 5.0)


@dataclass
class Slider:
    name: str
    lo: float
    hi: float
    step: float | None
    value: float
    play: bool


@dataclass
class GraphSpec:
    view: View | None = None
    sliders: dict[str, Slider] = field(default_factory=dict)
    functions: dict[str, Callable[[float, dict[str, float]], float]] = field(default_factory=dict)
    points: dict[str, tuple[Callable[[dict[str, float]], float], ...]] = field(default_factory=dict)
    errors: list[SpecError] = field(default_factory=list)


# ---------------------------------------------------------------- expressions

Env = dict[str, float]
Compiled = Callable[[Env], float]


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in BLANK:
            i += 1
            continue
        m = NUMBER.match(text, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        m = NAME.match(text, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        if ch in "+-*/^(),":
            out.append(ch)
            i += 1
            continue
        raise _Refused("character", f"'{ch}' is not part of the graph language")
    if len(out) > MAX_TOKENS:
        raise _Refused("too_long", f"longer than {MAX_TOKENS} symbols; split it into parts")
    return out


def _safe(fn: Callable[..., float], *args: float) -> float:
    """A math error is NaN, as it is in JS: the graph shows a gap, nothing raises."""
    try:
        return float(fn(*args))
    except (ValueError, OverflowError, ZeroDivisionError):
        return math.nan


def _exp(a: float) -> float:
    try:
        return math.exp(a)
    except OverflowError:
        return math.inf  # JS: exp(1000) is Infinity


def _log(fn: Callable[[float], float]) -> Callable[[float], float]:
    """ln and log: 0 is -Infinity and below 0 is NaN, as Math.log and Math.log10."""

    def wrapped(a: float) -> float:
        if math.isnan(a) or a < 0:
            return math.nan
        return -math.inf if a == 0 else fn(a)

    return wrapped


def _round(fn: Callable[[float], int]) -> Callable[[float], float]:
    """floor and ceil keep NaN, +-Infinity and the sign of a zero result, as Math.floor and
    Math.ceil do: ceil(-0.5) is -0, and 1/ceil(-0.5) is -Infinity."""

    def wrapped(a: float) -> float:
        if math.isnan(a) or math.isinf(a):
            return a
        r = float(fn(a))
        return math.copysign(r, a) if r == 0 else r

    return wrapped


def _extreme(pick: Callable[[float, float], float]) -> Callable[[float, float], float]:
    """min and max: NaN if either is NaN (Python's min(nan, 1) is nan but min(1, nan) is 1),
    and -0 is below +0, as in Math.min and Math.max (Python returns the first of the two)."""

    def wrapped(a: float, b: float) -> float:
        if math.isnan(a) or math.isnan(b):
            return math.nan
        if a == 0 and b == 0:
            negative = [math.copysign(1.0, v) < 0 for v in (a, b)]
            return -0.0 if (any(negative) if pick is min else all(negative)) else 0.0
        return pick(a, b)

    return wrapped


def _div(a: float, b: float) -> float:
    if b == 0:
        if a == 0 or math.isnan(a):
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def _odd_integer(b: float) -> bool:
    return math.isfinite(b) and b == math.floor(b) and b % 2 == 1


def _pow(a: float, b: float) -> float:
    """Math.pow / ** in JS: NaN for a NaN exponent, and for a base of 1 or -1 to
    +-Infinity (math.pow gives 1.0 for both); an overflow takes the sign of an odd power."""
    if math.isnan(b) or (math.isinf(b) and abs(a) == 1):
        return math.nan
    if a == 0 and b < 0:
        # 0 ** -1 is Infinity and (-0) ** -1 is -Infinity, where math.pow raises
        return -math.inf if math.copysign(1.0, a) < 0 and _odd_integer(b) else math.inf
    try:
        return math.pow(a, b)
    except ValueError:
        return math.nan  # a negative base to a fractional power
    except OverflowError:
        return -math.inf if a < 0 and _odd_integer(b) else math.inf


# name -> (arity, implementation). Both parsers implement exactly this list.
FUNCTIONS: dict[str, tuple[int, Callable[..., float]]] = {
    "sin": (1, math.sin),
    "cos": (1, math.cos),
    "tan": (1, math.tan),
    "asin": (1, math.asin),
    "acos": (1, math.acos),
    "atan": (1, math.atan),
    "atan2": (2, math.atan2),
    "sqrt": (1, math.sqrt),
    "abs": (1, abs),
    "exp": (1, _exp),
    "ln": (1, _log(math.log)),
    "log": (1, _log(math.log10)),
    "floor": (1, _round(math.floor)),
    "ceil": (1, _round(math.ceil)),
    "min": (2, _extreme(min)),
    "max": (2, _extreme(max)),
}
CONSTANTS = {"pi": math.pi, "e": math.e}
# Bound variables: x for f(x) now; y, t, u and v are kept for the curves and
# surfaces of later slices, so no definition may take them.
VARIABLES = ("x", "y", "t", "u", "v")
KEYWORDS = ("view", "slider", "step", "value", "play", "in")
RESERVED = frozenset(FUNCTIONS) | frozenset(CONSTANTS) | frozenset(VARIABLES) | frozenset(KEYWORDS)


class _Parser:
    """Recursive descent over the tokens of one expression.

    expr   := term (("+" | "-") term)*
    term   := unary (("*" | "/") unary)*
    unary  := "-" unary | "+" unary | power
    power  := atom ("^" unary)?          # right-associative; -x^2 is -(x^2)
    atom   := number | name | name "(" args ")" | "(" expr ")"
    """

    def __init__(
        self,
        tokens: list[str],
        values: set[str],
        functions: dict[str, Callable[[float, Env], float]],
        others: dict[str, str],
    ):
        self.tokens = tokens
        self.pos = 0
        self.values = values  # names an expression may read: sliders, bound variables
        self.functions = functions  # user functions defined above
        self.others = others  # names defined as something that is not a number, and what
        self.depth = 0
        self.cost = len(tokens)

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, tok: str) -> None:
        if self.peek() != tok:
            got = self.peek()
            if tok == ")" and got is None:
                raise _Refused("unclosed", "a '(' is not closed")
            raise _Refused("unexpected", f"expected '{tok}' here")
        self.pos += 1

    def parse(self) -> Compiled:
        if not self.tokens:
            raise _Refused("empty", "an expression is missing")
        node = self.expr()
        if self.peek() is not None:
            if self.peek() == ")":
                raise _Refused("unexpected", "a ')' has no matching '('")
            raise _Refused(
                "unexpected", "two values without an operator between them (write 2*x, not 2x)"
            )
        if self.cost > MAX_COST:
            raise _Refused(
                "too_costly", "this, with the functions it calls, is too long to evaluate"
            )
        node.cost = self.cost  # type: ignore[attr-defined]
        return node

    def expr(self) -> Compiled:
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            left, right = node, self.term()
            if op == "+":
                node = lambda env, a=left, b=right: a(env) + b(env)  # noqa: E731
            else:
                node = lambda env, a=left, b=right: a(env) - b(env)  # noqa: E731
        return node

    def term(self) -> Compiled:
        node = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            left, right = node, self.unary()
            if op == "*":
                node = lambda env, a=left, b=right: a(env) * b(env)  # noqa: E731
            else:
                node = lambda env, a=left, b=right: _div(a(env), b(env))  # noqa: E731
        return node

    def unary(self) -> Compiled:
        if self.peek() in ("-", "+"):
            op = self.take()
            self.enter()
            inner = self.unary()
            self.depth -= 1
            return (lambda env, a=inner: -a(env)) if op == "-" else inner
        return self.power()

    def power(self) -> Compiled:
        base = self.atom()
        if self.peek() == "^":
            self.take()
            self.enter()
            exponent = self.unary()
            self.depth -= 1
            return lambda env, a=base, b=exponent: _pow(a(env), b(env))
        return base

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise _Refused("too_deep", f"nested more than {MAX_DEPTH} levels deep")

    def atom(self) -> Compiled:
        tok = self.peek()
        if tok is None:
            raise _Refused("empty", "an operator is missing its right-hand side")
        if NUMBER.fullmatch(tok):
            self.take()
            value = float(tok)
            return lambda env: value
        if tok == "(":
            self.take()
            self.enter()
            inner = self.expr()
            self.expect(")")
            self.depth -= 1
            return inner
        if NAME.fullmatch(tok):
            self.take()
            if self.peek() == "(":
                return self.call(tok)
            return self.name(tok)
        if tok == ")":
            raise _Refused("unexpected", "a ')' has no matching '('")
        raise _Refused("unexpected", f"'{tok}' cannot start a value")

    def name(self, name: str) -> Compiled:
        if name in CONSTANTS:
            value = CONSTANTS[name]
            return lambda env: value
        if name in self.values:
            return lambda env: env[name]
        if name in FUNCTIONS or name in self.functions:
            raise _Refused("not_a_value", f"{name} is a function: call it, as {name}(...)")
        if name in self.others:
            raise _Refused("not_a_value", f"{name} is {self.others[name]}, not a number")
        if name in VARIABLES:
            raise _Refused("variable", f"{name} is not a variable here")
        raise _Refused("unknown_name", f"{name} is not defined above this line")

    def call(self, name: str) -> Compiled:
        self.take()  # "("
        self.enter()
        args: list[Compiled] = []
        if self.peek() is None:
            raise _Refused("unclosed", "a '(' is not closed")
        if self.peek() != ")":
            args.append(self.expr())
            while self.peek() == ",":
                self.take()
                args.append(self.expr())
        self.expect(")")
        self.depth -= 1
        if name in FUNCTIONS:
            arity, fn = FUNCTIONS[name]
            if len(args) != arity:
                raise _Refused("arity", f"{name} takes {arity} argument{'s' * (arity > 1)}")
            if arity == 1:
                (a,) = args
                return lambda env: _safe(fn, a(env))
            a, b = args
            return lambda env: _safe(fn, a(env), b(env))
        if name in self.functions:
            if len(args) != 1:
                raise _Refused("arity", f"{name} takes 1 argument")
            user, (a,) = self.functions[name], args
            self.cost += user.cost  # type: ignore[attr-defined]
            return lambda env: user(a(env), env)
        if name in self.values or name in self.others or name in CONSTANTS:
            raise _Refused("not_a_function", f"{name} is not a function")
        raise _Refused("unknown_function", f"{name} is not a known function")


def compile_expression(
    text: str,
    values: set[str] = frozenset(),
    functions: dict[str, Callable[[float, Env], float]] | None = None,
    others: dict[str, str] | None = None,
) -> Compiled:
    """Compile one expression to a closure taking the values of `values` by name.
    Raises ValueError with a .code attribute when the expression is refused."""
    try:
        return _Parser(_tokens(text), set(values), functions or {}, others or {}).parse()
    except _Refused as e:
        err = ValueError(e.message)
        err.code = e.code  # type: ignore[attr-defined]
        raise err from None


def evaluate(text: str, env: Env | None = None) -> float:
    """The value of a constant expression, or one over the names in `env`."""
    env = env or {}
    return compile_expression(text, set(env))(env)


# ---------------------------------------------------------------- statements

_B = r"[ \t\r]*"  # the language's blanks, not \s: Python's matches Unicode spaces and \f \v
_B_SPLIT = r"[ \t\r]+"
_N = "[A-Za-z][A-Za-z0-9_]*"
FUNCTION_DEF = re.compile(rf"({_N}){_B}\({_B}({_N}){_B}\){_B}=(.*)")
ASSIGN = re.compile(rf"({_N}){_B}=(.*)")
SLIDER = re.compile(rf"slider{_B}\((.*)\){_B}", re.S)
POINT = re.compile(rf"\((.*)\){_B}", re.S)


def _split_top(text: str) -> list[str]:
    """Split on commas outside parentheses."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


class _Checker:
    def __init__(self) -> None:
        self.spec = GraphSpec()
        self.kinds: dict[str, str] = {}  # every name defined, and what it is

    def constant(self, text: str) -> float:
        """A number fixed by the text alone: no slider, no variable."""
        try:
            value = compile_expression(text, others=self.kinds_as_others())({})
        except ValueError as e:
            if e.code in ("unknown_name", "not_a_value", "variable"):  # type: ignore[attr-defined]
                raise _Refused("constant", "must be a plain number here, not a name") from None
            raise _Refused(e.code, str(e)) from None  # type: ignore[attr-defined]
        if not math.isfinite(value):
            raise _Refused("constant", "must be a finite number")
        return value

    def kinds_as_others(self) -> dict[str, str]:
        return {n: f"a {k}" for n, k in self.kinds.items()}

    def expression(self, text: str, variable: str | None = None) -> Compiled:
        values = {n for n, k in self.kinds.items() if k == "slider"}
        if variable:
            values.add(variable)
        others = {n: f"a {k}" for n, k in self.kinds.items() if k not in ("slider", "function")}
        try:
            return compile_expression(text, values, self.spec.functions, others)
        except ValueError as e:
            raise _Refused(e.code, str(e)) from None  # type: ignore[attr-defined]

    def define(self, name: str, kind: str) -> None:
        if name in RESERVED:
            raise _Refused("reserved", f"{name} is a reserved word and cannot be defined")
        if name in self.kinds:
            raise _Refused("redefined", f"{name} is already defined above")
        self.kinds[name] = kind

    def line(self, text: str) -> None:
        stripped = text.split("#", 1)[0].strip(BLANK)
        if not stripped:
            return
        if stripped == "view" or stripped.startswith(("view ", "view\t", "view\r")):
            return self.view(stripped)
        m = FUNCTION_DEF.fullmatch(stripped)
        if m:
            return self.function(m.group(1), m.group(2), m.group(3))
        m = ASSIGN.fullmatch(stripped)
        if m:
            name, rhs = m.group(1), m.group(2).strip(BLANK)
            s = SLIDER.fullmatch(rhs)
            if s:
                return self.slider(name, s.group(1))
            p = POINT.fullmatch(rhs)
            if p and len(_split_top(p.group(1))) > 1:
                return self.point(name, p.group(1))
            raise _Refused(
                "statement",
                f"{name} = ... must be a slider(...) or a point (x, y)",
            )
        raise _Refused(
            "statement",
            "not a statement: expected view, a slider, a function f(x) = ... or a point P = (x, y)",
        )

    def view(self, text: str) -> None:
        if self.spec.view is not None:
            raise _Refused("view_twice", "only one view line is allowed")
        words = [w for w in re.split(_B_SPLIT, text) if w]
        if len(words) < 2:
            raise _Refused("view_kind", "view needs a kind: view 2d")
        if words[1] != "2d":
            raise _Refused("view_kind", "only view 2d is supported so far")
        view = View("2d")
        rest = words[2:]
        seen: set[str] = set()
        while rest:
            axis = rest.pop(0)
            if axis not in ("x", "y"):
                raise _Refused("view_option", "a 2d view takes x and y ranges, as x -5..5")
            if axis in seen:
                raise _Refused("view_option", f"the {axis} range is given twice")
            if not rest:
                raise _Refused("view_range", f"{axis} needs a range, as {axis} -5..5")
            lo_text, sep, hi_text = rest.pop(0).partition("..")
            if not sep:
                raise _Refused("view_range", f"{axis} needs a range, as {axis} -5..5")
            lo, hi = self.constant(lo_text), self.constant(hi_text)
            if not lo < hi:
                raise _Refused("view_range", f"the {axis} range must go from low to high")
            setattr(view, axis, (lo, hi))
            seen.add(axis)
        self.spec.view = view

    def slider(self, name: str, args_text: str) -> None:
        args = [a.strip(BLANK) for a in _split_top(args_text)]
        if len(args) < 2 or not args[0] or not args[1]:
            raise _Refused("slider_range", "slider needs a low and a high end: slider(0, 5)")
        lo, hi = self.constant(args[0]), self.constant(args[1])
        if not lo < hi:
            raise _Refused("slider_range", "the slider must go from low to high")
        step = value = None
        play = False
        for opt in args[2:]:
            word, _, rest = opt.partition(" ")
            if word == "play" and not rest.strip(BLANK):
                if play:
                    raise _Refused("slider_option", "play is given twice")
                play = True
            elif word in ("step", "value") and rest.strip(BLANK):
                if (step if word == "step" else value) is not None:
                    raise _Refused("slider_option", f"{word} is given twice")
                number = self.constant(rest)
                if word == "step":
                    step = number
                else:
                    value = number
            else:
                raise _Refused(
                    "slider_option", "a slider option is step <number>, value <number> or play"
                )
        if step is not None and not 0 < step <= hi - lo:
            raise _Refused("slider_step", "the step must be above 0 and at most the slider's span")
        if value is not None and not lo <= value <= hi:
            raise _Refused("slider_value", "the value must be within the slider's range")
        self.define(name, "slider")
        self.spec.sliders[name] = Slider(name, lo, hi, step, lo if value is None else value, play)

    def function(self, name: str, variable: str, body: str) -> None:
        if variable != "x":
            raise _Refused("function_variable", f"a function is written {name}(x) = ...")
        if name in FUNCTIONS:
            raise _Refused("reserved", f"{name} is a built-in function and cannot be redefined")
        compiled = self.expression(body.strip(BLANK), variable="x")
        self.define(name, "function")
        fn = lambda x, env, c=compiled: c({**env, "x": x})  # noqa: E731
        fn.cost = compiled.cost  # type: ignore[attr-defined]
        self.spec.functions[name] = fn

    def point(self, name: str, inner: str) -> None:
        coords = [c.strip(BLANK) for c in _split_top(inner)]
        if len(coords) != 2:
            raise _Refused("point", "a point has two coordinates: P = (x, y)")
        compiled = tuple(self.expression(c) for c in coords)
        self.define(name, "point")
        self.spec.points[name] = compiled


def parse(text: str) -> GraphSpec:
    """Parse a whole definition. Every refused line is reported, each with its
    1-based line number; a refused line defines nothing, so a later line using
    its name is reported as well."""
    checker = _Checker()
    # "\n" only: str.splitlines() also splits on \v \f \x1c-\x1e \x85 and U+2028/9,
    # which would number the lines differently from the JS parser's split("\n").
    for number, line in enumerate(text.split("\n"), start=1):
        try:
            checker.line(line)
        except _Refused as e:
            checker.spec.errors.append(SpecError(number, e.code, e.message))
        except RecursionError:
            # Belt and braces behind MAX_TOKENS: a definition never fails the save with a 500.
            checker.spec.errors.append(
                SpecError(number, "too_deep", "nested or chained too deeply to check")
            )
    return checker.spec


def validate(text: str) -> list[SpecError]:
    return parse(text).errors
