"""Where the points, lines and circles of a graph block are (20261022-064, slice 4).

app/static/js/graph-geometry.js works the constructions out; node runs it here with the
parser that makes the spec (app/static/js/graph-spec.js).
"""

import json
import math
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app/static/js"

SCRIPT = r"""
import { parse, newEnv } from './graph-spec.mjs';
import * as g from './graph-geometry.mjs';

const cases = JSON.parse(process.argv[2]);
const out = {};
for (const [name, c] of Object.entries(cases)) {
  const spec = parse(c.text);
  if (spec.errors.length) { out[name] = { errors: spec.errors.map((e) => `${e.line} ${e.code}`) }; continue; }
  const env = newEnv(c.env ?? {});
  const solved = g.solve(spec, env);
  out[name] = Object.fromEntries(c.read.map((r) => [r, solved.named.get(r) ?? null]));
}

// the solved definition is kept while the sliders hold still, and only then
const spec = parse('a = slider(0, 3, value 1)\nP = (a, 0)\nQ = (3, 1)\ns = segment(P, Q)');
let calls = 0;
const [fx, fy] = spec.points.get('P');
spec.points.set('P', [(env) => { calls++; return fx(env); }, fy]);
const env = newEnv({ a: 1 });
const get = g.geometry(spec, env);
for (let i = 0; i < 10; i++) get();
const kept = calls;
env.a = 2;
const after = get().shapes[0];
for (let i = 0; i < 10; i++) get();
out.keeping = { kept, afterMove: calls, p: after.p };

// a chain of midpoints that double back on themselves is solved once per statement
let chain = 'P = (0, 0)\nQ = (1024, 0)\nM0 = midpoint(P, Q)\n';
for (let i = 1; i < 150; i++) chain += `M${i} = midpoint(M${i - 1}, M${i - 1})\n`;
const started = performance.now();
const deep = g.solve(parse(chain), newEnv());
out.chain = { last: deep.named.get('M149'), ms: performance.now() - started, count: deep.shapes.length };

// the first of two places stays the first while a slider moves
const sweep = parse('r = slider(0.2, 5, value 1)\nA = (-6, 0.5)\nB = (6, 0.5)\nO = (0, 0)\nl = line(A, B)\nc = circle(O, r)\nX = intersection(l, c, 1)\nY = intersection(l, c, 2)');
const swept = [];
for (let r = 0.2; r <= 5; r += 0.1) {
  const s = g.solve(sweep, newEnv({ r }));
  swept.push([s.named.get('X'), s.named.get('Y')]);
}
out.sweep = swept;
console.log(JSON.stringify(out));
"""

