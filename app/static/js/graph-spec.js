/* The graph block's definition language, JS side (20261022-064, slice 2).
 *
 * A port of app/graph_spec.py. Both run tests/graph_spec_cases.json, which pins the
 * values, the error codes and the lines; read that file and the docstring of the
 * Python module for the rules. In short: one statement per line, numbers, + - * / ^,
 * parentheses, the functions in FUNCTIONS, the constants pi and e, the sliders and
 * functions above the line, and x inside f(x) = ... . ASCII only; blanks are space,
 * tab and carriage return; lines split on "\n" only.
 *
 * USER TEXT IS NEVER EVALUATED AS CODE: no eval, no Function, no JessieCode. An
 * expression is parsed by the recursive descent below into closures. Names live in
 * Maps and in prototype-less objects, so a name such as constructor or toString is
 * only ever what the definition made it.
 *
 * Do not use \s, \d, String.trim() or "." in a pattern without the s flag here: JS's
 * \s and trim() take U+00A0, U+2028 and more, and "." stops at U+2028.
 */

export const MAX_DEPTH = 64;
export const MAX_TOKENS = 256;
// What one evaluation may cost: an expression's tokens plus the cost of each user function it
// calls. Bounds chains of functions calling functions and a function calling another twice at
// every level; the drawing code calls a function hundreds of times per frame.
export const MAX_COST = 512;
const BLANK = ' \t\r';

// name -> [arity, implementation]. Math.* already gives the JS values the cases pin:
// Math.log(0) is -Infinity, Math.floor(Infinity) is Infinity, Math.min(1, NaN) is NaN.
export const FUNCTIONS = new Map([
  ['sin', [1, Math.sin]],
  ['cos', [1, Math.cos]],
  ['tan', [1, Math.tan]],
  ['asin', [1, Math.asin]],
  ['acos', [1, Math.acos]],
  ['atan', [1, Math.atan]],
  ['atan2', [2, Math.atan2]],
  ['sqrt', [1, Math.sqrt]],
  ['abs', [1, Math.abs]],
  ['exp', [1, Math.exp]],
  ['ln', [1, Math.log]],
  ['log', [1, Math.log10]],
  ['floor', [1, Math.floor]],
  ['ceil', [1, Math.ceil]],
  ['min', [2, Math.min]],
  ['max', [2, Math.max]],
]);
export const CONSTANTS = new Map([['pi', Math.PI], ['e', Math.E]]);
export const VARIABLES = ['x', 'y', 't', 'u', 'v'];
export const KEYWORDS = ['view', 'slider', 'step', 'value', 'play', 'in'];
const RESERVED = new Set([...FUNCTIONS.keys(), ...CONSTANTS.keys(), ...VARIABLES, ...KEYWORDS]);

const NAME = /[A-Za-z][A-Za-z0-9_]*/y;
const NUMBER = /(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)/y;
const NUMBER_FULL = /^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$/;
const NAME_FULL = /^[A-Za-z][A-Za-z0-9_]*$/;

class Refused extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

const strip = (s) => {
  let a = 0;
  let b = s.length;
  while (a < b && BLANK.includes(s[a])) a++;
  while (b > a && BLANK.includes(s[b - 1])) b--;
  return s.slice(a, b);
};

// ---------------------------------------------------------------- expressions

function tokens(text) {
  const out = [];
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (BLANK.includes(ch)) { i++; continue; }
    NUMBER.lastIndex = i;
    let m = NUMBER.exec(text);
    if (m) { out.push(m[0]); i += m[0].length; continue; }
    NAME.lastIndex = i;
    m = NAME.exec(text);
    if (m) { out.push(m[0]); i += m[0].length; continue; }
    if ('+-*/^(),'.includes(ch)) { out.push(ch); i++; continue; }
    throw new Refused('character', `'${ch}' is not part of the graph language`);
  }
  if (out.length > MAX_TOKENS) {
    throw new Refused('too_long', `longer than ${MAX_TOKENS} symbols; split it into parts`);
  }
  return out;
}

// JS's own Math.pow is what the cases pin: a NaN exponent and 1 ** Infinity are NaN,
// 0 ** -1 is Infinity and (-0) ** -1 is -Infinity, an overflow keeps the sign of an odd
// power. (Python needs a function for each of these; here it is the one call.)
const pow = (a, b) => Math.pow(a, b);

class Parser {
  constructor(toks, values, functions, others) {
    this.tokens = toks;
    this.pos = 0;
    this.values = values; // Set: names an expression may read (sliders, bound variables)
    this.functions = functions; // Map: user functions defined above, name -> (x, env) => number
    this.others = others; // Map: names defined as something that is not a number -> what
    this.depth = 0;
    this.cost = toks.length;
  }

