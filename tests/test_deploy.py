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
# One container only: a <NAME>-next (a deploy beside the serving one) never exists here.
case "$1" in container|inspect|rm|start|stop|logs|port) case "$*" in *-next|*-next" "*) exit 125 ;; esac ;; esac
case "$1" in
  image) [ -f "$S/images/$(img "$3")" ] ;;
  container) [ -f "$S/container" ] ;;
  build) while [ $# -gt 0 ]; do [ "$1" = -t ] && echo "id-$2" >"$S/images/$(img "$2")"; shift; done ;;
  tag) cp "$S/images/$(img "$2")" "$S/images/$(img "$3")" ;;
  create) image=${!#}; id=$(cat "$S/images/$(img "$image")") || exit 125
       grep -qx "$id" "$S/run_fail" 2>/dev/null && { echo "create failed" >&2; exit 126; }
       printf '%s created\n' "$id" >"$S/container"
       while [ $# -gt 0 ]; do [ "$1" = -p ] && echo "$2" >"$S/port"; shift; done ;;
  port) [ -f "$S/container" ] && read -r _ st <"$S/container" && [ "$st" = running ] \
          && read -r p <"$S/port" && echo "${p%:*}" ;;  # real: "127.0.0.1:20004", and nothing once stopped
  rm) rm -f "$S/container" ;;
  inspect) [ -f "$S/container" ] || exit 125; read -r id st <"$S/container"
           sha=${id#id-wisenotes:}
           case "$*" in *State.Running*) [ "$st" = running ] && echo "$sha" ;;
                        *wisenotes.sha*) echo "$sha" ;;
                        *PortBindings*) read -r p <"$S/port"; p=${p%:*}; echo "${p##*:}" ;;
                        *) echo "$id" ;; esac ;;
  logs) echo "stub log" ;;
  start) [ -f "$S/container" ] && read -r id _ <"$S/container" && printf '%s running\n' "$id" >"$S/container" \
           && rm -f "$S/deaf" ;;
  stop) [ -f "$S/container" ] && read -r id _ <"$S/container" && printf '%s stopped\n' "$id" >"$S/container" ;;
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
  is-system-running) cat "$S/systemd" 2>/dev/null || echo running ;;
  is-active) [ ! -f "$S/unit_inactive" ] ;;
  start|restart) podman start "${3%-container.service}" ;;  # the unit's ExecStart, in short
  stop) [ -f "$S/no_unit" ] && { echo "Unit $3 not loaded." >&2; exit 5; }
        [ -f "$S/container" ] && podman stop "${3%-container.service}" ;;
  is-enabled) grep -qx "$3" "$S/enabled" 2>/dev/null ;;
  enable) shift 2; for u in "$@"; do [ "$u" = --now ] || echo "$u" >>"$S/enabled"; done ;;
esac
""",
    "git": r"""#!/usr/bin/env bash
case "$*" in *rev-parse*) echo "$STUB_SHA" ;;
  *fetch*) [ ! -f "$STUB_STATE/fetch_fail" ] ;; esac
