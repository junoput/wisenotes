/* What one graph board may cost, and what it says when it left something out
 * (20261028-060). No DOM and no JSXGraph here, so node can run it
 * (tests/test_graph_budget_js.py).
 *
 * The cost of a drawing is bounded three times, per board (a board is drawn and updated
 * on its own, and the boards of a page are drawn one task apart, so one board never
 * spends another's allowance).
 *  - JSXGraph samples a curve adaptively, down to a recursion depth, so sin(1000000*x)
 *    would take it seconds of one task (default depths 17 and 15): graph.js lowers them.
 *  - A board gets MAX_EVALS evaluations per update, one for each sample of a curve (a
 *    parametric curve's x and y are one sample, counted once, in x). Past that a curve
 *    answers NaN (a gap), which JSXGraph handles cheaply. Measured in Chromium with
 *    JSXGraph 1.14.1 at depth 10/8: a simple function and a parametric circle each take
 *    about 1,025 samples per update (the circle's x and y calls make 2,050 calls), so
 *    50,000 is 24 curves of either kind with room for curves that sample more.
 *    JSXGraph evaluates a curve twice when it CREATES it (2,050 samples each), so a
 *    curve being created is charged at half (CREATION_WEIGHT): the allowance is for one
 *    update, and the twentieth circle is not drawn with gaps because the nineteen
 *    before it were made.
 *  - A board gets at most MAX_CURVES curves, and none is created once the allowance of
 *    the drawing is spent, because every curve costs JSXGraph work even when it only
 *    sees NaN (800 functions in one block took 5 s of long tasks on load, and per pan).
 * What was left out is said on that board's hint, and cleared when an update stays
 * inside the limits. */
export const MAX_EVALS = 50000;
export const MAX_CURVES = 24;
export const CREATION_WEIGHT = 0.5;
const NAMED = 5; // curves named in the hint; the rest are counted

export function newWork() {
  return { spent: 0, weight: 1, overran: false, curves: 0, skipped: [] };
}

/** Charge one evaluation to a board; true when the board is out of allowance. While a
 * curve is being created (`work.weight` is CREATION_WEIGHT) it costs half. */
export function overBudget(work) {
  work.spent += work.weight;
  if (work.spent <= MAX_EVALS) return false;
  work.overran = true;
  return true;
}

/** Run `create` (the board.create of one curve) with its evaluations charged at the
 * creation weight. */
export function creating(work, create) {
  work.weight = CREATION_WEIGHT;
  try { return create(); } finally { work.weight = 1; }
}

/** May another curve, called `name`, be created for this board? If not, it is left out. */
export function admitCurve(work, name) {
  if (work.curves >= MAX_CURVES || work.spent >= MAX_EVALS) {
    work.skipped.push(name);
    return false;
  }
  work.curves++;
  return true;
}

/** What a board left out, for its hint; '' when nothing. The curves are drawn in the order
 * of the definition (functions, then parametric curves), and the ones left out are named. */
export function leftOutText(work) {
  const parts = [];
  if (work.skipped.length) {
    const named = work.skipped.slice(0, NAMED).join(', ');
    const more = work.skipped.length > NAMED ? ` and ${work.skipped.length - NAMED} more` : '';
    parts.push(
      `Only the first ${work.curves} of ${work.curves + work.skipped.length} curves are drawn, in the order of the definition (functions, then curves); left out: ${named}${more}.`,
    );
  }
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
