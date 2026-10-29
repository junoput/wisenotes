/* The geometry of a graph block (20261022-064, slice 4): where the points, lines and circles
 * of a definition are for the current slider values. No DOM, so node can run it
 * (tests/test_graph_geometry_js.py); graph.js hands the numbers to JSXGraph.
 *
 * Every construction is worked out here, not by JSXGraph, so that what the text means does not
 * depend on the library: a segment stops at its ends (an intersection with a segment is only
 * where the segment is), a line does not, and "the second place two things meet" is the same
 * place whatever a slider does. A thing that does not exist for the current values (the
 * intersection of parallel lines, a circle of radius 0, anything built on a point that is
 * not a finite number) has the value null and is not drawn.
 *
 * Values: a point is [x, y]; a segment or a line is { p, q }; a circle is { c, r };
 * a polygon is { pts }. Which of two places is "first" is fixed by the text, not by the
 * numbers, so a point does not jump to the other place while a slider moves. With no number
 * written, intersection(a, b) is the first of the two places that exists (so it is a point
 * whenever the two meet at all, which for a segment from a circle's centre is its second):
 *   a line and a circle    the one nearer p along p -> q is first (the smaller t of p + t(q - p))
 *   two circles            the one to the left of the way from the first centre to the second
 *                          (which is where "left" is, with y up) is first. */

const TOLERANCE = 1e-9; // how far past a segment's end (as a part of its length) still counts as on it

const finite = (v) => Number.isFinite(v);
const point = (x, y) => (finite(x) && finite(y) ? [x, y] : null);

function onSegment(t) {
  return t >= -TOLERANCE && t <= 1 + TOLERANCE;
}

/** Where two straight things cross: null when they are parallel (or one is a single point). */
function lineLine(a, b) {
  const d1 = [a.q[0] - a.p[0], a.q[1] - a.p[1]];
  const d2 = [b.q[0] - b.p[0], b.q[1] - b.p[1]];
  const den = d1[0] * d2[1] - d1[1] * d2[0];
  if (Math.abs(den) <= 1e-12 * Math.hypot(...d1) * Math.hypot(...d2) || den === 0) return null;
  const w = [b.p[0] - a.p[0], b.p[1] - a.p[1]];
  const t = (w[0] * d2[1] - w[1] * d2[0]) / den;
  const u = (w[0] * d1[1] - w[1] * d1[0]) / den;
  if (a.kind === 'segment' && !onSegment(t)) return null;
  if (b.kind === 'segment' && !onSegment(u)) return null;
  return point(a.p[0] + t * d1[0], a.p[1] + t * d1[1]);
}

function lineCircle(l, c, index) {
  const d = [l.q[0] - l.p[0], l.q[1] - l.p[1]];
  const f = [l.p[0] - c.c[0], l.p[1] - c.c[1]];
  const A = d[0] * d[0] + d[1] * d[1];
  if (A === 0) return null;
  const B = 2 * (f[0] * d[0] + f[1] * d[1]);
  const C = f[0] * f[0] + f[1] * f[1] - c.r * c.r;
  let disc = B * B - 4 * A * C;
  // a line that touches the circle meets it in one place, which both indexes name
  if (disc < 0 && disc >= -1e-12 * (B * B + Math.abs(4 * A * C))) disc = 0;
  if (!(disc >= 0)) return null;
  const root = Math.sqrt(disc);
  const t = (-B + (index === 1 ? -root : root)) / (2 * A);
  if (l.kind === 'segment' && !onSegment(t)) return null;
  return point(l.p[0] + t * d[0], l.p[1] + t * d[1]);
}

function circleCircle(a, b, index) {
  const dx = b.c[0] - a.c[0];
  const dy = b.c[1] - a.c[1];
  const d = Math.hypot(dx, dy);
  if (d === 0) return null;
  const slack = 1e-12 * (a.r + b.r + d);
  if (d > a.r + b.r + slack || d < Math.abs(a.r - b.r) - slack) return null;
  const along = (a.r * a.r - b.r * b.r + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, a.r * a.r - along * along));
  const side = index === 1 ? h : -h;
  return point(a.c[0] + (along * dx - side * dy) / d, a.c[1] + (along * dy + side * dx) / d);
}

function intersect(a, b, index) {
  if (!a || !b) return null;
  if (index === null) return intersect(a, b, 1) ?? intersect(a, b, 2);
  if (a.kind === 'circle' && b.kind === 'circle') return circleCircle(a, b, index);
  if (a.kind === 'circle') return lineCircle(b, a, index);
  if (b.kind === 'circle') return lineCircle(a, b, index);
  return lineLine(a, b);
}

/** Work out every point and shape of `spec` for the sliders in `env`.
 * Returns { named: Map name -> value, shapes: [value, ...] } (shapes in the order of spec.shapes). */
export function solve(spec, env) {
  const named = new Map();
  for (const [name, [fx, fy]] of spec.points) named.set(name, point(fx(env), fy(env)));
  const shapes = [];
  for (const shape of spec.shapes) {
    const refs = shape.refs.map((r) => named.get(r) ?? null);
    let value = null;
    switch (shape.kind) {
      case 'segment':
      case 'line':
        if (refs[0] && refs[1] && (shape.kind === 'segment' || refs[0][0] !== refs[1][0] || refs[0][1] !== refs[1][1])) {
          value = { kind: shape.kind, p: refs[0], q: refs[1] };
        }
        break;
      case 'midpoint':
        if (refs[0] && refs[1]) value = point((refs[0][0] + refs[1][0]) / 2, (refs[0][1] + refs[1][1]) / 2);
        break;
      case 'circle': {
        if (!refs[0]) break;
        const r = shape.radius ? shape.radius(env) : refs[1] ? Math.hypot(refs[1][0] - refs[0][0], refs[1][1] - refs[0][1]) : NaN;
        if (finite(r) && r > 0) value = { kind: 'circle', c: refs[0], r };
        break;
      }
      case 'polygon':
        if (refs.every(Boolean)) value = { kind: 'polygon', pts: refs };
        break;
      case 'intersection':
        value = intersect(named.get(shape.refs[0]), named.get(shape.refs[1]), shape.index);
        break;
      default:
        break;
    }
    shapes.push(value);
    // objects are named by what they are: a point from midpoint(...) or intersection(...) is a
    // point to the statements below it, a segment or a circle is one to intersection(...)
    if (shape.name !== null) named.set(shape.name, value);
  }
  return { named, shapes };
}

/** `solve` for one board, kept until a slider moves: JSXGraph asks for each coordinate
 * of each element on its own, and they must not each re-solve the whole definition. */
export function geometry(spec, env) {
  const names = [...spec.sliders.keys()];
  let key = null;
  let solved = null;
  return () => {
    const now = names.map((n) => env[n]).join(' ');
    if (now !== key || solved === null) {
      solved = solve(spec, env);
      key = now;
    }
    return solved;
  };
}
