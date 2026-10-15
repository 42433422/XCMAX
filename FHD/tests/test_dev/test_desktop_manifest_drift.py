"""审计 R03：桌面下载中心 manifest 漂移检测器的行为测试.

用本地 HTTP 服务提供受控 manifest 与制品，验证：
- 一致时通过；
- 声明 size 与实际不符时 fail-closed 并列出漂移项；
- 制品不可达时 fail-closed；
- manifest 版本与请求版本不符时 fail-closed。
"""

from __future__ import annotations

import hashlib
import http.server
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "dev" / "verify_desktop_manifest_drift.py"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    payload: dict[str, bytes] = {}

    def do_GET(self) -> None:  # noqa: N802
        body = self.payload.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        body = self.payload.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

    def log_message(self, *args: object) -> None:  # silence
        return


def _serve(payload: dict[str, bytes]) -> tuple[http.server.ThreadingHTTPServer, str]:
    _Handler.payload = payload
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}"


def _stop(server: http.server.ThreadingHTTPServer) -> None:
    """停止服务并关闭监听 socket，避免未处理异常告警干扰断言。"""
    server.shutdown()
    server.server_close()


def _manifest(artifact_size: int, artifact_sha: str) -> bytes:
    return json.dumps(
        {
            "version": "9.9.9.9",
            "git_sha": "a" * 40,
            "channels": {
                "official_download": {
                    "enterprise": {
                        "mac": [
                            {
                                "filename": "app.dmg",
                                "url": "/artifacts/app.dmg",
                                "size": artifact_size,
                                "sha256": artifact_sha,
                            }
                        ]
                    }
                }
            },
        }
    ).encode()


def _run(base_url: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    import os

    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    env["NO_PROXY"] = "127.0.0.1,localhost"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            "9.9.9.9",
            "--base-url",
            base_url,
            "--output",
            str(tmp_path / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_consistent_manifest_passes(tmp_path: Path) -> None:
    artifact = b"x" * 1000
    payload = {
        "/xcagi-v9.9.9.9/manifest.json": _manifest(
            len(artifact), hashlib.sha256(artifact).hexdigest()
        ),
        "/artifacts/app.dmg": artifact,
    }
    server, base = _serve(payload)
    try:
        proc = _run(base, tmp_path)
    finally:
        _stop(server)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["passed"] is True
    assert report["entries_checked"] == 1
    assert report["drift"] == []


def test_declared_size_mismatch_fails_closed(tmp_path: Path) -> None:
    artifact = b"x" * 1000
    payload = {
        "/xcagi-v9.9.9.9/manifest.json": _manifest(999_999, hashlib.sha256(artifact).hexdigest()),
        "/artifacts/app.dmg": artifact,
    }
    server, base = _serve(payload)
    try:
        proc = _run(base, tmp_path)
    finally:
        _stop(server)
    assert proc.returncode == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["passed"] is False
    assert report["drift"][0]["reason"] == "size_mismatch"
    assert report["drift"][0]["actual_size"] == 1000


def test_unreachable_artifact_fails_closed(tmp_path: Path) -> None:
    payload = {"/xcagi-v9.9.9.9/manifest.json": _manifest(10, "0" * 64)}
    server, base = _serve(payload)
    try:
        proc = _run(base, tmp_path)
    finally:
        _stop(server)
    assert proc.returncode == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["drift"][0]["reason"] == "artifact_unreachable"


def test_manifest_version_mismatch_fails_closed(tmp_path: Path) -> None:
    payload = {"/xcagi-v9.9.9.9/manifest.json": json.dumps({"version": "1.2.3.4"}).encode()}
    server, base = _serve(payload)
    try:
        proc = _run(base, tmp_path)
    finally:
        _stop(server)
    assert proc.returncode == 1
    assert "manifest_version_mismatch" in proc.stdout