""",
    "tar": "#!/usr/bin/env bash\ncat >/dev/null\n",
    "sleep": "#!/usr/bin/env bash\n",
    # Never the real ones: a test that reached them would repoint a live tailnet slot.
    "tailscale": '#!/usr/bin/env bash\necho "tailscale $*" >>"$STUB_STATE/log"; exit 1\n',
    "systemd-run": '#!/usr/bin/env bash\necho "systemd-run $*" >>"$STUB_STATE/log"; exit 1\n',
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


def unit_text(box):
    return (box / "home/.config/systemd/user/wisenotes-container.service").read_text()


def test_boot_persistence_is_a_wisenotes_only_unit(box):
    deploy_good(box, "aaa")
    log = (box / "state/log").read_text()
    assert "podman-restart" not in log  # never enabled, never queried
    text = unit_text(box)
    assert f"ExecStart={box / 'bin/podman'} start --attach wisenotes\n" in text
    assert f"ExecStop={box / 'bin/podman'} stop -t 10 wisenotes\n" in text
    assert (box / "state/enabled").read_text().split() == ["wisenotes-container.service"]
    # the unit runs one container by name; nothing in it reaches other containers
    assert "--all" not in text and "podman-restart" not in text


# ---------------------------------------------------------------- 20261019-054: one restarter


def test_the_container_has_no_podman_restart_policy(box):
    # Two restarters raced: podman's restart=always (which also enrolled the
    # container in the box-wide podman-restart.service) and the unit.
    deploy_good(box, "aaa")
    log = (box / "state/log").read_text()
    assert "podman create --name wisenotes" in log
    assert "--restart" not in log
    assert "podman run" not in log


def test_the_unit_restarts_the_container_when_it_dies(box):
    deploy_good(box, "aaa")
    text = unit_text(box)
    assert "\nRestart=on-failure\n" in text
    assert "RemainAfterExit" not in text and "Type=oneshot" not in text  # a oneshot sees no exit


def test_the_unit_is_what_starts_the_container(box):
    # Started by the unit, conmon and the port forwarder live in the unit's
    # cgroup, not in the preview loop's (20261019-014).
    deploy_good(box, "aaa")
    log = (box / "state/log").read_text().splitlines()
    create = log.index(next(x for x in log if x.startswith("podman create")))
    rest = log[create + 1 :]
    assert "systemctl --user restart wisenotes-container.service" in rest
    assert not any(
        x.startswith("podman start")
        for x in rest[: rest.index("systemctl --user restart wisenotes-container.service")]
    )


def test_the_unit_is_stopped_before_its_container_is_removed(box):
    deploy_good(box, "aaa")
    (box / "state/log").write_text("")
    deploy_good(box, "bbb")
    log = (box / "state/log").read_text().splitlines()
    stop = log.index("systemctl --user stop wisenotes-container.service")
    rm = next(i for i, x in enumerate(log) if x.startswith("podman rm"))
    assert stop < rm


def test_without_systemd_the_container_is_started_directly_and_says_what_is_missing(box):
    (box / "state/systemd").write_text("offline\n")
    r = deploy_good(box, "aaa")
    assert "nothing restarts wisenotes if it dies" in r.stdout
    log = (box / "state/log").read_text()
    assert "podman start wisenotes" in log and "systemctl --user restart" not in log
    assert serving(box) == "id-wisenotes:aaa"


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
    assert "podman create" not in after and "podman rm" not in after


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
    (work / ".gitignore").write_text(".env\n.preview-last-tried\n.preview-deaf\n")
    (work / "Dockerfile").write_text("FROM scratch\n")
    a = commit(work, "A")
    git(box, "clone", "-q", "-b", "develop", str(origin), str(checkout))
    return {"origin": origin, "work": work, "checkout": checkout, "a": a}


def preview(box, checkout, *args, timeout=60):
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
        timeout=timeout,
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


def block_checkout(loop, tip_edit):
    """A tip that adds notes.txt, over an untracked notes.txt in the loop checkout.

    git refuses that checkout ("untracked working tree files would be
    overwritten"), and the tracked-edits check cannot see an untracked file.
    """
    (loop["checkout"] / "notes.txt").write_text("the loop's own\n")
    (loop["work"] / "notes.txt").write_text("the tip's\n")
    return commit(loop["work"], "B", edit=tip_edit)


def test_preview_does_not_restart_itself_when_the_checkout_fails(box, loop):
    # 20261019-068 F1: the failed checkout left the old preview.sh, whose blob
    # still differed from the tip's, so it re-executed itself with no sleep.
    block_checkout(loop, ("preview.sh", 'echo "preview.sh of commit B"'))
    r = preview(box, loop["checkout"], timeout=20)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "could not move" in r.stdout
    assert "restarting it" not in r.stdout
    assert git(loop["checkout"], "rev-parse", "--short", "HEAD") == loop["a"]
    assert serving(box) is None


def test_preview_does_not_deploy_with_old_scripts_when_the_checkout_fails(box, loop):
    # F1, the quiet half: preview.sh unchanged, so the old deploy.sh ran the deploy
    # under a log line naming the tip's scripts.
    block_checkout(loop, ("deploy.sh", 'echo "deploy.sh of commit B"'))
    r = preview(box, loop["checkout"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "could not move" in r.stdout
    assert serving(box) is None


def test_preview_does_not_deploy_when_head_is_not_the_tip(box, loop):
    # The second guard, on its own: a checkout that claims success and moves nothing.
    real = shutil.which("git")
    shim = box / "bin/git"
    shim.write_text(
        f'#!/usr/bin/env bash\ncase " $* " in *" checkout "*) exit 0 ;; esac\nexec {real} "$@"\n'
    )
    shim.chmod(0o755)
    b = commit(loop["work"], "B", edit=("deploy.sh", 'echo "deploy.sh of commit B"'))
    r = preview(box, loop["checkout"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"is at {loop['a']}, not {b}; not deploying" in r.stdout
    assert serving(box) is None


def test_harness_control_a_clean_checkout_still_moves_with_an_untracked_file(box, loop):
    # An untracked file the tip does not add does not block the move.
    (loop["checkout"] / "notes.txt").write_text("the loop's own\n")
    b = commit(loop["work"], "B")
    r = preview(box, loop["checkout"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert git(loop["checkout"], "rev-parse", "--short", "HEAD") == b
    assert serving(box) == f"id-wisenotes:{b}"


def test_one_failed_health_check_does_not_restart_the_container(box):
    # 20261019-068 F2: one slow answer made the loop remove a working container.
    deploy_good(box, "aaa")
    before = serving(box)
    (box / "state/deaf").touch()
    r = run(box, script="preview.sh", sha="aaa")
    assert r.returncode == 0, r.stderr
    assert "checking again next pass" in r.stderr
    assert "already serving" in r.stdout
    assert (box / "state/deaf").exists() and serving(box) == before


def test_harness_control_a_healthy_pass_between_failures_resets_the_count(box):
    deploy_good(box, "aaa")
    (box / "state/deaf").touch()
    run(box, script="preview.sh", sha="aaa")
    (box / "state/deaf").unlink()
    run(box, script="preview.sh", sha="aaa")
    (box / "state/deaf").touch()
    r = run(box, script="preview.sh", sha="aaa")
    assert "checking again next pass" in r.stderr and "second pass in a row" not in r.stderr
    assert (box / "state/deaf").exists()


def test_preview_restarts_a_running_container_that_does_not_answer(box):
    # 2026-10-19: the unit restart killed pasta; the container kept State.Running.
    # Two failed passes in a row (F2) before it counts as down.
    deploy_good(box, "aaa")
    (box / "state/deaf").touch()
    run(box, script="preview.sh", sha="aaa")
    r = run(box, script="preview.sh", sha="aaa")
    assert r.returncode == 0, r.stderr
    assert "already serving" not in r.stdout.splitlines()[0]
    assert "the second pass in a row; treating it as down" in r.stderr
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


# ---------------------------------------------------------------- 20261020-044


def test_a_miss_by_a_replaced_container_does_not_count_against_the_new_one(box):
    # Pass 1: aaa misses once, and the pass deploys bbb. Pass 2: bbb misses once.
    # That is bbb's FIRST miss; the old marker made it "the second pass in a row".
    deploy_good(box, "aaa")
    (box / "state/deaf").touch()
    r = run(box, script="preview.sh", sha="bbb")
    assert "checking again next pass" in r.stderr and serving(box) == "id-wisenotes:bbb"
    (box / "state/deaf").touch()
    r = run(box, script="preview.sh", sha="bbb")
    assert "checking again next pass" in r.stderr, r.stderr
    assert "second pass in a row" not in r.stderr


def test_a_deaf_container_is_restarted_while_origin_is_unreachable(box):
    deploy_good(box, "aaa")
    (box / "state/fetch_fail").touch()
    (box / "state/deaf").touch()
    run(box, script="preview.sh", sha="aaa")
    r = run(box, script="preview.sh", sha="aaa")
    assert "second pass in a row" in r.stderr
    assert "starting the current image" in r.stdout and "fetch failed" in r.stdout
    assert not (box / "state/deaf").exists() and serving(box) == "id-wisenotes:aaa"


def test_harness_control_a_reachable_origin_and_a_healthy_container(box):
    deploy_good(box, "aaa")
    (box / "state/fetch_fail").touch()
    r = run(box, script="preview.sh", sha="aaa")
    assert "fetch failed; keeping aaa" in r.stdout and "starting" not in r.stdout


def test_a_re_exec_does_not_judge_the_container_twice_in_one_pass(box, loop):
    a = loop["a"]
    assert serving(box) is None
    r = preview(box, loop["checkout"])  # deploys A
    assert serving(box) == f"id-wisenotes:{a}", r.stdout + r.stderr
    commit(loop["work"], "B", edit=("preview.sh", 'echo "preview.sh of commit B"'))
    (box / "state/deaf").touch()  # A is slow at both moments of this one pass
    r = preview(box, loop["checkout"])
    assert "preview.sh changed at" in r.stdout
    assert r.stderr.count("checking again next pass") == 1, r.stderr
    assert "second pass in a row" not in r.stderr and "starting the current image" not in r.stdout


def test_the_unit_is_stopped_before_removal_even_while_the_manager_is_stopping(box):
    # c1dd1d1 review 2a: is-system-running says "stopping", the unit still runs.
    deploy_good(box, "aaa")
    (box / "state/systemd").write_text("stopping\n")
    (box / "state/log").write_text("")
    run(box, sha="bbb")
    log = (box / "state/log").read_text().splitlines()
    stop = log.index("systemctl --user stop wisenotes-container.service")
    assert stop < next(i for i, x in enumerate(log) if x.startswith("podman rm"))


def test_the_unit_is_stopped_before_removal_while_it_is_activating(box):
    # 20261020-087: is-active is false for activating/deactivating (RestartSec=2), so
    # the stop was skipped and podman rm -f ran under a pending start.
    deploy_good(box, "aaa")
    (box / "state/unit_inactive").touch()  # is-active answers no, as while activating
    (box / "state/log").write_text("")
    deploy_good(box, "bbb")
    log = (box / "state/log").read_text().splitlines()
    stop = log.index("systemctl --user stop wisenotes-container.service")
    assert stop < next(i for i, x in enumerate(log) if x.startswith("podman rm"))


def test_harness_control_the_unconditional_stop_is_harmless_when_there_is_no_unit(box):
    # The harm an unconditional stop could do is fail the deploy where there is
    # nothing to stop. It does not: an unloaded unit (exit 5) still deploys.
    deploy_good(box, "aaa")
    (box / "state/no_unit").touch()
    (box / "state/log").write_text("")
    deploy_good(box, "bbb")
    assert "systemctl --user stop wisenotes-container.service" in (box / "state/log").read_text()
    assert serving(box) == "id-wisenotes:bbb"


# ---------------------------------------------------------------- 20261022-035: deploy beside, no gap
#
# Two-container stubs. Each container is a file under state/c/<name> holding
# "<image id> <created|running|stopped> <host port> <writer id>"; an image is a
# file holding "<id> <fence|nofence>". The tailnet slot is state/slot (its
# proxy target). After every command that changes a container or the slot, the
# stubs record a GAP if the slot's port has no running, answering container,
# and log "route <port> writer=<.writer>" on each repoint, so a test can read
# the order of writer changes and repoints.

STUBS_BESIDE = {
    "podman": r"""#!/usr/bin/env bash
S=$STUB_STATE; echo "podman $*" >>"$S/log"
img() { printf '%s' "$1" | tr ':/' '__'; }
last=${!#}
c="$S/c/$last"
field() { awk -v n="$1" '{print $n}' "$2"; }
case "$1" in
  image) case "$2" in
           exists) [ -f "$S/images/$(img "$3")" ] ;;
           inspect) [ -f "$S/images/$(img "$last")" ] || exit 125
                    [ "$(field 2 "$S/images/$(img "$last")")" = fence ] && echo 1 || echo ;;
         esac ;;
  container) [ -f "$S/c/$3" ] ;;
  build) while [ $# -gt 0 ]; do
           if [ "$1" = -t ]; then f=fence; grep -qx "$2" "$S/nofence" 2>/dev/null && f=nofence
             echo "id-$2 $f" >"$S/images/$(img "$2")"; fi; shift; done ;;
  tag) cp "$S/images/$(img "$2")" "$S/images/$(img "$3")" ;;
  create) id=$(field 1 "$S/images/$(img "$last")") || exit 125
       grep -qx "$id" "$S/run_fail" 2>/dev/null && { echo "create failed" >&2; exit 126; }
       name=; port=; writer=-
       while [ $# -gt 0 ]; do case "$1" in
         --name) name=$2 ;; -p) p=${2%:*}; port=${p##*:} ;; --label) case "$2" in wisenotes.writer=*) writer=${2#*=} ;; esac ;;
       esac; shift; done
       [ -f "$S/c/$name" ] && { echo "name in use" >&2; exit 125; }
       echo "$id created $port $writer" >"$S/c/$name" ;;
  port) [ -f "$c" ] && [ "$(field 2 "$c")" = running ] && echo "127.0.0.1:$(field 3 "$c")" ;;
  rm) rm -f "$c"; gapcheck ;;
  inspect) [ -f "$c" ] || exit 125
           id=$(field 1 "$c"); sha=${id##*:}
           case "$*" in *State.Running*) [ "$(field 2 "$c")" = running ] && echo true || echo false ;;
                        *wisenotes.writer*) field 4 "$c" ;;
                        *write-fence*) f=$(grep -l "^$id " "$S"/images/* | head -1); [ "$(field 2 "$f")" = fence ] && echo 1 || echo ;;
                        *wisenotes.sha*) echo "$sha" ;;
                        *PortBindings*) field 3 "$c" ;;
                        *) echo "$id" ;; esac ;;
  logs) echo "stub log" ;;
  start) [ -f "$c" ] || exit 125; read -r id _ port w <"$c"; echo "$id running $port $w" >"$c"
         echo "started $last writer=$(cat "$WISENOTES_DATA/.writer" 2>/dev/null)" >>"$S/log"; gapcheck ;;
  stop) [ -f "$c" ] || exit 125; read -r id _ port w <"$c"; echo "$id stopped $port $w" >"$c"; gapcheck ;;
  ps) ;;
esac
""",
    "curl": r"""#!/usr/bin/env bash
S=$STUB_STATE; url=${!#}; hp=${url#http://}; hp=${hp%%/*}; port=${hp##*:}
for c in "$S"/c/*; do
  [ -f "$c" ] || continue
  read -r id st p _ <"$c"
  [ "$p" = "$port" ] && [ "$st" = running ] || continue
  if grep -qx "$id" "$S/bad" 2>/dev/null; then printf 500; else printf 200; fi
  exit 0
done
printf 000; exit 7
""",
    "systemctl": r"""#!/usr/bin/env bash
S=$STUB_STATE; echo "systemctl $*" >>"$S/log"
case "$2" in
  is-system-running) echo running ;;
  start|restart) podman start "${3%-container.service}" ;;
  stop) [ -f "$S/c/${3%-container.service}" ] && podman stop "${3%-container.service}"; true ;;
  is-enabled) grep -qx "$3" "$S/enabled" 2>/dev/null ;;
  enable) echo "$3" >>"$S/enabled" ;;
  daemon-reload) ;;
esac
""",
    "systemd-run": r"""#!/usr/bin/env bash
echo "systemd-run $*" >>"$STUB_STATE/log"; podman start "${!#}"
""",
    "tailscale": r"""#!/usr/bin/env bash
S=$STUB_STATE; echo "tailscale $*" >>"$S/log"
case "$*" in
  "serve status --json")
    printf '{"Web":{"devbox.example.ts.net:%s":{"Handlers":{"/":{"Proxy":"%s"}}}}}\n' "$(cat "$S/slot_port")" "$(cat "$S/slot")" ;;
  "serve --bg --http="*)
    [ -f "$S/route_fail" ] && exit 1
    t=${!#}; echo "$t" >"$S/slot"
    echo "route ${t##*:} writer=$(cat "$WISENOTES_DATA/.writer" 2>/dev/null)" >>"$S/log"
    gapcheck ;;
esac
""",
    "gapcheck": r"""#!/usr/bin/env bash
# Is something running and answering on the port the tailnet slot proxies to?
S=$STUB_STATE; [ -f "$S/slot" ] || exit 0
t=$(cat "$S/slot"); port=${t##*:}
[ "$(curl -s "http://127.0.0.1:$port/health")" = 200 ] || echo "GAP slot->$port after: $(tail -1 "$S/log")" >>"$S/gaps"
exit 0
""",
    "git": STUBS["git"],
    "tar": STUBS["tar"],
    "sleep": STUBS["sleep"],
}


@pytest.fixture()
def beside(tmp_path):
    """A fake host for deploys beside the serving container; slot 8094 proxies to 20250."""
    for d in ("bin", "state/images", "state/c", "repo/deploy", "home", "data"):
        (tmp_path / d).mkdir(parents=True)
    for name, body in STUBS_BESIDE.items():
        f = tmp_path / "bin" / name
        f.write_text(body)
        f.chmod(0o755)
    shutil.copy(REPO / "deploy" / "deploy.sh", tmp_path / "repo/deploy" / "deploy.sh")
    (tmp_path / "state/slot").write_text("http://localhost:20250\n")
    (tmp_path / "state/slot_port").write_text("8094\n")
    return tmp_path


def run_beside(box, *args, sha="new", **env):
    settings = {
        "WISENOTES_PORT": "20250",
        "WISENOTES_SPARE_PORT": "20260",
        "WISENOTES_SERVE_SLOT": "8094",
        "WISENOTES_DRAIN_SECONDS": "2",
    }
    return run(box, *args, sha=sha, **{**settings, **env})


def image_id(box, tag):
    """The image's id without its fence flag."""
    got = image(box, tag)
    return got.split()[0] if got else None


def containers(box):
    """{name: (image id, state, port, writer id)}"""
    return {c.name: tuple(c.read_text().split()) for c in (box / "state/c").iterdir()}


def writer(box):
    f = box / "data/.writer"
    return f.read_text().strip() if f.exists() else None


def slot(box):
    return (box / "state/slot").read_text().strip()


def gaps(box):
    f = box / "state/gaps"
    return f.read_text() if f.exists() else ""


def log(box):
    return (box / "state/log").read_text()


def reset_log(box):
    (box / "state/log").write_text("")
    (box / "state/gaps").unlink(missing_ok=True)


def serving_aaa(box):
    """aaa deployed in place (nothing served before it), then the log cleared."""
    r = run_beside(box, sha="aaa")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "in place" in r.stdout and "not running" in r.stdout
    reset_log(box)


def test_beside_a_good_deploy_leaves_no_gap_on_the_slot(beside):
    serving_aaa(beside)
    r = run_beside(beside, sha="bbb")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no gap" in r.stdout
    assert gaps(beside) == ""
    # at rest: exactly as an in-place deploy leaves it
    assert set(containers(beside)) == {"wisenotes"}
    img, state, port, wid = containers(beside)["wisenotes"]
    assert (img, state, port) == ("id-wisenotes:bbb", "running", "20250")
    assert writer(beside) == wid
    assert slot(beside).endswith(":20250")
    assert image_id(beside, "wisenotes:current") == "id-wisenotes:bbb"
    assert image_id(beside, "wisenotes:previous") == "id-wisenotes:aaa"


def test_harness_control_an_in_place_deploy_is_seen_as_a_gap(beside):
    # The gap check must be able to see a gap: the same deploy, forced in place.
    serving_aaa(beside)
    r = run_beside(beside, sha="bbb", WISENOTES_SPARE_PORT="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "in place" in r.stdout and "WISENOTES_SPARE_PORT is unset" in r.stdout
    assert "GAP slot->20250" in gaps(beside)


def test_beside_the_writer_changes_before_each_repoint(beside):
    serving_aaa(beside)
    old = writer(beside)
    run_beside(beside, sha="bbb")
    routes = [line for line in log(beside).splitlines() if line.startswith("route ")]
    assert len(routes) == 2, routes
    # to the spare port: the new container is already the writer
    assert routes[0].startswith("route 20260 writer=wisenotes-next.")
    # back to 20250: the new wisenotes is already the writer
    assert routes[1] == f"route 20250 writer={writer(beside)}"
    assert old not in routes[0] and writer(beside).startswith("wisenotes.")


def started(box):
    return [line for line in log(box).splitlines() if line.startswith("started ")]


def test_beside_the_new_container_cannot_write_while_smoked(beside):
    serving_aaa(beside)
    old = writer(beside)
    run_beside(beside, sha="bbb")
    starts = started(beside)
    assert len(starts) == 2, starts
    # each new container starts while another is still named the writer
    assert starts[0] == f"started wisenotes-next writer={old}"
    assert starts[1].startswith("started wisenotes writer=wisenotes-next."), starts


@pytest.mark.parametrize("failure", ["bad", "run_fail"])
def test_beside_a_failed_smoke_leaves_the_old_serving_and_writing(beside, failure):
    serving_aaa(beside)
    old = writer(beside)
    mark(beside, failure, "id-wisenotes:bbb")
    r = run_beside(beside, sha="bbb")
    assert r.returncode == 1
    assert "ROLLED BACK" in r.stdout and "served throughout" in r.stdout
    assert gaps(beside) == ""
    assert containers(beside) == {"wisenotes": ("id-wisenotes:aaa", "running", "20250", old)}
    assert writer(beside) == old and slot(beside).endswith(":20250")
    assert image_id(beside, "wisenotes:current") == "id-wisenotes:aaa"  # never pointed at bbb
    assert "tailscale serve --bg" not in log(beside)


def test_beside_a_failed_repoint_gives_the_writer_back(beside):
    serving_aaa(beside)
    old = writer(beside)
    (beside / "state/route_fail").write_text("")
    r = run_beside(beside, sha="bbb")
    assert r.returncode == 1 and "NOT deployed" in r.stdout
    assert writer(beside) == old
    assert set(containers(beside)) == {"wisenotes"} and slot(beside).endswith(":20250")
    assert image_id(beside, "wisenotes:current") == "id-wisenotes:aaa"


def test_beside_a_write_in_flight_holds_the_handover(beside):
    # A write holds the shared lock (app/write_fence.py); the change of writer must
    # wait for it, and give up after WISENOTES_DRAIN_SECONDS without changing anything.
    serving_aaa(beside)
    old = writer(beside)
    holder = subprocess.Popen(["flock", "-s", str(beside / "data/.writer.lock"), "sleep", "30"])
    try:
        r = run_beside(beside, sha="bbb", WISENOTES_DRAIN_SECONDS="1")
    finally:
        holder.kill()
        holder.wait()
    assert r.returncode == 1 and "did not finish within 1s" in r.stdout
    assert writer(beside) == old and slot(beside).endswith(":20250")
    assert set(containers(beside)) == {"wisenotes"}


def test_harness_control_the_handover_proceeds_once_the_write_ends(beside):
    serving_aaa(beside)
    holder = subprocess.Popen(["flock", "-s", str(beside / "data/.writer.lock"), "sleep", "0.5"])
    try:
        r = run_beside(beside, sha="bbb")
    finally:
        holder.wait()
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize(
    "setup, why",
    [
        (lambda b: (b / "state/nofence").write_text("wisenotes:bbb\n"), "the new image has no write fence"),
        (lambda b: (b / "state/slot").write_text("http://localhost:9999\n"), "proxies to http://localhost:9999, not to 20250"),
    ],
)
def test_beside_falls_back_to_in_place_and_says_why(beside, setup, why):
    serving_aaa(beside)
    setup(beside)
    r = run_beside(beside, sha="bbb")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "in place" in r.stdout and why in r.stdout
    assert "systemd-run" not in log(beside)


def test_beside_an_old_image_without_the_fence_is_replaced_in_place(beside):
    # the first deploy of this change: the serving image predates the fence
    (beside / "state/nofence").write_text("wisenotes:aaa\n")
    serving_aaa(beside)
    r = run_beside(beside, sha="bbb")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "the serving image predates the write fence" in r.stdout
    assert "systemd-run" not in log(beside)


def test_beside_the_slot_url_never_changes(beside):
    serving_aaa(beside)
    run_beside(beside, sha="bbb")
    repoints = [line for line in log(beside).splitlines() if line.startswith("tailscale serve --bg")]
    assert repoints and all(line.startswith("tailscale serve --bg --http=8094 ") for line in repoints)


def test_beside_the_new_container_has_one_restarter_and_no_restart_policy(beside):
    serving_aaa(beside)
    run_beside(beside, sha="bbb")
    text = log(beside)
    runs = [line for line in text.splitlines() if line.startswith("systemd-run ")]
    assert len(runs) == 1 and "--unit=wisenotes-next-container.service" in runs[0]
    assert "Restart=on-failure" in runs[0]
    assert "--restart" not in "".join(line for line in text.splitlines() if line.startswith("podman create"))
    assert "podman-restart" not in text
    # its unit is stopped before the container is removed
    stop = text.index("systemctl --user stop wisenotes-next-container.service")
    assert stop < text.index("podman rm -f wisenotes-next")


def test_start_hands_back_from_a_container_left_beside(beside):
    # A deploy whose second leg failed leaves wisenotes-next serving; --start brings wisenotes back.
    serving_aaa(beside)
    run_beside(beside, sha="bbb")
    # the state a failed second leg leaves: wisenotes gone, next serving and writing
    (beside / "state/c/wisenotes").unlink()
    (beside / "state/c/wisenotes-next").write_text("id-wisenotes:bbb running 20260 wisenotes-next.1.1\n")
    (beside / "data/.writer").write_text("wisenotes-next.1.1\n")
    (beside / "state/slot").write_text("http://127.0.0.1:20260\n")
    reset_log(beside)
    r = run_beside(beside, "--start")
    assert r.returncode == 0, r.stdout + r.stderr
    assert gaps(beside) == ""
    # wisenotes starts unable to write: the container serving the slot keeps writing until the hand-back
    assert started(beside) == ["started wisenotes writer=wisenotes-next.1.1"]
    assert set(containers(beside)) == {"wisenotes"} and slot(beside).endswith(":20250")
    assert writer(beside) == containers(beside)["wisenotes"][3]


def test_start_after_a_reboot_mid_handover_points_the_slot_home(beside):
    # tailscale serve config survives a reboot; the transient container does not.
    serving_aaa(beside)
    (beside / "state/c/wisenotes").write_text("id-wisenotes:aaa stopped 20250 x\n")
    (beside / "state/slot").write_text("http://127.0.0.1:20260\n")
    r = run_beside(beside, "--start")
    assert r.returncode == 0, r.stdout + r.stderr
    assert slot(beside).endswith(":20250")


def test_harness_control_start_leaves_a_slot_pointing_elsewhere_alone(beside):
    serving_aaa(beside)
    (beside / "state/c/wisenotes").write_text("id-wisenotes:aaa stopped 20250 x\n")
    (beside / "state/slot").write_text("http://127.0.0.1:9999\n")
    r = run_beside(beside, "--start")
    assert r.returncode == 0, r.stdout + r.stderr
    assert slot(beside) == "http://127.0.0.1:9999"
