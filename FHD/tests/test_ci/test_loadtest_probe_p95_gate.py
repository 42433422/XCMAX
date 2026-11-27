"""Tests for scripts/loadtest/probe.py P95 latency and error-rate budget gates."""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]


def _load_probe():
    spec = importlib.util.spec_from_file_location(
        "loadtest_probe", FHD / "scripts/loadtest/probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, _fmt, *args):
        return

    def do_GET(self):
        if self.path == "/slow":
            time.sleep(0.04)
        if self.path == "/fail":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"ok":false}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


def _start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_probe_regular_pages_passes_under_500ms_p95_budget_and_writes_json(tmp_path, monkeypatch):
    server = _start_server()
    try:
        out = tmp_path / "p95-report.json"
        monkeypatch.setenv("SOURCE_SHA", "b" * 40)
        rc = probe.main(
            [
                "--base",
                f"http://127.0.0.1:{server.server_port}",
                "--suite",
                "regular-pages",
                "--workers",
                "4",
                "--total",
                "12",
                "--max-p95-ms",
                "500",
                "--max-error-rate",
                "0.0",
                "--json-out",
                str(out),
            ]
        )
        assert rc == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["passed"] is True
        assert report["source_sha"] == "b" * 40
        assert report["suite"] == "regular-pages"
        assert report["budgets"] == {"max_p95_ms": 500.0, "max_error_rate": 0.0}
        assert len(report["results"]) == 4
        assert all(item["passed"] is True and item["p95_ms"] <= 500.0 for item in report["results"])
    finally:
        server.shutdown()
        server.server_close()


def test_probe_fails_when_p95_exceeds_budget_or_http_errors_occur(tmp_path):
    server = _start_server()
    try:
        slow_out = tmp_path / "slow.json"
        rc_slow = probe.main(
            [
                "--base",
                f"http://127.0.0.1:{server.server_port}",
                "--path",
                "/slow",
                "--workers",
                "2",
                "--total",
                "6",
                "--max-p95-ms",
                "15",
                "--json-out",
                str(slow_out),
            ]
        )
        assert rc_slow == 1
        slow_report = json.loads(slow_out.read_text(encoding="utf-8"))
        assert slow_report["passed"] is False
        assert any(
            r.startswith("p95_ms_exceeded:") for r in slow_report["results"][0]["failure_reasons"]
        )

        fail_out = tmp_path / "fail.json"
        rc_fail = probe.main(
            [
                "--base",
                f"http://127.0.0.1:{server.server_port}",
                "--path",
                "/fail",
                "--workers",
                "2",
                "--total",
                "4",
                "--max-p95-ms",
                "500",
                "--max-error-rate",
                "0.0",
                "--json-out",
                str(fail_out),
            ]
        )
        assert rc_fail == 1
        fail_report = json.loads(fail_out.read_text(encoding="utf-8"))
        assert fail_report["passed"] is False
        assert any(
            r.startswith("error_rate_exceeded:")
            for r in fail_report["results"][0]["failure_reasons"]
        )
    finally:
        server.shutdown()
        server.server_close()