  peek() { return this.pos < this.tokens.length ? this.tokens[this.pos] : null; }

  take() { return this.tokens[this.pos++]; }

  expect(tok) {
    if (this.peek() !== tok) {
      if (tok === ')' && this.peek() === null) throw new Refused('unclosed', "a '(' is not closed");
      throw new Refused('unexpected', `expected '${tok}' here`);
    }
    this.pos++;
  }

  parse() {
    if (!this.tokens.length) throw new Refused('empty', 'an expression is missing');
    const node = this.expr();
    if (this.peek() !== null) {
      if (this.peek() === ')') throw new Refused('unexpected', "a ')' has no matching '('");
      throw new Refused('unexpected', 'two values without an operator between them (write 2*x, not 2x)');
    }
    if (this.cost > MAX_COST) {
      throw new Refused('too_costly', 'this, with the functions it calls, is too long to evaluate');
    }
    node.cost = this.cost;
    return node;
  }

  enter() {
    if (++this.depth > MAX_DEPTH) {
      throw new Refused('too_deep', `nested more than ${MAX_DEPTH} levels deep`);
    }
  }

  expr() {
    let node = this.term();
    while (this.peek() === '+' || this.peek() === '-') {
      const op = this.take();
      const a = node;
      const b = this.term();
      node = op === '+' ? (env) => a(env) + b(env) : (env) => a(env) - b(env);
    }
    return node;
  }

  term() {
    let node = this.unary();
    while (this.peek() === '*' || this.peek() === '/') {
      const op = this.take();
      const a = node;
      const b = this.unary();
      node = op === '*' ? (env) => a(env) * b(env) : (env) => a(env) / b(env);
    }
    return node;
  }

  unary() {
    if (this.peek() === '-' || this.peek() === '+') {
      const op = this.take();
      this.enter();
      const inner = this.unary();
      this.depth--;
      return op === '-' ? (env) => -inner(env) : inner;
    }
    return this.power();
  }

  power() {
    const base = this.atom();
    if (this.peek() === '^') {
      this.take();
      this.enter();
      const exponent = this.unary();
      this.depth--;
      return (env) => pow(base(env), exponent(env));
    }
    return base;
  }

  atom() {
    const tok = this.peek();
    if (tok === null) throw new Refused('empty', 'an operator is missing its right-hand side');
    if (NUMBER_FULL.test(tok)) {
      this.take();
      const value = Number(tok);
      return () => value;
    }
    if (tok === '(') {
      this.take();
      this.enter();
      const inner = this.expr();
      this.expect(')');
      this.depth--;
      return inner;
    }
    if (NAME_FULL.test(tok)) {
      this.take();
      return this.peek() === '(' ? this.call(tok) : this.name(tok);
    }
    if (tok === ')') throw new Refused('unexpected', "a ')' has no matching '('");
    throw new Refused('unexpected', `'${tok}' cannot start a value`);
  }

  name(name) {
    if (CONSTANTS.has(name)) {
      const value = CONSTANTS.get(name);
      return () => value;
    }
    if (this.values.has(name)) return (env) => env[name];
    if (FUNCTIONS.has(name) || this.functions.has(name)) {
      throw new Refused('not_a_value', `${name} is a function: call it, as ${name}(...)`);
    }
    if (this.others.has(name)) {
      throw new Refused('not_a_value', `${name} is ${this.others.get(name)}, not a number`);
    }
    if (VARIABLES.includes(name)) throw new Refused('variable', `${name} is not a variable here`);
    throw new Refused('unknown_name', `${name} is not defined above this line`);
  }

  call(name) {
    this.take(); // "("
    this.enter();
    const args = [];
    if (this.peek() === null) throw new Refused('unclosed', "a '(' is not closed");
    if (this.peek() !== ')') {
      args.push(this.expr());
      while (this.peek() === ',') {
        this.take();
        args.push(this.expr());
      }
    }
    this.expect(')');
    this.depth--;
    if (FUNCTIONS.has(name)) {
      const [arity, fn] = FUNCTIONS.get(name);
      if (args.length !== arity) {
        throw new Refused('arity', `${name} takes ${arity} argument${arity > 1 ? 's' : ''}`);
      }
      if (arity === 1) { const [a] = args; return (env) => fn(a(env)); }
      const [a, b] = args;
      return (env) => fn(a(env), b(env));
    }
    if (this.functions.has(name)) {
      if (args.length !== 1) throw new Refused('arity', `${name} takes 1 argument`);
      const user = this.functions.get(name);
      this.cost += user.cost;
      const [a] = args;
      return (env) => user(a(env), env);
    }
    if (this.values.has(name) || this.others.has(name) || CONSTANTS.has(name)) {
      throw new Refused('not_a_function', `${name} is not a function`);
    }
    throw new Refused('unknown_function', `${name} is not a known function`);
  }
}

