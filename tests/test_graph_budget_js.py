"""The allowance of a graph board, and what its hint says (20261028-060).

app/static/js/graph-budget.js has no DOM, so node runs it. The browser check
(tests/graph_draw.py) shows the hints on a real page; the overrun path, which a real
curve rarely reaches (24 curves at depth 10/8 stay near 50,000 evaluations), is shown here.
"""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGET = ROOT / "app/static/js/graph-budget.js"

SCRIPT = r"""
import * as b from './graph-budget.mjs';
const out = {};
const say = (w) => b.leftOutText(w);

// a cheap board says nothing, however often it is updated
const cheap = b.newWork();
for (let i = 0; i < 3; i++) { for (let k = 0; k < 2000; k++) b.overBudget(cheap); b.settleWork(cheap); }
out.cheap = say(cheap);

// the allowance is per board: a heavy board does not charge a cheap one
const heavy = b.newWork(), other = b.newWork();
for (let k = 0; k < b.MAX_EVALS + 10; k++) b.overBudget(heavy);
out.heavyOverran = heavy.overran;
out.otherUntouched = other.spent === 0 && !other.overran && b.settleWork(other) === '';

// exactly MAX_EVALS evaluations are within the allowance, one more is not
const edge = b.newWork();
let last = false;
for (let k = 0; k < b.MAX_EVALS; k++) last = b.overBudget(edge);
out.atTheLimit = last === false && edge.overran === false;
out.pastTheLimit = b.overBudget(edge) === true && edge.overran === true;

// the overrun is said after the update, and cleared by the next update that stays inside
out.said = b.settleWork(heavy);
out.clearedByNext = b.settleWork(heavy) === '';
out.cleanAfter = heavy.spent === 0 && heavy.overran === false;

// curves: the first MAX_CURVES are admitted, the rest are counted; no curve once the
// allowance is spent
const many = b.newWork();
let admitted = 0;
for (let i = 0; i < 800; i++) if (b.admitCurve(many, `f${i}`)) admitted++;
out.admitted = admitted;
out.curvesSaid = b.leftOutText(many);
const spentFirst = b.newWork();
spentFirst.spent = b.MAX_EVALS;
out.noCurveOnceSpent = b.admitCurve(spentFirst, 'g') === false && spentFirst.skipped.length === 1;
// skipped curves stay said after an update (they are still not drawn)
b.settleWork(many);
out.skippedStaySaid = b.leftOutText(many).includes('first 24 of 800');
out.maxCurves = b.MAX_CURVES;

// the curves left out are named, in the order of the definition, five and then a count
out.named = b.leftOutText(many);
const two = b.newWork();
for (let i = 0; i < b.MAX_CURVES + 2; i++) b.admitCurve(two, `h${i}`);
out.namedTwo = b.leftOutText(two);

// creating a curve charges half (JSXGraph evaluates a curve twice when it makes it), and
// the weight is back to 1 afterwards, also when the creation throws
const made = b.newWork();
b.creating(made, () => { for (let k = 0; k < 1000; k++) b.overBudget(made); });
out.createdSpent = made.spent;
for (let k = 0; k < 1000; k++) b.overBudget(made);
out.thenFull = made.spent;
try { b.creating(made, () => { throw new Error('x'); }); } catch { /* the point */ }
out.weightAfterThrow = made.weight;
out.creationWeight = b.CREATION_WEIGHT;
// 24 creations at the weight, each of 4,100 evaluations (a circle here), stay inside the allowance
const circles = b.newWork();
for (let i = 0; i < 24; i++) {
  if (!b.admitCurve(circles, `c${i}`)) break;
  b.creating(circles, () => { for (let k = 0; k < 4100; k++) b.overBudget(circles); });
}
out.circlesAdmitted = circles.curves;
out.circlesOverran = circles.overran;
console.log(JSON.stringify(out));
"""


def run(tmp_path: Path, source: Path = BUDGET) -> dict:
    node = shutil.which("node")
    assert node, "node is required to run the budget"
    (tmp_path / "graph-budget.mjs").write_text(source.read_text())
    (tmp_path / "check.mjs").write_text(SCRIPT)
    r = subprocess.run(
        [node, "check.mjs"], capture_output=True, text=True, check=False, cwd=tmp_path
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def test_a_boards_allowance_and_its_hint(tmp_path):
    got = run(tmp_path)
    assert got["maxCurves"] == 24  # the instrument ran this file, with this constant
    assert got["cheap"] == ""
    assert got["heavyOverran"] and got["otherUntouched"]
    assert got["atTheLimit"] and got["pastTheLimit"]
    assert "takes too much work" in got["said"]
    assert got["clearedByNext"] and got["cleanAfter"]
    assert got["admitted"] == 24 and "first 24 of 800" in got["curvesSaid"]
    assert got["noCurveOnceSpent"] and got["skippedStaySaid"]


def test_the_curves_left_out_are_named(tmp_path):
    got = run(tmp_path)
    assert got["maxCurves"] == 24
    assert "left out: f24, f25, f26, f27, f28 and 771 more." in got["named"]
    assert "in the order of the definition" in got["named"]
    assert got["namedTwo"].endswith("left out: h24, h25.")  # two: no count


def test_creating_a_curve_is_charged_at_half_and_the_weight_comes_back(tmp_path):
    got = run(tmp_path)
    assert got["creationWeight"] == 0.5  # the instrument ran this file
    assert got["createdSpent"] == 500
    assert got["thenFull"] == 1500  # the next 1000 are charged in full
    assert got["weightAfterThrow"] == 1
    # twenty-four circles of 4,100 evaluations each at creation are all admitted, with no gap
    assert got["circlesAdmitted"] == 24 and got["circlesOverran"] is False


def test_harness_control_creation_charged_in_full_is_seen(tmp_path):
    # the old design: the 13th circle ran out of allowance at creation
    source = BUDGET.read_text()
    broken = source.replace(
        "export const CREATION_WEIGHT = 0.5;", "export const CREATION_WEIGHT = 1;"
    )
    assert broken != source
    bad = tmp_path / "broken.js"
    bad.write_text(broken)
    got = run(tmp_path, bad)
    assert got["circlesAdmitted"] < 24 and got["circlesOverran"] is True


def test_harness_control_a_flag_that_is_never_cleared_is_seen(tmp_path):
    # the old design: one flag, set by any board and never cleared
    source = BUDGET.read_text()
    broken = source.replace("  work.overran = false;\n  return text;", "  return text;")
    assert broken != source
    bad = tmp_path / "broken.js"
    bad.write_text(broken)
    got = run(tmp_path, bad)
    assert got["clearedByNext"] is False
