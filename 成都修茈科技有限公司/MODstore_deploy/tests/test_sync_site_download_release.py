from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/sync_site_download_release.py"


def _run(tmp: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--site-root",
            str(tmp / "staged"),
            "--published-site-root",
            str(tmp / "live"),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _atomic_switch_compat() -> str:
    if sys.platform != "darwin":
        return ""
    # BSD mv has no -T. Execute the same-filesystem atomic symlink replacement,
    # rather than skipping the real activation/rollback filesystem assertions.
    command = shlex.join(
        [
            sys.executable,
            "-c",
            "import os, sys; assert len(sys.argv) == 4 and sys.argv[1] == '-Tf'; "
            "os.replace(sys.argv[2], sys.argv[3])",
        ]
    )
    return "\nmv() { " + command + ' "$@"; }\n'


def test_preserves_exact_public_identity_and_history_not_newest_candidate(
    tmp_path: Path,
) -> None:
    live, staged = tmp_path / "live", tmp_path / "staged"
    live.mkdir()
    mirror = staged / "MODstore_deploy/market/public"
    mirror.mkdir(parents=True)
    published = {
        "download_version": "1.0.0.6",
        "git_sha": "a" * 40,
        "release_id": "historical-artifact",
        "release_ready": False,
        "release_history": [{"version": "1.0.0.6"}, {"version": "1.0.0.5"}],
    }
    content = json.dumps(published, indent=3).encode() + b"\n"
    hotfix = b'{"version":"1.0.0.6","git_sha":"different-build","stable_auto_update":false}'
    for name, data in (
        ("download-release.json", content),
        ("download-windows-hotfix.json", hotfix),
    ):
        (live / name).write_bytes(data)
        (staged / name).write_text('{"download_version":"1.0.0.7"}')
    candidate = tmp_path / "www/update/releases/builds/1.0.0.7/newest"
    candidate.mkdir(parents=True)
    (candidate / "download-release.json").write_text('{"release_ready":true}')
    # Even a passing Windows-only manual record cannot create a global ready pointer.
    (candidate / "manual-download-manifest.json").write_text(
        json.dumps(
            {
                "publicationState": "verified",
                "installationLifecycleAcceptance": "PASS",
                "publicFullDownloadVerification": "PASS",
                "packages": [{"platform": "windows_x64"}],
            }
        )
    )
    for _ in range(2):
        result = _run(tmp_path)
        assert result.returncode == 0, result.stderr
        for root in (live, staged, mirror):
            assert (root / "download-release.json").read_bytes() == content
            assert (root / "download-windows-hotfix.json").read_bytes() == hotfix


@pytest.mark.parametrize("invalid", [None, b"not-json", b"[]", b"{}"])
def test_missing_or_invalid_public_pointer_fails_before_staged_writes(
    tmp_path: Path, invalid
) -> None:
    live, staged = tmp_path / "live", tmp_path / "staged"
    live.mkdir()
    staged.mkdir()
    target = staged / "download-release.json"
    target.write_bytes(b"existing-staged-bytes")
    if invalid is not None:
        (live / target.name).write_bytes(invalid)
    assert _run(tmp_path).returncode == 1
    assert target.read_bytes() == b"existing-staged-bytes"


def test_absent_public_hotfix_removes_stale_staged_copy(tmp_path: Path) -> None:
    for name in ("live", "staged"):
        (tmp_path / name).mkdir()
    (tmp_path / "live/download-release.json").write_text('{"release_ready":false}')
    stale = tmp_path / "staged/download-windows-hotfix.json"
    stale.write_text('{"download_allowed":true}')
    assert _run(tmp_path).returncode == 0
    assert not stale.exists()


def test_server_and_static_publishers_never_infer_desktop_publication() -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text()
    sync = script.index('python3 "$POINTER_SYNC" --site-root')
    assert script.index("npm run build") < sync < script.index('chmod -R a-w "$BUILD_ROOT"')
    assert '--published-site-root "$SITE_LINK"' in script[sync : sync + 300]
    assert "TARGET_SHA" not in script[sync : script.index("\n\n", sync)]
    updater = (ROOT / "scripts/xcmax-site-auto-update.sh").read_text()
    assert "seed_src=" not in updater
    workflow = (ROOT.parents[1] / ".github/workflows/corp-site-deploy.yml").read_text()
    assert 'cp -f "${GIT_SITE}/download-release.json"' not in workflow


@pytest.mark.parametrize("stale", ["root", "mirror", "hotfix", "symlink", None])
def test_check_is_read_only_and_requires_exact_pointer_set(tmp_path: Path, stale) -> None:
    for name in ("live", "staged"):
        (tmp_path / name).mkdir()
    pointer = "download-release.json"
    (tmp_path / "live" / pointer).write_text('{"version":"1.0.0.6"}')
    assert _run(tmp_path).returncode == 0
    mirror = tmp_path / "staged/corp-butler"
    mirror.mkdir()
    (mirror / pointer).write_bytes((tmp_path / "live" / pointer).read_bytes())
    if stale == "root":
        (tmp_path / "staged" / pointer).write_text('{"version":"1.0.0.5"}')
    elif stale == "mirror":
        (mirror / pointer).unlink()
    elif stale == "hotfix":
        (mirror / "download-windows-hotfix.json").write_text('{"stale":true}')
    elif stale == "symlink":
        (mirror / pointer).unlink()
        (mirror / pointer).symlink_to(tmp_path / "live" / pointer)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}
    result = _run(tmp_path, "--check")
    assert result.returncode == (0 if stale is None else 1), result.stderr
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}