BASE = "P = (0, 0)\nQ = (2, 2)\nR = (0, 2)\nS = (2, 0)\n"
CIRCLE_LINE = "A = (-3, 0)\nB = (3, 0)\nO = (0, 0)\n"
CASES = {
    "cross": {
        "text": BASE + "l = line(P, Q)\nm = line(R, S)\nX = intersection(l, m)",
        "read": ["X"],
    },
    "segments_cross": {
        "text": BASE + "l = segment(P, Q)\nm = segment(R, S)\nX = intersection(l, m)",
        "read": ["X"],
    },
    "segment_stops": {  # the lines meet at (1.5, 1.5), which the short segment does not reach
        "text": "P = (0, 0)\nQ = (1, 1)\nR = (0, 3)\nS = (3, 0)\n"
        "s = segment(P, Q)\nw = segment(R, S)\nk = line(P, Q)\nX = intersection(s, w)\n"
        "Y = intersection(k, w)\nZ = intersection(w, k)\nV = intersection(w, s)",
        "read": ["X", "Y", "Z", "V"],
    },
    "parallel": {
        "text": "P = (0, 0)\nQ = (1, 1)\nR = (0, 1)\nS = (1, 2)\nl = line(P, Q)\nm = line(R, S)\nX = intersection(l, m)\nY = intersection(l, l)",
        "read": ["X", "Y"],
    },
    "line_circle": {
        "text": CIRCLE_LINE
        + "l = line(A, B)\nc = circle(O, 2)\nX = intersection(l, c, 1)\nY = intersection(l, c, 2)\n"
        "Z = intersection(c, l)",
        "read": ["X", "Y", "Z"],
    },
    "segment_circle": {  # the segment ends at the centre: only the first place is on it
        "text": CIRCLE_LINE
        + "s = segment(A, O)\nc = circle(O, 2)\nX = intersection(s, c, 1)\nY = intersection(s, c, 2)",
        "read": ["X", "Y"],
    },
    "default_index": {  # no number: the first place that exists, from either end of the segment
        "text": "O = (0, 0)\nA = (-3, 0)\nB = (3, 0)\nc = circle(O, 2)\ns = segment(O, B)\nk = segment(A, O)\n"
        "X = intersection(s, c)\nY = intersection(k, c)\nZ = intersection(s, c, 1)\nW = intersection(s, c, 2)\n"
        "l = line(A, B)\nV = intersection(l, c)\nU = intersection(c, c)",
        "read": ["X", "Y", "Z", "W", "V", "U"],
    },
    "touching": {
        "text": "A = (-3, 2)\nB = (3, 2)\nO = (0, 0)\nl = line(A, B)\nc = circle(O, 2)\nX = intersection(l, c, 1)\nY = intersection(l, c, 2)",
        "read": ["X", "Y"],
    },
    "touching_with_noise": {  # 0.1 + 0.2 is 0.30000000000000004: the line is a hair past the circle
        "text": "A = (-3, 0.1 + 0.2)\nB = (3, 0.1 + 0.2)\nO = (0, 0)\nl = line(A, B)\nc = circle(O, 0.3)\n"
        "X = intersection(l, c, 1)\nY = intersection(l, c, 2)\nZ = intersection(l, c)",
        "read": ["X", "Y", "Z"],
    },
    "missing": {
        "text": "A = (-3, 3)\nB = (3, 3)\nO = (0, 0)\nl = line(A, B)\nc = circle(O, 2)\nX = intersection(l, c, 1)\nY = intersection(l, c, 2)",
        "read": ["X", "Y"],
    },
    "circles": {
        "text": "O = (0, 0)\nT = (2, 0)\nc = circle(O, 2)\nd = circle(T, 2)\nX = intersection(c, d, 1)\n"
        "Y = intersection(c, d, 2)\nU = intersection(d, c, 1)",
        "read": ["X", "Y", "U"],
    },
    "circles_touching": {
        "text": "O = (0, 0)\nT = (2, 0)\nc = circle(O, 1)\nd = circle(T, 1)\nX = intersection(c, d, 1)\nY = intersection(c, d, 2)",
        "read": ["X", "Y"],
    },
    "circles_apart": {
        "text": "O = (0, 0)\nT = (5, 0)\nU = (0.1, 0)\nc = circle(O, 1)\nd = circle(T, 1)\nh = circle(U, 0.5)\n"
        "f = circle(O, 0.2)\nX = intersection(c, d)\nY = intersection(c, h)\nZ = intersection(c, c)\nW = intersection(f, h, 2)",
        "read": ["X", "Y", "Z", "W"],
    },
    "circle_through": {
        "text": "O = (1, 1)\nT = (4, 5)\nc = circle(O, T)\nd = circle(O, O)\nX = intersection(c, c)\nl = line(O, T)\n"
        "Y = intersection(l, c, 2)",
        "read": ["X", "Y"],
    },
    "midpoint": {
        "text": "P = (0, 0)\nQ = (4, -2)\nM = midpoint(P, Q)\nN = midpoint(M, Q)",
        "read": ["M", "N"],
    },
    "not_a_number": {
        "text": "P = (1/0, 0)\nQ = (0, 0)\nR = (1, 1)\nM = midpoint(P, Q)\nN = midpoint(M, R)\ns = segment(P, Q)\n"
        "w = segment(Q, R)\nl = line(Q, R)\nX = intersection(s, w)\nY = intersection(l, w)\nc = circle(P, 1)\nd = circle(Q, 1/0)\n"
        "Z = intersection(c, d)",
        "read": ["M", "N", "X", "Y", "Z"],
    },
    "radius_from_a_slider": {
        "text": "r = slider(-1, 3, value 2)\nO = (0, 0)\nl = line(O, O)\nc = circle(O, r)\nX = intersection(c, c)",
        "read": ["l", "c"],
        "env": {"r": 2},
    },
    "radius_zero": {
        "text": "r = slider(-1, 3, value 0)\nO = (0, 0)\nA = (-1, 0)\nB = (1, 0)\nm = line(A, B)\nc = circle(O, r)\nX = intersection(m, c)",
        "read": ["c", "X"],
        "env": {"r": 0},
    },
}


