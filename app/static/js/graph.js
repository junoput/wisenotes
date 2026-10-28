/* Draws graph blocks (20261022-064, slice 2). Optional: without scripts the block
 * shows its definition as text, and so it does here whenever anything goes wrong.
 *
 * The definition text is parsed by graph-spec.js into closures; JSXGraph is only ever
 * handed closures and numbers, never a string to compile (JXG.Options.jc.compile is
 * false: under our Content-Security-Policy, which has no 'unsafe-eval', a compiled
 * term would silently become an empty function). A name is an identifier and is drawn
 * as SVG text (display: 'internal'): JSXGraph inserts HTML labels as markup, and our
 * policy allows inline event-handler attributes. Nothing here builds markup from user
 * text: the DOM is made with createElement and textContent. */
import { parse, newEnv } from '/static/js/graph-spec.js';
import { admitCurve, newWork, overBudget, settleWork } from '/static/js/graph-budget.js';

const JSX = '/static/vendor/jsxgraph';
const COLORS = ['--accent', '--color-code', '--color-math', '--color-chapter', '--danger'];
const HINT = 'Mouse: drag to pan, shift and scroll to zoom. Touch: one finger scrolls the page; two fingers pan, and pinching zooms.';
const boards = new Set(); // { figure, board, box, resize }

function palette() {
  const css = getComputedStyle(document.documentElement);
  const get = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  return {
    text: get('--text', '#e2e8f0'),
    muted: get('--muted', '#94a3b8'),
    border: get('--border', '#1f2937'),
    field: get('--field', '#0b1220'),
    curves: COLORS.map((name, i) => get(name, ['#22d3ee', '#f59e0b', '#a78bfa', '#0891b2', '#f87171'][i])),
  };
}

function el(tag, attrs = {}, text = null) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== null) node.textContent = text;
  return node;
}

/** A finite number, or NaN: JSXGraph leaves a gap at NaN, and Infinity would draw a line to nowhere. */
const finite = (v) => (Number.isFinite(v) ? v : NaN);

function drawBoard(box, spec, env, colors, label, work) {
  const JXG = window.JXG;
  const view = spec.view ?? { x: [-5, 5], y: [-5, 5] };
  const axis = { strokeColor: colors.muted, ticks: { strokeColor: colors.muted, label: { strokeColor: colors.muted } } };
  const board = JXG.JSXGraph.initBoard(box, {
    boundingbox: [view.x[0], view.y[1], view.x[1], view.y[0]],
    axis: true,
    defaultAxes: { x: axis, y: axis },
    grid: true,
    showCopyright: false,
    showNavigation: false,
    title: label, // the board's accessible name (JSXGraph sets the aria-label from it)
    keepAspectRatio: false,
    // Mouse: drag to pan, shift + wheel to zoom (a bare wheel must scroll the page).
    // Touch: two fingers pan and pinch zooms, so one finger still scrolls the page.
    pan: { enabled: true, needShift: false, needTwoFingers: true },
    zoom: { enabled: true, wheel: true, needShift: true, pinch: true, factorX: 1.25, factorY: 1.25 },
  });
  let n = 0;
  for (const [name, f] of spec.functions) {
    if (!admitCurve(work)) continue;
    board.create('functiongraph', [(x) => (overBudget(work) ? NaN : finite(f(x, env)))], {
      strokeColor: colors.curves[n++ % colors.curves.length],
      strokeWidth: 2,
      highlight: false,
      withLabel: false,
      fixed: true,
    });
  }
  for (const [name, [px, py]] of spec.points) {
    board.create('point', [() => (overBudget(work) ? NaN : finite(px(env))), () => (overBudget(work) ? NaN : finite(py(env)))], {
      name, // an identifier, by the grammar
      size: 3,
      fixed: true,
      showInfobox: false,
      strokeColor: colors.text,
      fillColor: colors.text,
      label: { display: 'internal', parse: false, useMathJax: false, useKatex: false, strokeColor: colors.text, fontSize: 13 },
    });
  }
  return board;
}

function sliderControls(spec, env, onChange) {
  const wrap = el('div', { class: 'graph-sliders' });
  for (const s of spec.sliders.values()) {
    const input = el('input', {
      type: 'range', min: String(s.lo), max: String(s.hi), step: s.step === null ? 'any' : String(s.step),
      value: String(s.value), 'aria-label': s.name,
    });
    const out = el('output', {}, String(s.value));
    env[s.name] = s.value;
    input.addEventListener('input', () => {
      env[s.name] = Number(input.value);
      out.textContent = String(Number(input.value));
      onChange();
    });
    const label = el('label', { class: 'graph-slider' });
    label.append(el('span', { class: 'graph-slider-name' }, s.name), input, out);
    wrap.append(label);
  }
  return wrap;
}

