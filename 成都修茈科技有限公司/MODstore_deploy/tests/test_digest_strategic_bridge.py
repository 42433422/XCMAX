"""digest_action_items → strategic_action_items 桥接测试。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select, text

from modstore_server.db.base import get_session_factory, init_db
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.digest_action_items import (
    list_action_items,
    parse_and_store_action_items,
    set_status,
)
from modstore_server.strategic_layer import (
    TRACK_ACTION,
    TRACK_SCOPE,
    seed_default_boundaries,
    sync_daily_to_strategic,
)
from modstore_server.strategic_layer.digest_strategic_bridge import mirror_daily_status


@pytest.fixture(scope="module", autouse=True)
def _ensure_db():
    init_db()
    yield


@pytest.fixture(autouse=True)
def _seed_and_reset(monkeypatch):
    monkeypatch.setenv("MODSTORE_STRATEGIC_LAYER_INTEGRATION_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_ACTION_ITEMS_KEEP_LOW_SIGNAL", "1")
    seed_default_boundaries()
    from modstore_server.digest_action_items import ensure_table
    from modstore_server.models import get_engine

    ensure_table()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM daily_action_items"))
    session = get_session_factory()()
    try:
        # 仅清本桥接相关镜像，避免拖垮其它战略层测试数据
        session.execute(text("DELETE FROM strategic_action_items WHERE action_id LIKE 'act-dai-%'"))
        session.execute(
            text("DELETE FROM strategic_decisions WHERE scope = :scope"),
            {"scope": TRACK_SCOPE},
        )
        session.commit()
    finally:
        session.close()
    yield


def _store_sample(*, record_id: int = 9001, day: str = "2026-07-21") -> dict:
    patches = """
# Vibe 预备 · 补丁清单

## [worker-bridge] Bridge Worker · v1
- scope：`FHD/app`
- **P0** 修复桥接回归：digest 条目必须镜像到战略层
"""
    updates = """
# Vibe 预备 · 更新清单

## [worker-bridge] Bridge Worker · v1
- scope：`FHD/frontend`
- **P1** 推进桥接看板口径：页头标注 daily + strategic 双轨
"""
    return parse_and_store_action_items(
        day=day,
        record_id=record_id,
        patches_markdown=patches,
        updates_markdown=updates,
        rt_version="1.0.0.0",
    )


class TestDigestStrategicBridge:
    def test_sync_creates_decision_and_action_items(self):
        stored = _store_sample()
        assert stored["ok"] is True
        assert stored["patch"] >= 1
        assert stored["update"] >= 1

        out = sync_daily_to_strategic(
            record_id=9001,
            release_kind="daily",
            release_train="1.0.0.0",
        )
        assert out["ok"] is True
        assert out["created"] >= 2
        assert out.get("decision_id")

        session = get_session_factory()()
        try:
            dec = session.execute(
                select(StrategicDecision).where(StrategicDecision.decision_id == out["decision_id"])
            ).scalar_one()
            assert dec.scope == TRACK_SCOPE
            assert dec.scope_ref == "9001"
            payload = json.loads(dec.decision_payload_json or "{}")
            assert payload.get("action") == TRACK_ACTION
            assert dec.autonomy_action == "report_only"
            assert dec.status == "auto_approved"

            rows = (
                session.execute(
                    select(StrategicActionItem).where(
                        StrategicActionItem.decision_id == out["decision_id"]
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) >= 2
            for row in rows:
                assert row.action_id.startswith("act-dai-")
                payload = json.loads(row.result_json or "{}")
                assert payload.get("daily_action_item_id")
                assert payload.get("record_id") == 9001
                assert row.status == "pending"
        finally:
            session.close()

    def test_sync_is_idempotent(self):
        _store_sample(record_id=9002, day="2026-07-22")
        first = sync_daily_to_strategic(record_id=9002)
        second = sync_daily_to_strategic(record_id=9002)
        assert first["ok"] is True
        assert second["ok"] is True
        assert first["created"] >= 1
        assert second["created"] == 0
        assert second["updated"] >= 1
        assert first["decision_id"] == second["decision_id"]

    def test_status_mirror_open_to_merged(self):
        _store_sample(record_id=9003, day="2026-07-23")
        sync = sync_daily_to_strategic(record_id=9003)
        assert sync["ok"] is True

        items = list_action_items(record_id=9003, limit=20)
        assert items
        daily_id = int(items[0]["id"])

        assert set_status(daily_id, "dispatched")["ok"] is True
        mirrored = mirror_daily_status(daily_id, "dispatched")
        assert mirrored["ok"] is True
        assert mirrored["status"] == "in_progress"

        assert set_status(daily_id, "merged")["ok"] is True
        mirrored2 = mirror_daily_status(daily_id, "merged")
        assert mirrored2["ok"] is True
        assert mirrored2["status"] == "completed"

        # 全量再 sync 也应保持 completed
        again = sync_daily_to_strategic(record_id=9003)
        assert again["ok"] is True
        session = get_session_factory()()
        try:
            row = session.execute(
                select(StrategicActionItem).where(
                    StrategicActionItem.action_id == f"act-dai-{daily_id}"
                )
            ).scalar_one()
            assert row.status == "completed"
            assert row.completed_at is not None
        finally:
            session.close()

    def test_disabled_env_skips(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_STRATEGIC_LAYER_INTEGRATION_ENABLED", "0")
        _store_sample(record_id=9004, day="2026-07-24")
        out = sync_daily_to_strategic(record_id=9004)
        assert out["ok"] is True
        assert out.get("skipped") is True
        assert "disabled" in str(out.get("reason") or "")
