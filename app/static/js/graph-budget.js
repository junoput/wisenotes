/* What one graph board may cost, and what it says when it left something out
 * (20261028-060). No DOM and no JSXGraph here, so node can run it
 * (tests/test_graph_budget_js.py).
 *
 * The cost of a drawing is bounded three times, per board (a board is drawn and updated
 * on its own, and the boards of a page are drawn one task apart, so one board never
 * spends another's allowance).
 *  - JSXGraph samples a curve adaptively, down to a recursion depth, so sin(1000000*x)
 *    would take it seconds of one task (default depths 17 and 15): graph.js lowers them.
 *  - A board gets MAX_EVALS function evaluations per update. Past that a function answers
 *    NaN (a gap), which JSXGraph handles cheaply. 50,000 is about 24 simple curves: a
 *    curve at depth 10/8 takes about 2,000 evaluations.
 *  - A board gets at most MAX_CURVES curves, and none is created once the allowance of
 *    the drawing is spent, because every curve costs JSXGraph work even when it only
 *    sees NaN (800 functions in one block took 5 s of long tasks on load, and per pan).
 * What was left out is said on that board's hint, and cleared when an update stays
 * inside the limits. */
export const MAX_EVALS = 50000;
export const MAX_CURVES = 24;

export function newWork() {
  return { spent: 0, overran: false, curves: 0, skipped: 0 };
}

/** Charge one evaluation to a board; true when the board is out of allowance. */
export function overBudget(work) {
  if (++work.spent <= MAX_EVALS) return false;
  work.overran = true;
  return true;
}

/** May another curve be created for this board? If not, it is counted as left out. */
export function admitCurve(work) {
  if (work.curves >= MAX_CURVES || work.spent >= MAX_EVALS) {
    work.skipped++;
    return false;
  }
  work.curves++;
  return true;
}

/** What a board left out, for its hint; '' when nothing. */
export function leftOutText(work) {
  const parts = [];
  if (work.skipped) parts.push(`Only the first ${work.curves} of ${work.curves + work.skipped} curves are drawn.`);
  if (work.overran) parts.push('Part of a graph is left out: it takes too much work.');
  return parts.join(' ');
}

/** After an update of the board: what to say about it, and a fresh allowance for the next one.
 *  The curves that were skipped at the first draw stay skipped, and stay said. */
export function settleWork(work) {
  const text = leftOutText(work);
  work.spent = 0;
  work.overran = false;
  return text;
}
