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
for (let i = 0; i < 800; i++) if (b.admitCurve(many)) admitted++;
out.admitted = admitted;
out.curvesSaid = b.leftOutText(many);
const spentFirst = b.newWork();
spentFirst.spent = b.MAX_EVALS;
out.noCurveOnceSpent = b.admitCurve(spentFirst) === false && spentFirst.skipped === 1;
// skipped curves stay said after an update (they are still not drawn)
b.settleWork(many);
out.skippedStaySaid = b.leftOutText(many).includes('first 24 of 800');
out.maxCurves = b.MAX_CURVES;
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


def test_harness_control_a_flag_that_is_never_cleared_is_seen(tmp_path):
    # the old design: one flag, set by any board and never cleared
    source = BUDGET.read_text()
    broken = source.replace("  work.overran = false;\n  return text;", "  return text;")
    assert broken != source
    bad = tmp_path / "broken.js"
    bad.write_text(broken)
    got = run(tmp_path, bad)
    assert got["clearedByNext"] is False