@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_real_activation_and_rollback_blocks_preserve_public_bytes(
    tmp_path: Path, rollback: bool, stale: bool
) -> None:
    _assert_public_switch(tmp_path, rollback, stale, wait=False)


def test_prepared_reuse_is_checked_before_migrations_with_controller_helper() -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text()
    early = script.index('verify_public_pointers "$FINAL_ROOT"')
    assert (
        script.index("unset BUILD_JWT_SECRET")
        < early
        < script.index("applying database migrations")
    )
    assert 'POINTER_SYNC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)' in script
    workflow = (ROOT / ".github/workflows/prod-deploy.yml").read_text()
    assert (
        ':成都修茈科技有限公司/MODstore_deploy/scripts/sync_site_download_release.py" > "$BOOTSTRAP/sync_site_download_release.py"'
        in workflow
    )


@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize("changed_while_waiting", [False, True])
def test_publication_lock_serializes_switch_and_rechecks_waited_pointer(
    tmp_path: Path, rollback: bool, changed_while_waiting: bool
) -> None:
    _assert_public_switch(tmp_path, rollback, changed_while_waiting, wait=True)


def _assert_public_switch(tmp_path: Path, rollback: bool, stale: bool, *, wait: bool) -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text()
    current, site = tmp_path / "current", tmp_path / "site"
    original = b'{"version":"1.0.0.6"}\n'
    for name in ("active", "prepared"):
        target = tmp_path / name / "site"
        target.mkdir(parents=True)
        content = (
            b'{"version":"1.0.0.5"}' if stale and not wait and name == "prepared" else original
        )
        (target / "download-release.json").write_bytes(content)
    current.symlink_to(tmp_path / "active")
    site.symlink_to(current / "site")
    lock, attempted, protected = (tmp_path / name for name in ("lock", "attempted", "protected"))
    # Exercise real kernel flock on macOS too, where the flock CLI is absent.
    flock = tmp_path / "flock"
    flock.write_text(
        f"#!{sys.executable}\nimport fcntl, os, pathlib, sys\n"
        "pathlib.Path(os.environ['FLOCK_ATTEMPT']).touch()\n"
        "fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX)\n"
    )
    flock.chmod(0o755)
    acquire = re.search(r"acquire_publication_lock\(\) \{.*?^}", script, re.M | re.S).group()
    verify = re.search(r"verify_public_pointers\(\) \{.*?^}", script, re.M | re.S).group()
    verify = verify.replace(
        '"/var/www/update/releases/stable/enterprise/download-windows-hotfix.json"',
        shlex.quote(str(tmp_path / "absent-hotfix")),
    )
    if rollback:
        body = re.search(r"rollback\(\) \{.*?^}", script, re.M | re.S).group()
        body += '\nacquire_publication_lock\nrollback || exit "$?"\n'
    else:
        body = script[script.rindex("\nacquire_publication_lock\n") :]
        body = body[: body.index("install_cli_launcher")]
    variables = {
        "PUBLICATION_LOCK": lock,
        "POINTER_SYNC": SCRIPT,
        "SITE_SUBDIR": "site",
        "SITE_LINK": site,
        "CURRENT_LINK": current,
        "FINAL_ROOT": tmp_path / "prepared",
        "PREVIOUS_ROOT": tmp_path / "prepared",
        "PREVIOUS_SHA": "",
        "PREVIOUS_ARTIFACT_SHA": "",
    }
    setup = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in variables.items())
    # A second open must still contend after the switch, during health/rollback.
    probe = (
        "import fcntl, pathlib, sys\n"
        "with open(sys.argv[1], 'a') as handle:\n"
        " try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        " except BlockingIOError: pathlib.Path(sys.argv[2]).touch()\n"
        " else: raise SystemExit('publication lock released before health')\n"
    )
    command = (
        "set -e\n"
        + setup
        + "\nlog() { :; }; fail() { exit 1; }; systemctl() { :; };\n"
        + _atomic_switch_compat()
        + acquire
        + "\n"
        + verify
        + "\n"
        + body
        + "\n"
        + shlex.join([sys.executable, "-c", probe, str(lock), str(protected)])
    )
    with lock.open("a") as held:
        if wait:
            fcntl.flock(held, fcntl.LOCK_EX)
        process = subprocess.Popen(
            ["bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "FLOCK_ATTEMPT": str(attempted),
            },
        )
        try:
            if wait:
                deadline = time.monotonic() + 5
                while (
                    not attempted.exists()
                    and process.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                assert attempted.exists(), "switch did not reach the shared lock"
                assert process.poll() is None, "switch passed another publisher's held lock"
                assert current.resolve() == tmp_path / "active"
                if stale:
                    (site / "download-release.json").write_bytes(b'{"version":"1.0.0.7"}')
                fcntl.flock(held, fcntl.LOCK_UN)
            stdout, stderr = process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert process.returncode == (1 if stale else 0), stdout + stderr
    assert current.resolve() == tmp_path / ("active" if stale else "prepared")
    expected = b'{"version":"1.0.0.7"}' if stale and wait else original
    assert (site / "download-release.json").read_bytes() == expected
    assert protected.exists() is not stale


def test_all_site_writers_share_one_lock_without_nested_acquisition() -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text()
    updater = (ROOT / "scripts/xcmax-site-auto-update.sh").read_text()
    workflow = (ROOT.parents[1] / ".github/workflows/corp-site-deploy.yml").read_text()
    for source in (script, updater, workflow):
        assert "${XCMAX_PUBLICATION_LOCK:-/run/lock/xcmax-publication.lock}" in source
        assert 'exec 8>"$PUBLICATION_LOCK"' in source
        assert "flock -w 60 8" in source
    activation = script.rindex("\nacquire_publication_lock\n")
    assert script.index("migrate_delivery_state false") < activation
    assert activation < script.rindex('verify_public_pointers "$FINAL_ROOT"')
    assert "exec 8>&-" not in script[activation:]
    assert updater.count("flock -w 60 8") == 1
    assert updater.index("flock -w 60 8") < updater.index("REPO_CHANGED=false")
    assert "restart_app_services\n)" in updater
    assert workflow.index("flock -w 60 8") < workflow.index('LIVE_SITE="$(readlink')
    assert workflow.index("exec 8>&-") > workflow.index("[ok] live site chrome published")
