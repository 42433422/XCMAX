from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/sync_site_download_release.py"


def _history(version: str) -> list[dict]:
    return [{"version": version, "date": "2026-10-17", "title": "t", "notes": ["n"]}]


def _run(tmp: Path, version: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--site-root",
            str(tmp / "site"),
            "--ssot",
            str(tmp / "ssot.json"),
            "--version",
            version,
            "--git-sha",
            "a" * 40,
            "--release-root",
            str(tmp / "www"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _site(tmp: Path, ssot_version: str) -> Path:
    site = tmp / "site"
    (site / "MODstore_deploy/market/public").mkdir(parents=True)
    (site / "download-release.json").write_text(
        json.dumps(
            {
                "version_lock": "1.0.0.1",
                "release_history": _history("1.0.0.1"),
                "primary_sku": "enterprise",
            }
        )
    )
    (tmp / "ssot.json").write_text(
        json.dumps(
            {
                "version_lock": ssot_version,
                "download_version": ssot_version,
                "release_history": _history(ssot_version),
            }
        )
    )
    return site


def test_stale_git_copy_is_replaced_from_ssot_for_every_mirror(tmp_path: Path) -> None:
    site = _site(tmp_path, "1.0.0.6")
    assert _run(tmp_path, "1.0.0.6").returncode == 0
    for path in (
        site / "download-release.json",
        site / "MODstore_deploy/market/public/download-release.json",
    ):
        data = json.loads(path.read_text())
        assert (
            data["version_lock"],
            data["release_history"][0]["version"],
            data["primary_sku"],
        ) == ("1.0.0.6", "1.0.0.6", "enterprise")
    assert not (site / "corp-butler/download-release.json").exists()


def test_release_managed_pointer_wins_and_version_mismatch_fails_closed(tmp_path: Path) -> None:
    site = _site(tmp_path, "1.0.0.6")
    build = tmp_path / "www/update/releases/builds/1.0.0.6/" / ("b" * 40)
    build.mkdir(parents=True)
    (build / "download-release.json").write_text(
        json.dumps(
            {
                "version_lock": "1.0.0.6",
                "release_history": _history("1.0.0.6"),
                "release_ready": True,
            }
        )
    )
    assert _run(tmp_path, "1.0.0.6").returncode == 0
    assert json.loads((site / "download-release.json").read_text())["release_ready"] is True
    failed = _run(tmp_path, "1.0.0.7")
    assert failed.returncode == 1 and "1.0.0.7" in failed.stderr


def test_immutable_release_runs_sync_before_freezing_the_tree() -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text(encoding="utf-8")
    sync = script.index("sync_site_download_release.py")
    assert script.index("npm run build", 0) < sync < script.index('chmod -R a-w "$BUILD_ROOT"')
    assert '--version "$PRODUCT_VERSION"' in script[sync : sync + 300]
