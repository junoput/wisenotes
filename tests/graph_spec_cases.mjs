// Runs tests/graph_spec_cases.json against app/static/js/graph-spec.js, the JS twin of
// app/graph_spec.py. Driven by tests/test_graph_spec_js.py, which copies graph-spec.js
// to a .mjs file first (Node reads .js as CommonJS unless a package.json says otherwise).
//
//   node tests/graph_spec_cases.mjs <graph-spec.mjs> <graph_spec_cases.json>
//
// Prints one JSON object: how many cases of each kind it ran, and the failures.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [, , modulePath, casesPath] = process.argv;
const spec = await import(pathToFileURL(modulePath).href);
const cases = JSON.parse(readFileSync(casesPath, 'utf8'));
const SPECIAL = { NaN: NaN, Infinity: Infinity, '-Infinity': -Infinity };

function same(got, want) {
  if (typeof want === 'string') want = SPECIAL[want];
  if (Number.isNaN(want)) return Number.isNaN(got);
  if (!Number.isFinite(want)) return got === want;
  return Math.abs(got - want) <= Math.max(1e-12 * Math.max(Math.abs(got), Math.abs(want)), 1e-12);
}

const ran = { values: 0, rejected: 0, specs: 0, checks: 0 };
const failures = [];
const fail = (kind, name, detail) => failures.push({ kind, name: String(name).slice(0, 60), detail: String(detail).slice(0, 200) });

for (const c of cases.values) {
  ran.values++;
  try {
    const got = spec.evaluate(c.expr, c.env);
    if (!same(got, c.value)) fail('value', c.expr, `got ${got}, want ${c.value}`);
  } catch (e) {
    fail('value', c.expr, `threw ${e.code ?? e}`);
  }
}

for (const c of cases.rejected) {
  ran.rejected++;
  try {
    spec.evaluate(c.expr, c.env);
    fail('rejected', c.expr, `accepted, want ${c.code}`);
  } catch (e) {
    if (e.code !== c.code) fail('rejected', c.expr, `code ${e.code ?? e}, want ${c.code}`);
  }
}

for (const c of cases.specs) {
  ran.specs++;
  let parsed;
  try {
    parsed = spec.parse(c.spec);
  } catch (e) {
    fail('spec', c.name, `parse threw ${e}`);
    continue;
  }
  const got = JSON.stringify(parsed.errors.map((e) => [e.line, e.code]));
  if (got !== JSON.stringify(c.errors)) fail('spec', c.name, `errors ${got}, want ${JSON.stringify(c.errors)}`);
  for (const check of c.checks ?? []) {
    ran.checks++;
    const env = spec.newEnv(check.env ?? {});
    if (check.view) {
      const v = parsed.view ?? { x: [-5, 5], y: [-5, 5] };
      if (JSON.stringify([v.x, v.y]) !== JSON.stringify([check.view.x, check.view.y])) fail('check', c.name, `view ${JSON.stringify([v.x, v.y])}`);
    } else if (check.function) {
      if (!same(parsed.functions.get(check.function)(check.x, env), check.value)) fail('check', c.name, 'function value');
    } else {
      const got2 = parsed.points.get(check.point).map((f) => f(env));
      if (!got2.every((g, i) => same(g, check.value[i]))) fail('check', c.name, `point ${got2}`);
    }
  }
}

console.log(JSON.stringify({ ran, failures }));