function describe(spec) {
  const names = [...spec.functions.keys(), ...spec.points.keys()];
  return names.length ? `Graph of ${names.join(', ')}` : 'Graph';
}

function showErrors(figure, errors) {
  figure.querySelector('.graph-errors')?.remove();
  // data-drawn marks the list the script made, so a check can tell it from the server's
  const list = el('ul', { class: 'graph-errors', role: 'alert', 'data-drawn': 'script' });
  for (const e of errors) list.append(el('li', {}, `line ${e.line}: ${e.message}`));
  figure.insertBefore(list, figure.querySelector('.graph-spec'));
}

function release(entry) {
  entry.resize?.disconnect();
  try { window.JXG?.JSXGraph.freeBoard(entry.board); } catch { /* the container is gone already */ }
  boards.delete(entry);
}

/** Draw every graph block on the page that is not drawn yet. `loadOnce` is app.js's loader. */
export async function renderGraphs(loadOnce) {
  for (const entry of [...boards]) if (!entry.figure.isConnected) release(entry);
  const todo = [...document.querySelectorAll('.graph-block-display')].filter((f) => !f._graph);
  if (!todo.length) return;
  const drawable = [];
  for (const figure of todo) {
    figure._graph = true;
    const source = figure.querySelector('.graph-spec')?.textContent ?? '';
    const spec = parse(source);
    if (spec.errors.length) { showErrors(figure, spec.errors); continue; }
    if (spec.functions.size + spec.points.size === 0) continue; // nothing to draw: the text stays
    drawable.push({ figure, spec });
  }
  if (!drawable.length) return;
  try {
    await loadOnce('link', { rel: 'stylesheet', href: `${JSX}/jsxgraph.css` });
    await loadOnce('script', { src: `${JSX}/jsxgraphcore.js` });
    window.JXG.Options.jc.compile = false; // before any board exists; see the header
    window.JXG.Options.curve.recursionDepthHigh = 10; // from 17: see MAX_EVALS
    window.JXG.Options.curve.recursionDepthLow = 8; // from 15
    window.JXG.Options.text.display = 'internal';
  } catch (err) {
    console.warn('JSXGraph unavailable, the definition stays as text', err);
    for (const { figure } of drawable) figure._graph = false;
    return;
  }
  const colors = palette();
  let first = true;
  for (const { figure, spec } of drawable) {
    // One task per board: a page of many blocks stays responsive while it is drawn.
    if (!first) await new Promise((resolve) => setTimeout(resolve, 0));
    first = false;
    // The page may have swapped while the library loaded or while earlier boards were drawn.
    if (!figure.isConnected) continue;
    let live = null;
    try {
      const env = newEnv();
      const work = newWork();
      // The block's view is a link that opens the editor, so the live graph goes beside
      // it, not inside it: a drag on a board must not be a click on a link, and a slider
      // is not content of an <a>.
      live = el('div', { class: 'graph-live' });
      const box = el('div', { class: 'graph-board' });
      let board = null;
      const hint = el('p', { class: 'graph-hint' }, HINT);
      // After every update of this board (pan, zoom, resize, slider, theme): say what was
      // left out of it, or nothing, and give the next update a fresh allowance.
      const settle = () => {
        const text = settleWork(work);
        const want = text ? `${text} ${HINT}` : HINT;
        if (hint.textContent !== want) hint.textContent = want;
      };
      const sliders = sliderControls(spec, env, () => board?.fullUpdate());
      live.append(box, sliders, hint);
      (figure.closest('.chapter-view') ?? figure).before(live);
      board = drawBoard(box, spec, env, colors, describe(spec), work);
      settle();
      board.on('update', settle); // after the first draw, which settles by hand
      const entry = { figure, board, box, extras: [live] };
      entry.resize = new ResizeObserver(() => board.resizeContainer(box.clientWidth, box.clientHeight, true));
      entry.resize.observe(box);
      boards.add(entry);
      figure.classList.add('graph-rendered');
      figure.querySelector('.graph-source-caption').textContent = 'Click here to edit the graph';
    } catch (err) {
      console.warn('graph block not drawn, its definition stays as text', err);
      live?.remove();
    }
  }
}

/** The palette is read when a board is drawn; draw them again when the theme changes. */
export function redrawOnThemeChange(loadOnce) {
  const redraw = () => {
    for (const entry of [...boards]) {
      entry.figure._graph = false;
      entry.figure.classList.remove('graph-rendered');
      release(entry);
      for (const part of entry.extras) part.remove();
    }
    renderGraphs(loadOnce);
  };
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw);
  new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}