/** Compile one expression to a closure taking an env: a prototype-less object holding
 * the values of `values` by name. Throws an Error with a .code when it is refused. */
export function compileExpression(text, values = [], functions = new Map(), others = new Map()) {
  try {
    return new Parser(tokens(text), new Set(values), functions, others).parse();
  } catch (e) {
    if (e instanceof Refused) {
      const err = new Error(e.message);
      err.code = e.code;
      throw err;
    }
    throw e;
  }
}

export const newEnv = (values = {}) => Object.assign(Object.create(null), values);

/** The value of a constant expression, or one over the names in `env`. */
export function evaluate(text, env = {}) {
  const e = newEnv(env);
  return compileExpression(text, Object.keys(e))(e);
}

// ---------------------------------------------------------------- statements

const B = '[ \\t\\r]*';
const N = '[A-Za-z][A-Za-z0-9_]*';
const FUNCTION_DEF = new RegExp(`^(${N})${B}\\(${B}(${N})${B}\\)${B}=(.*)$`, 's');
const ASSIGN = new RegExp(`^(${N})${B}=(.*)$`, 's');
const SLIDER = new RegExp(`^slider${B}\\((.*)\\)${B}$`, 's');
const POINT = new RegExp(`^\\((.*)\\)${B}$`, 's');

function splitTop(text) {
  const parts = [];
  let depth = 0;
  let cur = '';
  for (const ch of text) {
    if (ch === '(') depth++;
    else if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; } else cur += ch;
  }
  parts.push(cur);
  return parts;
}

class Checker {
  constructor() {
    this.spec = { view: null, sliders: new Map(), functions: new Map(), points: new Map(), errors: [] };
    this.kinds = new Map(); // every name defined, and what it is
  }

  constant(text) {
    const others = new Map([...this.kinds].map(([n, k]) => [n, `a ${k}`]));
    let value;
    try {
      value = compileExpression(text, [], new Map(), others)(newEnv());
    } catch (e) {
      if (e.code === undefined) throw e;
      if (['unknown_name', 'not_a_value', 'variable'].includes(e.code)) {
        throw new Refused('constant', 'must be a plain number here, not a name');
      }
      throw new Refused(e.code, e.message);
    }
    if (!Number.isFinite(value)) throw new Refused('constant', 'must be a finite number');
    return value;
  }

  expression(text, variable = null) {
    const values = [...this.kinds].filter(([, k]) => k === 'slider').map(([n]) => n);
    if (variable) values.push(variable);
    const others = new Map(
      [...this.kinds].filter(([, k]) => k !== 'slider' && k !== 'function').map(([n, k]) => [n, `a ${k}`]),
    );
    try {
      return compileExpression(text, values, this.spec.functions, others);
    } catch (e) {
      if (e.code === undefined) throw e;
      throw new Refused(e.code, e.message);
    }
  }

  define(name, kind) {
    if (RESERVED.has(name)) throw new Refused('reserved', `${name} is a reserved word and cannot be defined`);
    if (this.kinds.has(name)) throw new Refused('redefined', `${name} is already defined above`);
    this.kinds.set(name, kind);
  }

  line(text) {
    const stripped = strip(text.split('#')[0]);
    if (!stripped) return;
    if (stripped === 'view' || /^view[ \t\r]/.test(stripped)) return this.view(stripped);
    let m = FUNCTION_DEF.exec(stripped);
    if (m) return this.function(m[1], m[2], m[3]);
    m = ASSIGN.exec(stripped);
    if (m) {
      const name = m[1];
      const rhs = strip(m[2]);
      const s = SLIDER.exec(rhs);
      if (s) return this.slider(name, s[1]);
      const p = POINT.exec(rhs);
      if (p && splitTop(p[1]).length > 1) return this.point(name, p[1]);
      throw new Refused('statement', `${name} = ... must be a slider(...) or a point (x, y)`);
    }
    throw new Refused(
      'statement',
      'not a statement: expected view, a slider, a function f(x) = ... or a point P = (x, y)',
    );
  }

