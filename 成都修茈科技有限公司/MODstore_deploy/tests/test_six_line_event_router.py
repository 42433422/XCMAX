"""六线事件轨路由器单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def routes_file(tmp_path, monkeypatch):
    cfg = {
        "operations_line": [
            {
                "id": "test-o7",
                "step_id": "O7",
                "status_in": ["progress"],
                "six_line": "ops_acquisition",
                "line_step": "O7",
                "action": "digest_backlog",
                "dispatch_line": "P-S",
                "list_kind": "patches",
                "priority": "P1",
                "also_incident": "ops.change_request.submitted",
            }
        ],
        "cross_line": [
            {
                "id": "test-xl",
                "from_step": "O7",
                "to_step": "P2",
                "six_line": "prod_software",
                "line_step": "P2",
                "action": "incident",
                "event_type": "ops.intake.task.queued",
                "priority": "P1",
            }
        ],
        "incident_defaults": [],
    }
    p = tmp_path / "six_line_event_routes.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("XCAGI_SIX_LINE_EVENT_ROUTES", str(p))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    from modstore_server import six_line_event_router as router

    router.reload_event_routes()
    return router


def test_operations_line_routes_to_backlog_and_incident(routes_file, monkeypatch):
    published = []

    def fake_publish(event_type, payload, *, source, fingerprint=None):
        published.append((event_type, source))
        return True

    monkeypatch.setattr(
        "modstore_server.incident_bus.publish",
        fake_publish,
    )
    out = routes_file.handle_operations_line_event(
        {"step_id": "O7", "status": "progress", "payload": {"summary": "用户反馈 UI 卡顿"}}
    )
    assert out["routed"] is True
    assert out["backlog"] is True
    assert out["published"] is True
    assert published[0][0] == "ops.change_request.submitted"


def test_cross_line_route(routes_file, monkeypatch):
    monkeypatch.setattr(
        "modstore_server.incident_bus.publish",
        lambda *a, **k: True,
    )
    out = routes_file.handle_cross_line_trigger(from_step="O7", to_step="P2", context={"k": 1})
    assert out["routed"] is True
    assert out["event_type"] == "ops.intake.task.queued"


def test_unknown_ops_step_not_routed(routes_file):
    out = routes_file.handle_operations_line_event({"step_id": "O99", "status": "progress"})
    assert out["routed"] is False


def test_merge_event_backlog_into_vibe_patches(routes_file):
    routes_file.append_digest_backlog(
        {
            "dispatch_line": "P-S",
            "priority": "P1",
            "task_brief": "修复登录页卡顿",
            "route_id": "oa-o7-feedback",
        }
    )
    merged, meta = routes_file.merge_event_backlog_into_vibe_patches(
        "# Vibe 预备 · 补丁清单\n\n## [fhd-core-maintainer]\n- **P2** 既有任务",
        consume=True,
    )
    assert meta["merged_count"] == 1
    assert "事件轨·oa-o7-feedback" in merged
    assert "修复登录页卡顿" in merged
    assert routes_file.read_digest_backlog_entries() == []
