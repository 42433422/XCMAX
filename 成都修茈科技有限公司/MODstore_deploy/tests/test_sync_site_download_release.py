from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/sync_site_download_release.py"


def _history(version: str) -> list[dict]:
    return [{"version": version, "date": "2026-10-17", "title": "t", "notes": ["n"]}]


def _run(tmp: Path, version: str) -> subprocess.CompletedProcess[str]:
    cli = f"--site-root {tmp}/site --ssot {tmp}/ssot.json --release-root {tmp}/www"
    cli += f" --version {version}"
    argv = [sys.executable, str(SCRIPT), *cli.split(), "--git-sha", "a" * 40]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _site(tmp: Path, ver: str) -> Path:
    site = tmp / "site"
    (site / "MODstore_deploy/market/public").mkdir(parents=True)
    stale = {
        "version_lock": "1.0.0.1",
        "release_history": _history("1.0.0.1"),
        "primary_sku": "enterprise",
    }
    stale["release_root"] = "https://xiu-ci.com/xcagi-v1.0.0.1"
    (site / "download-release.json").write_text(json.dumps(stale))
    ssot = {"version_lock": ver, "download_version": ver, "release_history": _history(ver)}
    (tmp / "ssot.json").write_text(json.dumps(ssot))
    return site


def test_stale_git_copy_is_replaced_from_ssot_for_every_mirror(tmp_path: Path) -> None:
    site = _site(tmp_path, "1.0.0.6")
    assert _run(tmp_path, "1.0.0.6").returncode == 0
    for path in (
        site / "download-release.json",
        site / "MODstore_deploy/market/public/download-release.json",
    ):
        d = json.loads(path.read_text())
        assert (d["version_lock"], d["release_history"][0]["version"], d["primary_sku"]) == (
            "1.0.0.6",
        ) * 2 + ("enterprise",)
    assert not (site / "corp-butler/download-release.json").exists()


def test_release_managed_pointer_wins_and_version_mismatch_fails_closed(tmp_path: Path) -> None:
    site = _site(tmp_path, "1.0.0.6")
    build = tmp_path / "www/update/releases/builds/1.0.0.6/" / ("b" * 40)
    build.mkdir(parents=True)
    pointer = {
        "version_lock": "1.0.0.6",
        "release_history": _history("1.0.0.6"),
        "release_ready": True,
    }
    (build / "download-release.json").write_text(json.dumps(pointer))
    assert _run(tmp_path, "1.0.0.6").returncode == 0
    assert json.loads((site / "download-release.json").read_text())["release_ready"] is True
    failed = _run(tmp_path, "1.0.0.7")
    assert failed.returncode == 1 and "1.0.0.7" in failed.stderr


def test_immutable_release_runs_sync_before_freezing_the_tree() -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text(encoding="utf-8")
    sync = script.index("sync_site_download_release.py")
    assert script.index("npm run build", 0) < sync < script.index('chmod -R a-w "$BUILD_ROOT"')
    assert '--version "$PRODUCT_VERSION"' in script[sync : sync + 300]


def _accept(tmp: Path, payload: bytes, recorded: bytes) -> None:
    vdir = tmp / "www/xcagi-v1.0.0.6"
    (vdir / "enterprise").mkdir(parents=True)
    (vdir / "enterprise/setup.exe").write_bytes(payload)
    pkg = {
        "file": "setup.exe",
        "bytes": len(recorded),
        "sha256": hashlib.sha256(recorded).hexdigest(),
        "platform": "windows_x64",
    }
    record = {"version": "1.0.0.6", "publicationState": "verified", "packages": [pkg]}
    record.update(installationLifecycleAcceptance="PASS", publicFullDownloadVerification="PASS")
    (vdir / "manual-download-manifest.json").write_text(json.dumps(record))


def test_ssot_fallback_recomputes_release_urls_and_gates_release_ready(tmp_path: Path) -> None:
    site = _site(tmp_path, "1.0.0.6")
    _accept(tmp_path, b"x" * 3 * 1048576, b"y" * 3 * 1048576)  # same size, wrong hash
    assert _run(tmp_path, "1.0.0.6").returncode == 0
    data = json.loads((site / "download-release.json").read_text())
    root = "https://xiu-ci.com/xcagi-v1.0.0.6"
    assert (data["release_root"], data["cos_base_url"], data["manifest_url"]) == (
        root,
        root,
        root + "/manifest.json",
    )
    assert data["release_ready"] is False
    (tmp_path / "www/xcagi-v1.0.0.6/enterprise/setup.exe").write_bytes(b"y" * 3 * 1048576)
    assert _run(tmp_path, "1.0.0.6").returncode == 0
    data = json.loads((site / "download-release.json").read_text())
    assert (data["release_ready"], data["win_installer_mb"]) == (True, 3)
