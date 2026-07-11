from __future__ import annotations

import functools
import hashlib
import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy/verify-download.sh"


@pytest.fixture
def download_server(tmp_path: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def write_manifest(tmp_path: Path, url: str, filename: str, content: bytes, sha256: str) -> Path:
    manifest = {
        "schema": "xcagi.download_manifest/v1",
        "version": "10.0.0",
        "git_sha": "test",
        "generated_at": "2026-07-11T00:00:00+00:00",
        "channels": {
            "official_download": {
                "base_url": url.rsplit("/", 1)[0],
                "enterprise": {
                    "mac" if filename.endswith(".dmg") else "win": (
                        [{"url": url, "sha256": sha256, "size": len(content), "filename": filename}]
                        if filename.endswith(".dmg")
                        else {"url": url, "sha256": sha256, "size": len(content), "filename": filename}
                    )
                },
            }
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def run_verify(manifest: Path) -> subprocess.CompletedProcess[str]:
    if shutil.which("jq") is None or shutil.which("xxd") is None:
        pytest.skip("download verifier requires jq and xxd")
    return subprocess.run(
        ["bash", str(SCRIPT), str(manifest)],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_sha_failure_is_not_lost_after_loop(tmp_path: Path, download_server: str) -> None:
    filename = "XCAGI-Enterprise-Setup-10.0.0-x64.exe"
    content = b"MZ" + b"candidate"
    (tmp_path / filename).write_bytes(content)
    manifest = write_manifest(
        tmp_path,
        f"{download_server}/{filename}",
        filename,
        content,
        "0" * 64,
    )

    result = run_verify(manifest)

    assert result.returncode == 1
    assert "SHA256 mismatch" in result.stdout
    assert "FAIL: 1" in result.stdout


def test_dmg_uses_koly_trailer_and_passes(tmp_path: Path, download_server: str) -> None:
    filename = "XCAGI-10.0.0-mac-arm64.dmg"
    content = b"payload" + b"koly" + bytes(508)
    (tmp_path / filename).write_bytes(content)
    manifest = write_manifest(
        tmp_path,
        f"{download_server}/{filename}",
        filename,
        content,
        hashlib.sha256(content).hexdigest(),
    )

    result = run_verify(manifest)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK file magic" in result.stdout
    assert "PASS: 1" in result.stdout


def test_missing_schema_is_rejected_before_download(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"channels": {}}), encoding="utf-8")

    result = run_verify(manifest)

    assert result.returncode == 2
    assert "Unsupported or missing manifest schema" in result.stderr
