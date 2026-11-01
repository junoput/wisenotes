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
import { admitCurve, creating, newWork, overBudget, settleWork } from '/static/js/graph-budget.js';
import { advance, nextFrameAt, snap } from '/static/js/graph-play.js';

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
    if (!admitCurve(work, name)) continue;
    creating(work, () => board.create('functiongraph', [(x) => (overBudget(work) ? NaN : finite(f(x, env)))], {
      strokeColor: colors.curves[n++ % colors.curves.length],
      strokeWidth: 2,
      highlight: false,
      withLabel: false,
      fixed: true,
    }));
  }
  for (const [name, c] of spec.curves) {
    if (!admitCurve(work, name)) continue;
    // x and y of a sample are one evaluation: x is charged, y follows x (a gap is a gap)
    creating(work, () => board.create(
      'curve',
      [(t) => (overBudget(work) ? NaN : finite(c.x(t, env))), (t) => (work.overran ? NaN : finite(c.y(t, env))), c.lo, c.hi],
      {
        strokeColor: colors.curves[n++ % colors.curves.length],
        strokeWidth: 2,
        highlight: false,
        withLabel: false,
        fixed: true,
      },
    ));
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

/** Is the board on the screen, in a tab that is shown? A play waits while it is not.
 * `listen(fn)` calls fn when that changes; `disconnect()` lets go of the observers. */
function watchPresence(node) {
  const listeners = new Set();
  let onScreen = true; // until the observer says otherwise
  const changed = () => listeners.forEach((fn) => fn());
  const observer = 'IntersectionObserver' in window
    ? new IntersectionObserver((seen) => { onScreen = seen[seen.length - 1].isIntersecting; changed(); })
    : null;
  observer?.observe(node);
  document.addEventListener('visibilitychange', changed);
  return {
    shown: () => onScreen && !document.hidden,
    listen: (fn) => listeners.add(fn),
    disconnect() { observer?.disconnect(); document.removeEventListener('visibilitychange', changed); listeners.clear(); },
  };
}

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** The sliders of a board, with a play button on those declared `play` (not offered when
 * the person asked for reduced motion). `reset()` puts every slider back to its declared
 * value; `values()` is what each shows now and `changed()` only those that differ from the
 * declared value. A play draws at most 30 frames a second and leaves at least half of the
 * time idle (graph-play.js), and waits while the board is off the screen or the tab is
 * hidden (`presence`, see watchPresence). */
function sliderControls(spec, env, onChange, presence) {
  const wrap = el('div', { class: 'graph-sliders' });
  const parts = [];
  for (const s of spec.sliders.values()) {
    const input = el('input', {
      type: 'range', min: String(s.lo), max: String(s.hi), step: s.step === null ? 'any' : String(s.step),
      value: String(s.value), 'aria-label': s.name,
    });
    const out = el('output', {}, String(s.value));
    env[s.name] = s.value;
    const show = () => {
      env[s.name] = Number(input.value);
      out.textContent = String(Number(input.value));
    };
    input.addEventListener('input', () => { show(); onChange(); });
    const label = el('label', { class: 'graph-slider' });
    label.append(el('span', { class: 'graph-slider-name' }, s.name), input, out);
    let stop = () => {};
    if (s.play && !reducedMotion()) {
      const button = el('button', { type: 'button', class: 'graph-play', 'aria-label': `Play ${s.name}`, 'aria-pressed': 'false' }, '\u25B6');
      let frame = null; // the pending animation frame; null while paused or stopped
      let wanted = false; // the person pressed play, and has not pressed pause
      let state = null;
      let last = null;
      let due = 0;
      const showState = (playing) => {
        button.setAttribute('aria-pressed', String(playing));
        button.setAttribute('aria-label', `${playing ? 'Pause' : 'Play'} ${s.name}`);
        button.textContent = playing ? '\u23F8' : '\u25B6';
      };
      const pause = () => { // not drawing, but still wanted: it goes on when the board is back
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
      };
      stop = () => { wanted = false; pause(); showState(false); };
      const tick = () => {
        // the clock of the page, not the frame's timestamp: a frame that is late (a slow
        // board) can carry the time it was meant to start, which would count its cost short
        const now = performance.now();
        frame = null;
        // gone from the page, or the person asked for less motion since: stop
        if (!input.isConnected || reducedMotion()) { stop(); return; }
        if (!presence.shown()) return; // paused; presence.listen starts it again
        if (now < due) { frame = requestAnimationFrame(tick); return; }
        state = advance(state, last === null ? 0 : (now - last) / 1000, s);
        last = now;
        input.value = String(snap(state.value, s));
        show();
        onChange();
        // What a frame costs is the redraw and what the browser does after it (layout and
        // paint come before the next frame), so the next frame is asked for at once and the
        // time it takes to arrive is the cost. A cheap board arrives in one 60 Hz frame
        // (about 17 ms), which the pacing allows.
        frame = requestAnimationFrame(() => {
          due = nextFrameAt(now, performance.now() - now);
          tick();
        });
      };
      const run = () => {
        if (!wanted || frame !== null || !presence.shown()) return;
        last = null; // the time it was away is not a frame
        due = 0;
        frame = requestAnimationFrame(tick);
      };
      presence.listen(() => (presence.shown() ? run() : pause()));
      button.addEventListener('click', () => {
        if (wanted) { stop(); return; }
        wanted = true;
        state = { value: Number(input.value), dir: Number(input.value) >= s.hi ? -1 : 1 };
        showState(true);
        run();
      });
      // touching the slider takes over
      input.addEventListener('pointerdown', stop);
      input.addEventListener('keydown', stop);
      label.append(button);
    }
    parts.push({ s, input, show, stop });
    wrap.append(label);
  }
  return {
    node: wrap,
    reset() { for (const { s, input, show, stop } of parts) { stop(); input.value = String(s.value); show(); } },
    values() { return parts.map(({ s, input }) => `${s.name}=${Number(input.value)}`); },
    changed() {
      return parts.filter(({ s, input }) => Number(input.value) !== s.value).map(({ s, input }) => `${s.name}=${Number(input.value)}`);
    },
    stop() { for (const { stop } of parts) stop(); },
  };
}

/** Reset view, and (when the page says where) Save view: the box on the screen and the
 * sliders' values go to the server, which writes them into the definition. */
function viewControls(figure, getBoard, view, sliders) {
  const bar = el('div', { class: 'graph-controls' });
  const reset = el('button', { type: 'button', class: 'graph-reset' }, 'Reset view');
  const status = el('span', { class: 'graph-status', role: 'status' });
  reset.addEventListener('click', () => {
    sliders.reset();
    getBoard().setBoundingBox([view.x[0], view.y[1], view.x[1], view.y[0]], false);
    getBoard().fullUpdate();
    status.textContent = '';
  });
  bar.append(reset);
  const url = figure.dataset.viewUrl;
  if (url && window.htmx) {
    const save = el('button', { type: 'button', class: 'graph-save' }, 'Save view');
    save.addEventListener('click', () => {
      const [x0, y1, x1, y0] = getBoard().getBoundingBox();
      status.textContent = 'Saving\u2026';
      window.htmx.ajax('POST', url, { source: save, target: 'body', swap: 'none', values: { x0, x1, y0, y1, slider: sliders.changed() } });
    });
    save.addEventListener('htmx:responseError', (e) => {
      status.textContent = `Not saved: ${e.detail.xhr.responseText || e.detail.xhr.status}`;
    });
    bar.append(save);
  }
  bar.append(status);
  return bar;
}

function describe(spec) {
  const names = [...spec.functions.keys(), ...spec.curves.keys(), ...spec.points.keys()];
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
  entry.stop?.();
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
    if (spec.functions.size + spec.curves.size + spec.points.size === 0) continue; // nothing to draw: the text stays
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
  let first = true;
  for (const { figure, spec } of drawable) {
    // One task per board: a page of many blocks stays responsive while it is drawn.
    if (!first) await new Promise((resolve) => setTimeout(resolve, 0));
    first = false;
    // The page may have swapped while the library loaded or while earlier boards were drawn.
    if (!figure.isConnected) continue;
    const colors = palette(); // this board's, read now: the theme may have changed while earlier boards were drawn
    let live = null;
    let presence = null; // watching the board, until it is released
    let sliders = null;
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
      presence = watchPresence(box);
      sliders = sliderControls(spec, env, () => board?.fullUpdate(), presence);
      const view = spec.view ?? { x: [-5, 5], y: [-5, 5] };
      const controls = viewControls(figure, () => board, view, sliders);
      live.append(box, sliders.node, controls, hint);
      (figure.closest('.chapter-view') ?? figure).before(live);
      board = drawBoard(box, spec, env, colors, describe(spec), work);
      settle();
      board.on('update', settle); // after the first draw, which settles by hand
      const entry = { figure, board, box, extras: [live], stop: () => { sliders.stop(); presence.disconnect(); } };
      entry.resize = new ResizeObserver(() => board.resizeContainer(box.clientWidth, box.clientHeight, true));
      entry.resize.observe(box);
      boards.add(entry);
      figure.classList.add('graph-rendered');
      figure.querySelector('.graph-source-caption').textContent = 'Click here to edit the graph';
    } catch (err) {
      console.warn('graph block not drawn, its definition stays as text', err);
      sliders?.stop();
      presence?.disconnect(); // its observer and its listener would outlive the board that never was
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
