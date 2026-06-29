"""employee_circle_sync 单测：MODstore 汇报流 → ai_circle 动态投影、过滤、去重计数、节流、降级。"""

from __future__ import annotations

import asyncio

import pytest

from app.application import employee_circle_sync as sync


@pytest.fixture(autouse=True)
def _reset():
    sync._last_sync = None
    yield
    sync._last_sync = None


_NEW = object()


def _install(monkeypatch, *, threads, messages_by_tid, upsert_returns=_NEW):
    async def fake_get(path, **kw):
        if path.endswith("/messages"):
            tid = int(path.rsplit("/", 2)[1])
            return {"items": messages_by_tid.get(tid, []), "count": 0}
        return {"items": threads, "count": len(threads)}

    calls: list[dict] = []

    def fake_upsert(**kwargs):
        calls.append(kwargs)
        if upsert_returns is _NEW:
            return len(calls)  # truthy new id
        return upsert_returns

    monkeypatch.setattr(sync, "modstore_get", fake_get)
    monkeypatch.setattr("app.application.ai_circle_service.upsert_employee_post", fake_upsert)
    return calls


def test_projects_only_report_threads(monkeypatch):
    calls = _install(
        monkeypatch,
        threads=[
            {"id": 5, "title": "[员工交流圈] P-S 软件部 · dept=prod_software"},
            {"id": 9, "title": "随便一个别的线程"},
        ],
        messages_by_tid={
            5: [
                {
                    "id": 12,
                    "sender_employee_id": "fhd-core-maintainer",
                    "content": "今日行动条目 共 2 项",
                    "created_at": "2026-06-22T08:10:00Z",
                },
                {"id": 13, "sender_employee_id": "", "content": "无主，应跳过"},
            ],
            9: [{"id": 99, "sender_employee_id": "x", "content": "不该被扫到"}],
        },
    )
    out = asyncio.run(sync.sync_modstore_reports(force=True))
    assert out["ok"] and out["synced"] == 1
    assert len(calls) == 1
    assert calls[0]["employee_id"] == "fhd-core-maintainer"
    assert calls[0]["source_ref"] == "modstore-collab:12"
    assert "行动条目" in calls[0]["body"]


def test_dedupe_counts_zero_when_exists(monkeypatch):
    calls = _install(
        monkeypatch,
        threads=[{"id": 5, "title": "[员工交流圈] 公司大会 / 编排 · dept=company"}],
        messages_by_tid={
            5: [{"id": 7, "sender_employee_id": "meeting-chair", "content": "每日员工大会纪要"}]
        },
        upsert_returns=None,  # 已存在
    )
    out = asyncio.run(sync.sync_modstore_reports(force=True))
    assert out["synced"] == 0 and out["scanned"] == 1
    assert len(calls) == 1  # 仍尝试 upsert（由其内部去重）


def test_throttled_second_call_skips(monkeypatch):
    _install(monkeypatch, threads=[], messages_by_tid={})
    first = asyncio.run(sync.sync_modstore_reports())
    assert first.get("skipped") is not True
    second = asyncio.run(sync.sync_modstore_reports())
    assert second.get("skipped") is True


def test_threads_unreachable_degrades(monkeypatch):
    async def boom(path, **kw):
        raise RuntimeError("modstore down")

    monkeypatch.setattr(sync, "modstore_get", boom)
    out = asyncio.run(sync.sync_modstore_reports(force=True))
    assert out["ok"] is False and out["synced"] == 0
