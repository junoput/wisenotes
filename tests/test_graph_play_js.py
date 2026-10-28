"""The motion of a playing slider (20261022-064, slice 3): app/static/js/graph-play.js, run by node."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAY = ROOT / "app/static/js/graph-play.js"

SCRIPT = r"""
import * as p from './graph-play.mjs';
const out = { sweep: p.SWEEP_SECONDS };
const range = { lo: 0, hi: 5 };

// a whole sweep takes SWEEP_SECONDS, at any frame rate
for (const fps of [10, 30, 60, 144]) {
  let s = { value: 0, dir: 1 };
  const dt = 1 / fps;
  let t = 0;
  while (s.dir === 1 && t < 20) { s = p.advance(s, dt, range); t += dt; }
  out[`sweep${fps}`] = t;
}

// it bounces and stays inside the range, and keeps bouncing
let s = { value: 4.9, dir: 1 };
let min = 99, max = -99, turns = 0, last = s.dir;
for (let i = 0; i < 2000; i++) {
  s = p.advance(s, 1 / 60, range);
  min = Math.min(min, s.value); max = Math.max(max, s.value);
  if (s.dir !== last) { turns++; last = s.dir; }
}
out.min = min; out.max = max; out.turns = turns;

// a frame after a long sleep moves at most 0.1 s of a sweep, and the first frame (dt 0) none
out.afterSleep = p.advance({ value: 1, dir: 1 }, 60, range).value - 1;
out.firstFrame = p.advance({ value: 1, dir: 1 }, 0, range).value;
out.backwardsClock = p.advance({ value: 1, dir: 1 }, -5, range).value;

// the shown value lies on the step grid, inside the range
out.snapStep = p.snap(0.34, { lo: 0, hi: 5, step: 0.1 });
out.snapGridFromLow = p.snap(1.3, { lo: 1, hi: 2, step: 0.25 });
out.snapClamped = p.snap(5.2, { lo: 0, hi: 5, step: 0.5 });
out.snapNoStep = p.snap(2.718, { lo: 0, hi: 5, step: null });
console.log(JSON.stringify(out));
"""


def run(tmp_path: Path, source: Path = PLAY) -> dict:
    node = shutil.which("node")
    assert node, "node is required to run the slider's motion"
    (tmp_path / "graph-play.mjs").write_text(source.read_text())
    (tmp_path / "check.mjs").write_text(SCRIPT)
    r = subprocess.run(
        [node, "check.mjs"], capture_output=True, text=True, check=False, cwd=tmp_path
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def test_a_slider_sweeps_and_bounces_inside_its_range(tmp_path):
    got = run(tmp_path)
    assert got["sweep"] == 4  # the instrument ran this file, with this constant
    for fps in (10, 30, 60, 144):
        assert abs(got[f"sweep{fps}"] - got["sweep"]) <= 1 / fps + 1e-9, (fps, got)
    assert 0 <= got["min"] and got["max"] <= 5
    assert got["max"] > 4.9 and got["min"] < 0.1 and got["turns"] >= 4
    assert abs(got["afterSleep"] - 5 * 0.1 / got["sweep"]) < 1e-9
    assert got["firstFrame"] == 1 and got["backwardsClock"] == 1


def test_the_shown_value_is_on_the_step_grid(tmp_path):
    got = run(tmp_path)
    assert abs(got["snapStep"] - 0.3) < 1e-9
    assert abs(got["snapGridFromLow"] - 1.25) < 1e-9
    assert got["snapClamped"] == 5
    assert got["snapNoStep"] == 2.718


def test_harness_control_a_sweep_that_ignores_the_frame_time_is_seen(tmp_path):
    broken = tmp_path / "broken.js"
    source = PLAY.read_text()
    bad = source.replace(
        "(Math.min(Math.max(dt, 0), LONGEST_FRAME) / SWEEP_SECONDS)", "(1 / 60 / SWEEP_SECONDS)"
    )
    assert bad != source
    broken.write_text(bad)
    got = run(tmp_path, broken)
    assert abs(got["sweep10"] - got["sweep"]) > 0.1
