"""The Playwright checks run as part of the suite, when a chromium is present (20261027-036).

tests/graph_refusal.py and tests/graph_draw.py see what no server-side test can: that
app.js lets a refused graph save through htmx, and that a graph draws under the app's
real Content-Security-Policy. They used to run only by hand, so removing the one clause in
app.js that the first one guards turned nothing red. Here each runs against a uvicorn on a
scratch data directory. Without playwright or a launchable chromium (CI has neither) the
tests skip, and the skip names why; on devbox the browser is the cached one.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIBS = Path.home() / ".local/chromium-libs/extracted/usr/lib/x86_64-linux-gnu"


def browser_env() -> dict[str, str]:
    env = dict(os.environ)
    if LIBS.is_dir():  # devbox: the cached chromium needs its libraries (CONTRIBUTING.md)
        env["LD_LIBRARY_PATH"] = f"{LIBS}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


@pytest.fixture(scope="module")
def chromium():
    pytest.importorskip("playwright.sync_api")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from playwright.sync_api import sync_playwright\n"
            "with sync_playwright() as p:\n    p.chromium.launch().close()",
        ],
        env=browser_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(f"no launchable chromium: {probe.stderr.strip().splitlines()[-1:]}")


@pytest.fixture(scope="module")
def server(chromium, tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "WISENOTES_DATA_DIR": str(tmp_path_factory.mktemp("browser-data"))}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if urllib.request.urlopen(f"{base}/health", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("the scratch server never answered /health")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def run_check(script: str, base: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tests" / script), base],
        env=browser_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=240,
    )


@pytest.mark.parametrize("script", ["graph_refusal.py", "graph_draw.py"])
def test_the_browser_check_passes_in_both_arms(server, script):
    r = run_check(script, server)
    # exit 0 is a pass; 1 names a failed check; 2 is VACUOUS (it saw nothing to judge)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("VERDICT: PASS") == 2, r.stdout  # both arms gave a verdict