def run_node(tmp_path: Path, geometry: Path = JS / "graph-geometry.js") -> dict:
    node = shutil.which("node")
    assert node, "node is required to run the geometry"
    (tmp_path / "graph-spec.mjs").write_text((JS / "graph-spec.js").read_text())
    (tmp_path / "graph-geometry.mjs").write_text(geometry.read_text())
    (tmp_path / "check.mjs").write_text(SCRIPT)
    r = subprocess.run(
        [node, "check.mjs", json.dumps(CASES)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def near(got, want):
    if want is None:
        return got is None
    return got is not None and all(
        math.isclose(g, w, abs_tol=1e-9) for g, w in zip(got, want, strict=True)
    )


def test_the_premise_every_case_parses(tmp_path):
    got = run_node(tmp_path)
    for name in CASES:
        assert "errors" not in got[name], (name, got[name])  # a case that never ran proves nothing


def test_two_straight_things_cross_once_and_a_segment_stops_at_its_ends(tmp_path):
    got = run_node(tmp_path)
    assert near(got["cross"]["X"], [1, 1])
    assert near(got["segments_cross"]["X"], [1, 1])
    assert got["segment_stops"]["X"] is None  # two segments that do not reach each other
    assert got["segment_stops"]["V"] is None  # and when it is the second that falls short
    assert near(got["segment_stops"]["Y"], [1.5, 1.5])  # the line goes on, the segment t holds it
    assert near(got["segment_stops"]["Z"], [1.5, 1.5])  # in either order
    assert got["parallel"] == {"X": None, "Y": None}  # parallel, and a line with itself


def test_a_line_meets_a_circle_nearer_end_first(tmp_path):
    got = run_node(tmp_path)
    assert near(got["line_circle"]["X"], [-2, 0])
    assert near(got["line_circle"]["Y"], [2, 0])
    assert near(got["line_circle"]["Z"], [-2, 0])  # circle first or line first
    assert near(got["segment_circle"]["X"], [-2, 0])
    assert got["segment_circle"]["Y"] is None  # (2, 0) is beyond the segment's end
    assert near(got["touching"]["X"], [0, 2]) and near(got["touching"]["Y"], [0, 2])
    noisy = got["touching_with_noise"]
    assert near(noisy["X"], [0, 0.3]) and near(noisy["Y"], [0, 0.3]) and near(noisy["Z"], [0, 0.3])
    assert got["missing"] == {"X": None, "Y": None}


def test_without_a_number_it_is_the_first_place_that_exists(tmp_path):
    got = run_node(tmp_path)["default_index"]
    assert near(got["X"], [2, 0]) and near(
        got["W"], [2, 0]
    )  # from the centre, only the 2nd is on it
    assert got["Z"] is None  # written 1 means the 1st, which is behind the centre
    assert near(got["Y"], [-2, 0])
    assert near(got["V"], [-2, 0])  # both exist: the first
    assert got["U"] is None


def test_two_circles_meet_left_of_the_way_between_the_centres_first(tmp_path):
    got = run_node(tmp_path)
    root = math.sqrt(3)
    assert near(got["circles"]["X"], [1, root])
    assert near(got["circles"]["Y"], [1, -root])
    assert near(got["circles"]["U"], [1, -root])  # from the other centre, left is the other way
    assert near(got["circles_touching"]["X"], [1, 0]) and near(got["circles_touching"]["Y"], [1, 0])
    # apart, inside, the same circle with itself, concentric
    assert got["circles_apart"] == {"X": None, "Y": None, "Z": None, "W": None}


def test_a_circle_through_a_point_and_a_midpoint(tmp_path):
    got = run_node(tmp_path)
    assert got["circle_through"] == {"X": None, "Y": got["circle_through"]["Y"]}
    assert near(got["circle_through"]["Y"], [4, 5])  # the point it goes through is on it
    assert near(got["midpoint"]["M"], [2, -1]) and near(got["midpoint"]["N"], [3, -1.5])


def test_what_does_not_exist_is_null_and_stays_null_down_the_definition(tmp_path):
    got = run_node(tmp_path)
    assert got["not_a_number"] == {"M": None, "N": None, "X": None, "Y": None, "Z": None}
    assert got["radius_from_a_slider"]["l"] is None  # a line through one point twice
    assert got["radius_from_a_slider"]["c"]["r"] == 2
    assert got["radius_zero"] == {"c": None, "X": None}


def test_a_solved_definition_is_kept_until_a_slider_moves(tmp_path):
    got = run_node(tmp_path)["keeping"]
    assert got["kept"] == 1  # ten reads, one solve
    assert got["afterMove"] == 2  # the move, and ten reads after it, one more
    assert near(got["p"], [2, 0])  # and it is the new answer


def test_a_chain_that_doubles_back_is_solved_once_per_statement(tmp_path):
    chain = run_node(tmp_path)["chain"]
    assert chain["count"] == 150 and chain["ms"] < 1000
    assert near(chain["last"], [512, 0])  # (0..1024) halved again: the point is M0 itself


def test_the_first_place_stays_the_first_while_a_slider_moves(tmp_path):
    sweep = run_node(tmp_path)["sweep"]
    both = [(x, y) for x, y in sweep if x is not None and y is not None]
    assert len(sweep) > 40 and 10 < len(both) < len(sweep)  # it crosses, and sometimes misses
    assert all(x[0] <= y[0] for x, y in both)  # never swapped (equal where it touches)


def test_harness_control_a_swapped_index_is_seen(tmp_path):
    broken = tmp_path / "broken.js"
    source = (JS / "graph-geometry.js").read_text()
    anchor = "(index === 1 ? -root : root)"
    assert source.count(anchor) == 1
    broken.write_text(source.replace(anchor, "(index === 1 ? root : -root)"))
    got = run_node(tmp_path, broken)
    assert near(got["line_circle"]["X"], [2, 0])  # the instrument can tell
