/* The motion of a playing slider (20261022-064, slice 3). No DOM, so node can run it
 * (tests/test_graph_play_js.py). A play sweeps from the low end to the high end and back,
 * one sweep in SWEEP_SECONDS, whatever the frame rate. */
export const SWEEP_SECONDS = 4;
const LONGEST_FRAME = 0.5; // seconds: a frame this late (or later) moves the slider no further
export const FRAME_MS = 1000 / 30; // a play draws at most 30 frames a second
const BUSY_AT_MOST = 0.5; // and leaves at least half of the time to the page

/** When the next frame of a play may start, given when the last one started and what it
 * cost (ms: the redraw and the browser's layout and paint after it). A board whose frame
 * takes 80 ms is redrawn every 160 ms, not back to back:
 * the sweep keeps its 4 s (a frame moves the slider by the time since the last one, up to
 * LONGEST_FRAME), only choppier, and the tab stays usable. */
export function nextFrameAt(startedAt, costMs) {
  return startedAt + Math.max(FRAME_MS, costMs / BUSY_AT_MOST);
}

/** One frame. `state` is { value, dir } (dir is 1 or -1), `dt` seconds, `range` { lo, hi }. */
export function advance(state, dt, { lo, hi }) {
  const span = hi - lo;
  let value = state.value + state.dir * span * (Math.min(Math.max(dt, 0), LONGEST_FRAME) / SWEEP_SECONDS);
  let dir = state.dir;
  if (value >= hi) { value = hi - (value - hi); dir = -1; }
  else if (value <= lo) { value = lo + (lo - value); dir = 1; }
  return { value: Math.min(hi, Math.max(lo, value)), dir };
}

/** The value a slider shows for a position: on its step grid when it has one. */
export function snap(value, { lo, hi, step }) {
  if (!step) return Math.min(hi, Math.max(lo, value));
  return Math.min(hi, Math.max(lo, lo + Math.round((value - lo) / step) * step));
}
