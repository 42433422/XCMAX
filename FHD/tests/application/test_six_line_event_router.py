"""六线事件轨路由匹配与 backlog 写入。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.application.six_line_event_app_service import SixLineEventAppService
from app.infrastructure.six_line import event_route_loader as loader


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    src = Path(__file__).resolve().parents[2] / "config" / "six_line_event_routes.json"
    (cfg_dir / "six_line_event_routes.json").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    cs = tmp_path / "customer_service"
    cs.mkdir()

    def fake_base_dir():
        return str(tmp_path)

    def fake_data_dir():
        return str(tmp_path)

    monkeypatch.setattr(loader, "_config_path", lambda: cfg_dir / "six_line_event_routes.json")
    monkeypatch.setattr(loader, "_customer_service_dir", lambda: cs)
    return SixLineEventAppService()


def test_match_o7_backlog(svc: SixLineEventAppService):
    route = svc.match_route(step_id="O7", status="progress")
    assert route is not None
    assert route.action == "digest_backlog"
    assert route.dispatch_line == "P-S"


def test_dispatch_payment_anomaly_incident(svc: SixLineEventAppService, tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "_customer_service_dir", lambda: tmp_path / "customer_service")
    (tmp_path / "customer_service").mkdir(exist_ok=True)
    out = svc.dispatch({"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"})
    assert out["matched"] is True
    assert out["action"] == "incident"
    outbox = tmp_path / "customer_service" / "incident_outbox.jsonl"
    assert outbox.is_file()


def test_dispatch_o7_writes_backlog(svc: SixLineEventAppService, tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "_customer_service_dir", lambda: tmp_path / "customer_service")
    (tmp_path / "customer_service").mkdir(exist_ok=True)
    out = svc.dispatch({"step_id": "O7", "status": "completed", "payload": {"ticket": 1}})
    assert out["matched"] is True
    bl = tmp_path / "customer_service" / "six_line_digest_backlog.jsonl"
    assert bl.is_file()
    row = json.loads(bl.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["dispatch_line"] == "P-S"


def test_status_snapshot_counts(svc: SixLineEventAppService):
    snap = svc.status_snapshot()
    assert snap["operations_routes"] >= 10
    assert "cross_line_routes" in snap
