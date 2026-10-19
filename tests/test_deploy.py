"""deploy/deploy.sh and deploy/preview.sh against stub podman, systemctl, git and curl.

The stubs keep their state in files: an image is a file under images/ holding an
id; the container is one file naming its image id and whether it runs; curl
answers 200 unless the running image's id is listed as bad. Nothing touches the
real podman, systemd or network.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

STUBS = {
    "podman": r"""#!/usr/bin/env bash
S=$STUB_STATE; echo "podman $*" >>"$S/log"
img() { printf '%s' "$1" | tr ':/' '__'; }
case "$1" in
  image) [ -f "$S/images/$(img "$3")" ] ;;
  container) [ -f "$S/container" ] ;;
  build) while [ $# -gt 0 ]; do [ "$1" = -t ] && echo "id-$2" >"$S/images/$(img "$2")"; shift; done ;;
  tag) cp "$S/images/$(img "$2")" "$S/images/$(img "$3")" ;;
  run) image=${!#}; id=$(cat "$S/images/$(img "$image")") || exit 125
       grep -qx "$id" "$S/run_fail" 2>/dev/null && { echo "run failed" >&2; exit 126; }
       printf '%s running\n' "$id" >"$S/container"; rm -f "$S/deaf"
       while [ $# -gt 0 ]; do [ "$1" = -p ] && echo "$2" >"$S/port"; shift; done ;;
  port) [ -f "$S/container" ] && read -r p <"$S/port" && echo "${p%:*}" ;;  # real: "127.0.0.1:20004"
  rm) rm -f "$S/container" ;;
  inspect) [ -f "$S/container" ] || exit 125; read -r id st <"$S/container"
           sha=${id#id-wisenotes:}
           case "$*" in *State.Running*) [ "$st" = running ] && echo "$sha" ;;
                        *wisenotes.sha*) echo "$sha" ;;
                        *PortBindings*) read -r p <"$S/port"; p=${p%:*}; echo "${p##*:}" ;;
                        *) echo "$id" ;; esac ;;
  logs) echo "stub log" ;;
  start) [ -f "$S/container" ] && read -r id _ <"$S/container" && printf '%s running\n' "$id" >"$S/container" ;;
esac
""",
    "curl": r"""#!/usr/bin/env bash
S=$STUB_STATE
[ -f "$S/container" ] || { printf 000; exit 7; }
[ -f "$S/deaf" ] && { printf 000; exit 7; }  # running, but nothing forwards its port
read -r id st <"$S/container"
if [ "$st" != running ] || grep -qx "$id" "$S/bad" 2>/dev/null; then printf 500; else printf 200; fi
""",
    "systemctl": r"""#!/usr/bin/env bash
S=$STUB_STATE; echo "systemctl $*" >>"$S/log"
case "$2" in
  is-system-running) echo running ;;
  is-enabled) grep -qx "$3" "$S/enabled" 2>/dev/null ;;
  enable) shift 2; for u in "$@"; do [ "$u" = --now ] || echo "$u" >>"$S/enabled"; done ;;
esac
""",
    "git": r"""#!/usr/bin/env bash
