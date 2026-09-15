"""连接件4（客户侧重测）测试：对模拟客户应用的 HTTP 服务执行重测并落回执。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

_FHD_ROOT = Path(__file__).resolve().parents[2]


def _load_repro() -> Any:
    path = _FHD_ROOT / "scripts/dev/work_order_repro.py"
    spec = importlib.util.spec_from_file_location("work_order_repro_c4", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["work_order_repro_c4"] = module
    spec.loader.exec_module(module)
    return module


def _load_retest() -> Any:
    path = _FHD_ROOT / "scripts/dev/customer_retest.py"
    spec = importlib.util.spec_from_file_location("customer_retest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["customer_retest"] = module
    spec.loader.exec_module(module)
    return module


retest_mod = _load_retest()


class _FakeAppHandler(BaseHTTPRequestHandler):
    """模拟客户机上的 XCAGI 应用：/api/health + 可配置的路由状态。"""

    retest_status = 200
    health_version = "1.0.0.4"

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/health"):
            body = json.dumps({"status": "healthy", "version": self.health_version}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/mods/faulty/"):
            self.send_response(self.retest_status)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def fake_app(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), _FakeAppHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}", server
    server.shutdown()
    server.server_close()


def _spec(retest_url: str = "/mods/faulty/page") -> dict[str, Any]:
    return {
        "dedup_key": "abcd1234" * 8,
        "wo_id": "WO-c4",
        "kind": "module_import",
        "scenario": {"module": "mods.faulty.route", "retest_url": retest_url},
    }


class TestRetest:
    def test_pass_when_all_checks_ok(self, tmp_path: Path, fake_app) -> None:
        base_url, _ = fake_app
        receipt = retest_mod.retest(_spec(), base_url)
        assert receipt["verdict"] == "pass"
        assert receipt["app_version"] == "1.0.0.4"
        names = [c["name"] for c in receipt["checks"]]
        assert "app_health" in names and "scenario_retest" in names

    def test_fail_when_scenario_route_404(self, tmp_path: Path, monkeypatch, fake_app) -> None:
        base_url, _ = fake_app
        _FakeAppHandler.retest_status = 404
        try:
            receipt = retest_mod.retest(_spec(), base_url)
        finally:
            _FakeAppHandler.retest_status = 200
        assert receipt["verdict"] == "fail"
        scenario_check = next(c for c in receipt["checks"] if c["name"] == "scenario_retest")
        assert scenario_check["ok"] is False
        assert scenario_check["status"] == 404

    def test_fail_on_version_mismatch(self, fake_app) -> None:
        base_url, _ = fake_app
        receipt = retest_mod.retest(_spec(), base_url, expect_version="1.0.0.5")
        assert receipt["verdict"] == "fail"

    def test_health_payload_not_json_fails(self, fake_app) -> None:
        base_url, _ = fake_app

        class BrokenHandler(_FakeAppHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"not-json")

        server = HTTPServer(("127.0.0.1", 0), BrokenHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            receipt = retest_mod.retest(_spec(), f"http://127.0.0.1:{server.server_address[1]}")
        finally:
            server.shutdown()
            server.server_close()
        assert receipt["verdict"] == "fail"

    def test_health_payload_longer_than_snippet_still_parses(self, fake_app) -> None:
        """回归：真实 health 载荷超过 400 字符时不得因截断而解析失败。"""
        base_url, _ = fake_app

        class FatHealthHandler(_FakeAppHandler):
            def do_GET(self):  # noqa: N802
                if self.path.startswith("/api/health"):
                    payload = {
                        "status": "healthy",
                        "version": "1.0.0.4",
                        "runtime": {"components": {f"c{i}": "ok" for i in range(40)}},
                    }
                    body = json.dumps(payload).encode()
                    assert len(body) > 400
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/mods/faulty/"):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                else:
                    self.send_response(404)
                    self.end_headers()

        server = HTTPServer(("127.0.0.1", 0), FatHealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            receipt = retest_mod.retest(
                _spec(),
                f"http://127.0.0.1:{server.server_address[1]}",
                expect_version="1.0.0.4",
            )
        finally:
            server.shutdown()
            server.server_close()
        assert receipt["verdict"] == "pass", receipt
        assert receipt["app_version"] == "1.0.0.4"

    def test_receipt_written_and_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_app
    ) -> None:
        base_url, _ = fake_app
        out = tmp_path / "retest"
        monkeypatch.setenv("WORK_ORDER_RETEST_DIR", str(out))
        monkeypatch.setenv("WORK_ORDER_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
        monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(tmp_path / "none"))
        rc = retest_mod.main(["--spec", str(_write_spec(tmp_path)), "--base-url", base_url])
        assert rc == 0
        receipts = list(out.glob("receipt-*.json"))
        assert len(receipts) == 1
        data = json.loads(receipts[0].read_text(encoding="utf-8"))
        assert data["verdict"] == "pass"

    def test_exit_2_on_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_app
    ) -> None:
        base_url, _ = fake_app
        monkeypatch.setenv("WORK_ORDER_RETEST_DIR", str(tmp_path / "retest"))
        monkeypatch.setenv("WORK_ORDER_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
        monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(tmp_path / "none"))
        _FakeAppHandler.retest_status = 500
        try:
            rc = retest_mod.main(["--spec", str(_write_spec(tmp_path)), "--base-url", base_url])
        finally:
            _FakeAppHandler.retest_status = 200
        assert rc == 2


def _write_spec(tmp_path: Path) -> Path:
    repro = _load_repro()
    out = tmp_path / "repro"
    repro._REPRO_DIR = out
    out.mkdir(parents=True, exist_ok=True)
    path = out / "repro-abcd1234abcd.json"
    path.write_text(json.dumps(_spec(), ensure_ascii=False), encoding="utf-8")
    return path
