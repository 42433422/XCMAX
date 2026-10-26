from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
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
    tmp_path: Path, rollback, stale
) -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text()
    current, site = tmp_path / "current", tmp_path / "site"
    for name, content in (
        ("active", '{"version":"1.0.0.6"}'),
        ("prepared", '{"version":"1.0.0.5"}' if stale else '{"version":"1.0.0.6"}'),
    ):
        target = tmp_path / name / "site"
        target.mkdir(parents=True)
        (target / "download-release.json").write_text(content)
    current.symlink_to(tmp_path / "active")
    site.symlink_to(current / "site")
    before = (site / "download-release.json").read_bytes()
    verify = re.search(r"verify_public_pointers\(\) \{.*?^}", script, re.M | re.S).group()
    # Isolate only filesystem guards/switches; no production commands or paths run.
    verify = verify.replace(
        '"/var/www/update/releases/stable/enterprise/download-windows-hotfix.json"',
        shlex.quote(str(tmp_path / "absent-hotfix")),
    )
    if rollback:
        body = re.search(r"rollback\(\) \{.*?^}", script, re.M | re.S).group()
        body += '\nrollback || status=$?; exit "${status:-0}"'  # errexit is suppressed here in real EXIT recovery.
    else:
        body = script[script.rindex('verify_public_pointers "$FINAL_ROOT"') :]
        body = body[: body.index("install_cli_launcher")]
    variables = {
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
    result = subprocess.run(
        [
            "bash",
            "-c",
            "set -e;\n"
            + setup
            + "\nlog() { :; }; fail() { exit 1; }; systemctl() { :; };\n"
            + verify
            + "\n"
            + body,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == (1 if stale else 0), result.stderr
    assert current.resolve() == tmp_path / ("active" if stale else "prepared")
    assert (site / "download-release.json").read_bytes() == before


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
