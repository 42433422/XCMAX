"""Execute the native k6 program against deterministic transport boundary fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.loadtest.validate_evidence import validate_chat_soak

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "wrong_build",
        "degraded",
        "login",
        "missing",
        "unknown",
        "wrong_turn",
        "workload_override",
    ],
)
def test_native_k6_rejects_http_200_without_original_completed_turn(native_tool, tmp_path, fault):
    turns = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, payload, content_type="application/json"):
            body = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "csrf_token=fixture; Path=/")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == "/api/health":
                return self.reply(
                    {
                        "status": "degraded" if fault == "degraded" else "healthy",
                        "git_sha": "b" * 40 if fault == "wrong_build" else SHA,
                    }
                )
            session = path.path.removeprefix("/api/conversations/")
            turn = parse_qs(path.query)["turn_id"][0]
            assert turns[turn] == session
            payload = {"success": True, "id": session, "durable": True}
            if fault != "missing":
                payload["turn_receipt"] = {
                    "turn_id": "other-turn" if fault == "wrong_turn" else turn,
                    "durable": True,
                    "status": "unknown" if fault == "unknown" else "completed",
                    "requires_reconciliation": fault == "unknown",
                }
            self.reply(payload)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/auth/login":
                return self.reply({"success": fault != "login"})
            assert self.headers["X-CSRF-Token"] == "fixture"
            context = body["context"]
            assert context["turn_id"] not in turns, "k6 must not replay a chat POST"
            turns[context["turn_id"]] = context["session_id"]
            self.reply(
                'event: error\ndata: {"type": "error"}\n\n'
                if fault in {"missing", "unknown"}
                else 'event: done\ndata: {"type": "done"}\n\n',
                "text/event-stream",
            )

    binary = native_tool("k6")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    summary_path = tmp_path / "k6-7d-summary.json"
    try:
        result = subprocess.run(
            [
                binary,
                "run",
                "--quiet",
                "--out",
                f"json={tmp_path / 'k6-7d-samples.jsonl'}",
                str(ROOT / "scripts/observability/k6_7d_contract.js"),
            ],
            cwd=tmp_path,
            env={
                **os.environ,
                "XCAGI_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "E2E_USER": "synthetic-acceptance",
                "E2E_PASSWORD": "fixture-only",
                "SOURCE_SHA": SHA,
                "XCAGI_SOAK_DURATION": "1s",
                "K6_SUMMARY_PATH": str(summary_path),
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
                **({"K6_DURATION": "1s"} if fault == "workload_override" else {}),
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
        expected = 107 if fault == "workload_override" else (0 if fault == "none" else 99)
        assert result.returncode == expected, result.stdout + result.stderr
        if fault == "workload_override":
            assert not turns and "workload was overridden" in result.stderr
            return
        assert summary_path.exists(), result.stdout + result.stderr
        summary = json.loads(summary_path.read_text())
        assert summary["source_sha"] == SHA
        assert summary["test_profile"] == "chat-durable-turn/v1"
        assert summary["duration"] == "1s"
        assert summary["business_reconciliation"] is False
        assert summary["metrics"]["checks"]["thresholds"]["rate==1"]["ok"] is (fault == "none")
        assert summary["state"]["testRunDurationMs"] >= 1000
        if fault == "none":
            assert summary["metrics"]["chat_turns_verified"]["values"]["count"] >= 1
            assert len(turns) >= 1
            with pytest.raises(ValueError, match="shorter than"):
                validate_chat_soak(tmp_path, SHA)
            rejected = subprocess.run(
                ["bash", str(ROOT / "scripts/observability/run_staging_7d_acceptance.sh")],
                env={**os.environ, "SOURCE_SHA": SHA, "K6_EVIDENCE_DIR": str(tmp_path)},
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert rejected.returncode != 0
            assert "shorter than" in rejected.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