case "$*" in *rev-parse*) echo "$STUB_SHA" ;; esac
""",
    "tar": "#!/usr/bin/env bash\ncat >/dev/null\n",
    "sleep": "#!/usr/bin/env bash\n",
}


@pytest.fixture()
def box(tmp_path):
    """A fake host: stubs on PATH, the two scripts copied out of the checkout."""
    for d in ("bin", "state/images", "repo/deploy", "home", "data"):
        (tmp_path / d).mkdir(parents=True)
    for name, body in STUBS.items():
        f = tmp_path / "bin" / name
        f.write_text(body)
        f.chmod(0o755)
    for script in ("deploy.sh", "preview.sh"):
        shutil.copy(REPO / "deploy" / script, tmp_path / "repo/deploy" / script)
    return tmp_path


def run(box, *args, script="deploy.sh", sha="new", **env):
    environ = {
        "PATH": f"{box / 'bin'}:/usr/bin:/bin",
        "HOME": str(box / "home"),
        "XDG_CONFIG_HOME": str(box / "home/.config"),
        "STUB_STATE": str(box / "state"),
        "STUB_SHA": sha,
        "WISENOTES_DATA": str(box / "data"),
        "WISENOTES_SMOKE_SECONDS": "1",
        **env,
    }
    return subprocess.run(
        ["bash", str(box / "repo/deploy" / script), *args],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )


def image(box, tag):
    f = box / "state/images" / tag.replace(":", "_")
    return f.read_text().strip() if f.exists() else None


def serving(box):
    f = box / "state/container"
    return f.read_text().split()[0] if f.exists() else None


def mark(box, kind, image_id):
    with (box / "state" / kind).open("a") as f:
        f.write(image_id + "\n")


def deploy_good(box, sha, **env):
    r = run(box, sha=sha, **env)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


# ---------------------------------------------------------------- item 6


def test_a_good_deploy_moves_current_and_previous(box):
    deploy_good(box, "aaa")
    deploy_good(box, "bbb")
    assert image(box, "wisenotes:current") == "id-wisenotes:bbb"
    assert image(box, "wisenotes:previous") == "id-wisenotes:aaa"
    assert serving(box) == "id-wisenotes:bbb"


@pytest.mark.parametrize("failure", ["bad", "run_fail"])
def test_a_failed_deploy_leaves_current_on_the_last_good_image(box, failure):
    deploy_good(box, "aaa")
    mark(box, failure, "id-wisenotes:bbb")  # bbb fails smoke, or podman run fails
    r = run(box, sha="bbb")
    assert r.returncode == 1
    assert image(box, "wisenotes:current") == "id-wisenotes:aaa"  # never pointed at bbb
    assert serving(box) == "id-wisenotes:aaa"
    assert "ROLLED BACK" in r.stdout


def test_a_first_deploy_that_fails_leaves_nothing_tagged_current(box):
    mark(box, "run_fail", "id-wisenotes:aaa")
    r = run(box, sha="aaa")
    assert r.returncode == 1 and "NOTHING IS SERVING" in r.stdout
    assert image(box, "wisenotes:current") is None and serving(box) is None


def test_start_never_leaves_a_failing_image_serving(box):
    deploy_good(box, "aaa")
    mark(box, "bad", "id-wisenotes:aaa")  # e.g. the host changed under it
    r = run(box, "--start")
    assert r.returncode == 1 and "NOTHING IS SERVING" in r.stdout
    assert serving(box) is None


# ---------------------------------------------------------------- item 8


def test_boot_persistence_is_a_wisenotes_only_unit(box):
    deploy_good(box, "aaa")
    log = (box / "state/log").read_text()
    assert "podman-restart" not in log  # never enabled, never queried
    unit = box / "home/.config/systemd/user/wisenotes-container.service"
    text = unit.read_text()
    assert f"ExecStart={box / 'bin/podman'} start wisenotes\n" in text
    assert (box / "state/enabled").read_text().split() == ["wisenotes-container.service"]
    # the unit starts one container by name; nothing in it reaches other containers
    assert "--all" not in text and "restart" not in text.lower().replace("remainafterexit", "")


def test_boot_unit_is_written_once_and_enabled_once(box):
    deploy_good(box, "aaa")
    deploy_good(box, "bbb")
    log = (box / "state/log").read_text()
    assert log.count("systemctl --user enable") == 1
    assert log.count("daemon-reload") == 1


# ---------------------------------------------------------------- preview after a reboot


def test_preview_starts_a_stopped_container_instead_of_calling_it_serving(box):
    deploy_good(box, "aaa")
    c = box / "state/container"
    c.write_text(c.read_text().replace("running", "stopped"))  # what a reboot leaves
    r = run(box, script="preview.sh", sha="aaa")
    assert r.returncode == 0, r.stderr
    assert "already serving" not in r.stdout.splitlines()[0]
    assert "starting the current image" in r.stdout
    assert c.read_text().split()[1] == "running"


def test_harness_control_a_running_container_is_left_alone(box):
    # Control for the test above: the same pass with the container up does nothing.
    deploy_good(box, "aaa")
    before = (box / "state/log").read_text()
    r = run(box, script="preview.sh", sha="aaa")
    assert "already serving" in r.stdout
    after = (box / "state/log").read_text()[len(before) :]
    assert "podman run" not in after and "podman rm" not in after


def test_stubs_are_the_ones_on_path(box):
    # Precondition for every test here: the scripts reach the stubs, not real tools.
    r = run(box, sha="aaa")
    assert (box / "state/log").exists() and "podman build" in (box / "state/log").read_text()
    assert os.environ.get("STUB_STATE") is None  # nothing leaked into this process
    assert r.returncode == 0


# ---------------------------------------------------------------- item 7


def test_the_docs_name_the_ref_the_script_deploys():
    # deploy/README.md said origin/main for months after deploy.sh moved to develop.
    script = (REPO / "deploy/deploy.sh").read_text()
    [default] = re.findall(r"^REF=\$\{WISENOTES_REF:-([^}]+)\}", script, re.M)
    readme = (REPO / "deploy/README.md").read_text()
    env = (REPO / "deploy/env.example").read_text()
    assert f"deploys `{default}` unless" in readme
    assert re.search(rf"^WISENOTES_REF={re.escape(default)}\s", env, re.M)
    others = set(re.findall(r"deploys `(origin/[\w./-]+)`", readme)) - {default}
    assert not others, others


def test_the_docs_record_the_csrf_acceptance_and_what_ends_it():
    readme = (REPO / "deploy/README.md").read_text()
    section = readme.split("## Accepted risks", 1)[1].split("\n## ", 1)[0]
    assert "No CSRF protection" in section and "tailnet" in section
    assert "acceptance ends if the app is exposed beyond the" in " ".join(section.split())


# ---------------------------------------------------------------- port moves are said out loud


def test_a_deploy_on_another_port_says_the_port_moved(box):
    deploy_good(box, "aaa", PORT="20004")
    r = deploy_good(box, "bbb", PORT="20250")
    assert "PORT MOVES: wisenotes served on 20004 and will serve on 20250" in r.stdout
    assert (box / "state/port").read_text().strip() == "127.0.0.1:20250:8000"


def test_harness_control_a_deploy_on_the_same_port_is_quiet(box):
    deploy_good(box, "aaa", PORT="20250")
    r = deploy_good(box, "bbb", PORT="20250")
    assert "PORT MOVES" not in r.stdout
    assert (box / "state/port").read_text().strip() == "127.0.0.1:20250:8000"


# ---------------------------------------------------------------- 20261019-002: the loop runs the tip's scripts
#
# These use real git: an origin repo, and a loop checkout cloned from it, as the
# preview unit has. podman, curl, systemctl, tar and sleep stay stubbed.

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        env={**os.environ, **GIT_ENV, "GIT_CONFIG_GLOBAL": "/dev/null"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def commit(work, message, edit=None):
    """Commit the current deploy/ scripts, after inserting a line into one of them."""
    if edit:
        name, line = edit
        f = work / "deploy" / name
        lines = f.read_text().splitlines(keepends=True)
        at = next(i for i, x in enumerate(lines) if x.startswith("set -euo pipefail")) + 1
        f.write_text("".join([*lines[:at], line + "\n", *lines[at:]]))
    git(work, "add", "-A")
    git(work, "commit", "-q", "--allow-empty", "-m", message)
    git(work, "push", "-q", "origin", "HEAD:develop")
    return git(work, "rev-parse", "--short", "HEAD")


@pytest.fixture()
def loop(box):
    """origin (bare) <- author's clone; the loop checkout is a second clone at commit A."""
    (box / "bin/git").unlink()  # real git from here on
    origin, work, checkout = box / "origin.git", box / "author", box / "loop"
    git(box, "init", "-q", "--bare", "-b", "develop", str(origin))
    git(box, "clone", "-q", str(origin), str(work))
    git(work, "checkout", "-q", "-b", "develop")
    (work / "deploy").mkdir()
    for script in ("deploy.sh", "preview.sh"):
        shutil.copy(REPO / "deploy" / script, work / "deploy" / script)
    (work / ".gitignore").write_text(".env\n.preview-last-tried\n")
    (work / "Dockerfile").write_text("FROM scratch\n")
    a = commit(work, "A")
    git(box, "clone", "-q", "-b", "develop", str(origin), str(checkout))
    return {"origin": origin, "work": work, "checkout": checkout, "a": a}


