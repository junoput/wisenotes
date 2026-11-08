/* The picture of a graph block's default view (20261022-064, slice 5). Optional: it is
 * what a page without scripts, and paper, show in place of the drawing.
 *
 * After a board is drawn, a graph whose page says it has no picture (no data-has-snapshot)
 * is drawn once more, off screen: the default view (the box and the slider values the
 * definition declares), in the light palette, at twice the size, on white. That is sent
 * to the server, which names the file after the definition (app/graph_snapshot.py). The
 * page names the definition it drew (data-spec-hash); the server refuses a picture of a
 * definition that has changed since. Nothing here is retried: a failure leaves the block
 * as it was, with its text, and the next draw of the page tries once more.
 *
 * The picture goes through canvas.toBlob, not through a data URL in the page, and nothing
 * the person typed reaches the DOM here. */

export const WIDTH = 640;
export const HEIGHT = 400;
const SCALE = 2;
const STAGE = 'position:fixed;left:-10000px;top:0;pointer-events:none;';

/** The light theme of style.css, spelled out: the picture is the same whichever theme the
 * page is in, and white is what paper is. `curves` follows graph.js's COLORS order. */
export const LIGHT = {
  text: '#0f172a',
  muted: '#64748b',
  border: '#cbd5e1',
  field: '#ffffff',
  curves: ['#0e7490', '#d97706', '#7c3aed', '#0891b2', '#b91c1c'],
};

let counter = 0;

/** A PNG Blob of the board `build(host)` draws, or null when the browser cannot make one.
 * `build` gets an empty box of WIDTH x HEIGHT and returns the JSXGraph board it drew in it. */
export async function pictureOf(JXG, build) {
  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = `${STAGE}width:${WIDTH}px;height:${HEIGHT}px;`;
  const canvas = document.createElement('canvas');
  canvas.id = `graph-picture-${++counter}`;
  canvas.style.display = 'none';
  document.body.append(host, canvas);
  let board = null;
  try {
    board = build(host);
    // JSXGraph draws the board's SVG into the canvas at the size given; it has no background
    await board.renderer.dumpToCanvas(canvas.id, WIDTH * SCALE, HEIGHT * SCALE);
    const flat = document.createElement('canvas');
    flat.width = WIDTH * SCALE;
    flat.height = HEIGHT * SCALE;
    const ctx = flat.getContext('2d');
    ctx.fillStyle = LIGHT.field;
    ctx.fillRect(0, 0, flat.width, flat.height);
    ctx.drawImage(canvas, 0, 0);
    return await new Promise((resolve) => flat.toBlob(resolve, 'image/png'));
  } finally {
    if (board) {
      try { JXG.JSXGraph.freeBoard(board); } catch { /* the box is gone already */ }
    }
    host.remove();
    canvas.remove();
  }
}

/** Does this figure still need a picture from this page? */
export function needsPicture(figure) {
  return Boolean(figure.dataset.snapshotUrl && figure.dataset.specHash)
    && !figure.hasAttribute('data-has-snapshot')
    && !figure._pictured;
}

/** Send the picture of the definition `figure` was drawn from. True when the server stored it. */
export async function sendPicture(figure, blob) {
  const form = new FormData();
  form.set('spec', figure.dataset.specHash);
  form.set('image', blob, 'snapshot.png');
  const response = await fetch(figure.dataset.snapshotUrl, { method: 'POST', body: form });
  if (response.status === 204) {
    figure.setAttribute('data-has-snapshot', '');
    return true;
  }
  // 409: the definition changed while it was drawn; the page is about to be drawn again
  if (response.status !== 409) console.warn('graph picture not stored', response.status, (await response.text()).slice(0, 200));
  return false;
}
