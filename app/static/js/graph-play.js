/* The motion of a playing slider (20261022-064, slice 3). No DOM, so node can run it
 * (tests/test_graph_play_js.py). A play sweeps from the low end to the high end and back,
 * one sweep in SWEEP_SECONDS, whatever the frame rate. */
export const SWEEP_SECONDS = 4;
const LONGEST_FRAME = 0.1; // seconds: a tab that was asleep does not jump a whole sweep

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