def preview(box, checkout, *args):
    environ = {
        "PATH": f"{box / 'bin'}:/usr/bin:/bin",
        "HOME": str(box / "home"),
        "XDG_CONFIG_HOME": str(box / "home/.config"),
        "STUB_STATE": str(box / "state"),
        "WISENOTES_DATA": str(box / "data"),
        "WISENOTES_SMOKE_SECONDS": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        **GIT_ENV,
    }
    return subprocess.run(
        ["bash", str(checkout / "deploy/preview.sh"), *args],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preview_deploys_with_the_deploy_script_of_the_tip(box, loop):
    # The bug: the loop checkout stayed at the commit it was cloned at, so every
    # deploy ran that commit's deploy.sh, whatever develop's said.
    b = commit(loop["work"], "B", edit=("deploy.sh", 'echo "deploy.sh of commit B"'))
    r = preview(box, loop["checkout"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "deploy.sh of commit B" in r.stdout
    assert git(loop["checkout"], "rev-parse", "--short", "HEAD") == b
    assert serving(box) == f"id-wisenotes:{b}"


def test_preview_runs_its_own_new_version_when_preview_sh_changed(box, loop):
    b = commit(loop["work"], "B", edit=("preview.sh", 'echo "preview.sh of commit B"'))
    r = preview(box, loop["checkout"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "preview.sh changed at" in r.stdout
    assert r.stdout.count("preview.sh of commit B") == 1  # restarted once, not in a loop
    assert serving(box) == f"id-wisenotes:{b}"


def test_preview_never_moves_or_deploys_from_an_edited_checkout(box, loop):
    commit(loop["work"], "B", edit=("deploy.sh", 'echo "deploy.sh of commit B"'))
    script = loop["checkout"] / "deploy/deploy.sh"
    script.write_text(script.read_text() + "# a hand edit\n")
    r = preview(box, loop["checkout"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "has edits to tracked files" in r.stdout
    assert "deploy.sh of commit B" not in r.stdout
    assert git(loop["checkout"], "rev-parse", "--short", "HEAD") == loop["a"]
    assert serving(box) is None


def test_harness_control_gitignored_files_do_not_count_as_edits(box, loop):
    # deploy/.env and the last-tried marker live in the checkout and must not block it.
    (loop["checkout"] / "deploy/.env").write_text("WISENOTES_SMOKE_SECONDS=1\n")
    b = commit(loop["work"], "B")
    r = preview(box, loop["checkout"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "has edits" not in r.stdout
    assert serving(box) == f"id-wisenotes:{b}"
    assert (loop["checkout"] / "deploy/.env").exists()


def test_preview_restarts_a_running_container_that_does_not_answer(box):
    # 2026-10-19: the unit restart killed pasta; the container kept State.Running.
    deploy_good(box, "aaa")
    (box / "state/deaf").touch()
    r = run(box, script="preview.sh", sha="aaa")
    assert r.returncode == 0, r.stderr
    assert "already serving" not in r.stdout.splitlines()[0]
    assert "treating it as down" in r.stderr
    assert "starting the current image" in r.stdout
    assert not (box / "state/deaf").exists() and serving(box) == "id-wisenotes:aaa"


def test_a_start_on_another_port_says_the_port_moved_even_when_stopped(box):
    # The real move happened on this path: the old container had stopped, so
    # `podman port` had nothing to say and the move went unannounced.
    deploy_good(box, "aaa", PORT="20004")
    c = box / "state/container"
    c.write_text(c.read_text().replace("running", "stopped"))
    r = run(box, script="preview.sh", sha="aaa", PORT="20250")
    assert "PORT MOVES: wisenotes served on 20004 and will serve on 20250" in r.stdout
    assert (box / "state/port").read_text().strip() == "127.0.0.1:20250:8000"
