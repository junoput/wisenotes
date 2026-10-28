"""The JS twin of the graph spec parser runs the same cases as the Python one (20261022-064).

app/static/js/graph-spec.js is what draws a graph in the browser. The shared cases
(tests/graph_spec_cases.json) are the contract between it and app/graph_spec.py, so the
two cannot drift apart without a test going red. Needs `node` (CI's ubuntu runner has it).
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app/static/js"
CASES = Path(__file__).parent / "graph_spec_cases.json"
RUNNER = Path(__file__).parent / "graph_spec_cases.mjs"


def node(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    exe = shutil.which("node")
    assert exe, "node is required to run the JS parser against the shared cases"
    return subprocess.run([exe, *args], capture_output=True, text=True, check=False, cwd=cwd)


def run_cases(tmp_path: Path, source: Path = JS / "graph-spec.js") -> dict:
    module = tmp_path / "graph-spec.mjs"
    module.write_text(source.read_text())
    r = node(str(RUNNER), str(module), str(CASES), cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def test_the_js_parser_passes_every_shared_case(tmp_path):
    result = run_cases(tmp_path)
    cases = json.loads(CASES.read_text())
    # the instrument saw every case: a runner that ran nothing passes vacuously
    assert result["ran"]["values"] == len(cases["values"]) >= 60
    assert result["ran"]["rejected"] == len(cases["rejected"]) >= 40
    assert result["ran"]["specs"] == len(cases["specs"]) >= 50
    assert result["ran"]["checks"] == sum(len(s.get("checks", [])) for s in cases["specs"]) >= 3
    assert result["failures"] == []


def test_harness_control_the_runner_reports_a_wrong_value(tmp_path):
    # the runner can see a failure: break one function and it must say so
    source = (JS / "graph-spec.js").read_text()
    broken = source.replace("['sqrt', [1, Math.sqrt]]", "['sqrt', [1, Math.cbrt]]")
    assert broken != source
    bad = tmp_path / "broken.js"
    bad.write_text(broken)
    result = run_cases(tmp_path, bad)
    assert any(f["name"] == "sqrt(16)" for f in result["failures"]), result["failures"]


# What the spike called the gotchas of a JS port: names that exist on every object.
@pytest.mark.parametrize(
    "name", ["constructor", "toString", "hasOwnProperty", "valueOf", "prototype"]
)
def test_a_name_that_every_js_object_has_is_just_a_name(tmp_path, name):
    probe = tmp_path / "probe.mjs"
    module = tmp_path / "graph-spec.mjs"
    module.write_text((JS / "graph-spec.js").read_text())
    probe.write_text(
        f"""
import * as s from './graph-spec.mjs';
const out = {{}};
out.undefined_is_unknown = s.validate('P = ({name}, 1)').map((e) => e.code);
const ok = s.parse('{name} = slider(0, 4, value 3)\\nf(x) = {name}*x\\nP = ({name}, f(2))');
out.defined = ok.errors.length;
out.value = ok.functions.get('f')(2, Object.assign(Object.create(null), {{{name}: 3}}));
out.call = s.validate('f(x) = {name}(x)').map((e) => e.code);
console.log(JSON.stringify(out));
"""
    )
    r = node(str(probe), cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    got = json.loads(r.stdout)
    assert got == {
        "undefined_is_unknown": ["unknown_name"],
        "defined": 0,
        "value": 6,
        "call": ["unknown_function"],
    }


def code_of(name: str) -> str:
    """The source without full-line comments, so a rule written in a comment is not a hit."""
    return "\n".join(
        ln
        for ln in (JS / name).read_text().splitlines()
        if not ln.strip().startswith(("//", "*", "/*"))
    )


SINKS = re.compile(
    r"(?<![\w.$])(?:eval|Function)\s*\(|new\s+Function|\.(?:innerHTML|outerHTML)\s*=|insertAdjacentHTML"
    r"|document\.write|set(?:Timeout|Interval)\s*\(\s*['\"`]"
)


def test_the_js_sources_never_evaluate_user_text_or_build_markup():
    for name in ("graph-spec.js", "graph.js", "graph-budget.js"):
        assert SINKS.findall(code_of(name)) == [], name
    # the check can see each kind of sink
    for probe in (
        "eval(t)",
        "new Function(t)",
        "el.innerHTML = t",
        "x.insertAdjacentHTML('a', t)",
        "setTimeout('f()', 1)",
    ):
        assert SINKS.search(probe), probe


def test_jsxgraph_is_told_to_not_compile_before_any_board_exists():
    code = code_of("graph.js")
    assert "JXG.Options.jc.compile = false" in code
    # by execution order, not by text: drawBoard is defined above the code that calls it
    assert code.index("JXG.Options.jc.compile = false") < code.index("board = drawBoard(")


def test_jsxgraph_is_only_handed_closures_and_numbers():
    # a string term ('sin(a*x)') would go to JessieCode and be compiled with eval
    code = code_of("graph.js")
    creates = re.findall(r"board\.create\(\s*'(\w+)'\s*,\s*\[(.*?)\]\s*,", code, flags=re.S)
    assert {kind for kind, _ in creates} == {"functiongraph", "curve", "point"}
    for kind, args in creates:
        assert not re.search(r"['\"`]", args), (kind, args)


VENDOR = ROOT / "app/static/vendor/jsxgraph"


def test_the_vendored_jsxgraph_is_the_unmodified_release():
    core = VENDOR / "jsxgraphcore.js"
    assert hashlib.sha256(core.read_bytes()).hexdigest() == (
        "b6ebd07421e560431b888efeb472cfb7f2cfc495a853200963f97d2c28e6e474"
    )
    assert core.read_text().lstrip().startswith("/*\n    JSXGraph 1.14.1")
    assert hashlib.sha256((VENDOR / "jsxgraph.css").read_bytes()).hexdigest() == (
        "58ff5704eb9bb8db66e8b002d01c44a6ddfe0ced7f887ab2ef602feff2f3c0f6"
    )
    for licence in ("LICENSE.MIT", "LICENSE.LGPL", "README.md"):
        assert (VENDOR / licence).stat().st_size > 500, licence


def test_the_page_loads_jsxgraph_from_the_app_not_from_a_cdn(client):
    # R2 of the charter: no new CDN. base.html must not name another host for it.
    page = client.get("/").text
    assert "jsxgraph" not in page.lower()  # loaded lazily by graph.js, from /static/vendor
    assert "'/static/vendor/jsxgraph'" in code_of("graph.js")
    assert client.get("/static/vendor/jsxgraph/jsxgraphcore.js").status_code == 200
    assert client.get("/static/js/graph.js").status_code == 200