  view(text) {
    if (this.spec.view !== null) throw new Refused('view_twice', 'only one view line is allowed');
    const words = text.split(/[ \t\r]+/).filter((w) => w);
    if (words.length < 2) throw new Refused('view_kind', 'view needs a kind: view 2d');
    if (words[1] !== '2d') throw new Refused('view_kind', 'only view 2d is supported so far');
    const view = { kind: '2d', x: [-5, 5], y: [-5, 5] };
    const rest = words.slice(2);
    const seen = new Set();
    while (rest.length) {
      const axis = rest.shift();
      if (axis !== 'x' && axis !== 'y') {
        throw new Refused('view_option', 'a 2d view takes x and y ranges, as x -5..5');
      }
      if (seen.has(axis)) throw new Refused('view_option', `the ${axis} range is given twice`);
      if (!rest.length) throw new Refused('view_range', `${axis} needs a range, as ${axis} -5..5`);
      const word = rest.shift();
      const at = word.indexOf('..');
      if (at < 0) throw new Refused('view_range', `${axis} needs a range, as ${axis} -5..5`);
      const lo = this.constant(word.slice(0, at));
      const hi = this.constant(word.slice(at + 2));
      if (!(lo < hi)) throw new Refused('view_range', `the ${axis} range must go from low to high`);
      view[axis] = [lo, hi];
      seen.add(axis);
    }
    this.spec.view = view;
  }

  slider(name, argsText) {
    const args = splitTop(argsText).map(strip);
    if (args.length < 2 || !args[0] || !args[1]) {
      throw new Refused('slider_range', 'slider needs a low and a high end: slider(0, 5)');
    }
    const lo = this.constant(args[0]);
    const hi = this.constant(args[1]);
    if (!(lo < hi)) throw new Refused('slider_range', 'the slider must go from low to high');
    let step = null;
    let value = null;
    let play = false;
    for (const opt of args.slice(2)) {
      const at = opt.indexOf(' ');
      const word = at < 0 ? opt : opt.slice(0, at);
      const rest = at < 0 ? '' : opt.slice(at + 1);
      if (word === 'play' && !strip(rest)) {
        if (play) throw new Refused('slider_option', 'play is given twice');
        play = true;
      } else if ((word === 'step' || word === 'value') && strip(rest)) {
        if ((word === 'step' ? step : value) !== null) {
          throw new Refused('slider_option', `${word} is given twice`);
        }
        const number = this.constant(rest);
        if (word === 'step') step = number; else value = number;
      } else {
        throw new Refused('slider_option', 'a slider option is step <number>, value <number> or play');
      }
    }
    if (step !== null && !(step > 0 && step <= hi - lo)) {
      throw new Refused('slider_step', "the step must be above 0 and at most the slider's span");
    }
    if (value !== null && !(lo <= value && value <= hi)) {
      throw new Refused('slider_value', "the value must be within the slider's range");
    }
    this.define(name, 'slider');
    this.spec.sliders.set(name, { name, lo, hi, step, value: value === null ? lo : value, play });
  }

  function(name, variable, body) {
    if (variable !== 'x') throw new Refused('function_variable', `a function is written ${name}(x) = ...`);
    if (FUNCTIONS.has(name)) throw new Refused('reserved', `${name} is a built-in function and cannot be redefined`);
    const compiled = this.expression(strip(body), 'x');
    this.define(name, 'function');
    const fn = (x, env) => {
      const inner = Object.create(env); // env's sliders, and x here only
      inner.x = x;
      return compiled(inner);
    };
    fn.cost = compiled.cost;
    this.spec.functions.set(name, fn);
  }

  point(name, inner) {
    const coords = splitTop(inner).map(strip);
    if (coords.length !== 2) throw new Refused('point', 'a point has two coordinates: P = (x, y)');
    const compiled = coords.map((c) => this.expression(c));
    this.define(name, 'point');
    this.spec.points.set(name, compiled);
  }
}

/** Parse a whole definition. Every refused line is reported with its 1-based line
 * number; a refused line defines nothing, so a later line using its name is reported too. */
export function parse(text) {
  const checker = new Checker();
  text.split('\n').forEach((line, i) => {
    try {
      checker.line(line);
    } catch (e) {
      if (e instanceof Refused) {
        checker.spec.errors.push({ line: i + 1, code: e.code, message: e.message });
      } else if (e instanceof RangeError) { // a stack overflow: never an uncaught error
        checker.spec.errors.push({ line: i + 1, code: 'too_deep', message: 'nested or chained too deeply to check' });
      } else {
        throw e;
      }
    }
  });
  return checker.spec;
}

export const validate = (text) => parse(text).errors;
