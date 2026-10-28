# JSXGraph 1.14.1 (vendored, unmodified)

Source: the npm tarball `jsxgraph-1.14.1.tgz`, integrity
`sha512-TrjfzohP5hkw4ZYqFjxrPD3w7hjZFct8lqGv6RlbgyUoOqIw6Z2Io3q7nVpO+FPK7KEOfH/xcf0Y2xotoQQQMA==`
(the value `npm view jsxgraph@1.14.1 dist.integrity` prints, checked against the
downloaded file). The files here are copied byte for byte from the tarball:
`distrib/jsxgraphcore.js`, `distrib/jsxgraph.css`, `distrib/jsxgraphcore.js.LICENSE.txt`,
`LICENSE.MIT` and `LICENSE.LGPL`.

Licence: MIT or LGPL-3.0-or-later, at our choice (both texts are here).

Why it is safe under the app's Content-Security-Policy (no `unsafe-eval`):

- The bundle has one `eval(` and one `new Function`: the JessieCode compiler
  (option `JXG.Options.jc.compile`, default `true`) and a feature probe in a
  try/catch. `app/static/js/graph.js` sets `JXG.Options.jc.compile = false` before
  any board exists, and never hands JSXGraph a string to compile: every curve is a
  closure produced by `app/static/js/graph-spec.js`. Under the CSP a compiled string
  term would be silently replaced by an empty function, not run.
- JSXGraph inserts a text element's label as HTML, and the CSP allows inline event
  handler attributes. So no user text reaches it as a label: a name is an
  identifier (`[A-Za-z][A-Za-z0-9_]*`), drawn with `display: 'internal'` (SVG text).

To upgrade: download the new tarball, compare its integrity with the registry's, replace
these files, and run `tests/graph_draw.py` (see CONTRIBUTING.md) and `pytest tests/`.
