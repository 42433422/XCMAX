from __future__ import annotations

import hashlib
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = FHD_ROOT / "scripts" / "package" / "generate-download-manifest.py"
VERIFY_SCRIPT = FHD_ROOT / "scripts" / "deploy" / "verify-download.sh"
RELEASE_WORKFLOW = FHD_ROOT / ".github" / "workflows" / "release-desktop.yml"


def _generate(tmp_path: Path, *, include_enterprise_mac: bool = True) -> tuple[dict, dict]:
    release_root = tmp_path / "release" / "xcagi-v1.0.0.0"
    enterprise = release_root / "enterprise"
    personal = release_root / "personal"
    enterprise.mkdir(parents=True)
    personal.mkdir(parents=True)

    (enterprise / "XCAGI-Enterprise-Setup-1.0.0.0-x64.exe").write_bytes(b"MZenterprise")
    if include_enterprise_mac:
        (enterprise / "XCAGI-Enterprise-1.0.0.0-mac-arm64.dmg").write_bytes(b"enterprise-dmg")

    # A stale/future-compatible personal directory must never leak into stable output.
    (personal / "XCAGI-Personal-Setup-1.0.0.0-x64.exe").write_bytes(b"MZpersonal")
    (personal / "XCAGI-Personal-1.0.0.0-mac-arm64.dmg").write_bytes(b"personal-dmg")

    manifest_path = tmp_path / "manifest.json"
    release_path = tmp_path / "download-release.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            "1.0.0.0",
            "--release-dir",
            str(tmp_path / "release"),
            "--release-subdir",
            "xcagi-v1.0.0.0",
            "--git-sha",
            "abc123",
            "--output",
            str(manifest_path),
            "--download-release-output",
            str(release_path),
        ],
        check=True,
    )
    return json.loads(manifest_path.read_text()), json.loads(release_path.read_text())


def test_stable_manifest_is_enterprise_only_even_when_personal_files_exist(tmp_path: Path) -> None:
    manifest, public_release = _generate(tmp_path)

    assert manifest["release_ready"] is True
    assert manifest["active_skus"] == ["enterprise"]
    assert manifest["frozen_skus"] == ["personal"]
    assert manifest["primary_sku"] == "enterprise"
    for channel in manifest["channels"].values():
        assert "enterprise" in channel
        assert "personal" not in channel

    assert public_release["release_ready"] is True
    assert public_release["active_skus"] == ["enterprise"]
    assert public_release["frozen_skus"] == ["personal"]
    assert public_release["primary_sku"] == "enterprise"
    assert public_release["win_installer_mb"] == 0


def test_release_is_not_ready_without_enterprise_windows_and_macos(tmp_path: Path) -> None:
    manifest, public_release = _generate(tmp_path, include_enterprise_mac=False)

    assert manifest["release_ready"] is False
    assert public_release["release_ready"] is False


def test_release_workflow_uses_fhd_relative_download_verifier_path() -> None:
    workflow = RELEASE_WORKFLOW.read_text()

    assert (
        'bash scripts/deploy/verify-download.sh "${RUNNER_TEMP}/manifest/manifest.json"' in workflow
    )
    assert "bash FHD/scripts/deploy/verify-download.sh" not in workflow
    assert "verify_only:" in workflow
    assert "inputs.verify_only == true || needs.generate-manifest.result == 'success'" in workflow
    assert '"https://xiu-ci.com/xcagi-v${version}/manifest.json"' in workflow


def test_download_verifier_accepts_udif_trailer_and_propagates_failures(tmp_path: Path) -> None:
    web_root = tmp_path / "web"
    enterprise = web_root / "enterprise"
    enterprise.mkdir(parents=True)
    exe = enterprise / "XCAGI-Enterprise-Setup-1.0.0.0-x64.exe"
    dmg = enterprise / "XCAGI-Enterprise-1.0.0.0-mac-arm64.dmg"
    exe.write_bytes(b"MZ" + b"\0" * 1022)
    dmg.write_bytes(b"\0" * 512 + b"koly" + b"\0" * 508)

    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *args, directory=str(web_root), **kwargs
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    def entry(path: Path) -> dict:
        return {
            "url": f"{base_url}/enterprise/{path.name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "filename": path.name,
        }

    enterprise_entries = {"win": entry(exe), "mac": [entry(dmg)]}
    manifest = {
        "schema": "xcagi.download_manifest/v1",
        "version": "1.0.0.0",
        "release_ready": True,
        "active_skus": ["enterprise"],
        "frozen_skus": ["personal"],
        "primary_sku": "enterprise",
        "git_sha": "abc123",
        "generated_at": "2026-07-12T00:00:00Z",
        "channels": {
            "auto_update": {
                "base_url": base_url,
                "enterprise": enterprise_entries,
            },
            "official_download": {
                "base_url": base_url,
                "enterprise": enterprise_entries,
            },
        },
    }
    manifest_path = tmp_path / "verify-manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    try:
        passed = subprocess.run(
            ["bash", str(VERIFY_SCRIPT), str(manifest_path)],
            capture_output=True,
            text=True,
        )
        assert passed.returncode == 0, passed.stdout + passed.stderr
        assert passed.stdout.count("REUSE SHA256 already verified") == 2
        assert "PASS: 4" in passed.stdout

        manifest["channels"]["official_download"]["enterprise"]["win"]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        failed = subprocess.run(
            ["bash", str(VERIFY_SCRIPT), str(manifest_path)],
            capture_output=True,
            text=True,
        )
        assert failed.returncode == 1
        assert "SHA256 mismatch" in failed.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
