from __future__ import annotations


def _reset_action_items_table() -> None:
    from sqlalchemy import text

    from modstore_server.digest_action_items import ensure_table
    from modstore_server.models import get_engine

    ensure_table()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM daily_action_items"))


def test_parse_skips_low_signal_action_items(monkeypatch):
    monkeypatch.delenv("MODSTORE_ACTION_ITEMS_KEEP_LOW_SIGNAL", raising=False)
    _reset_action_items_table()

    from modstore_server.digest_action_items import list_action_items, parse_and_store_action_items

    updates = """
# Vibe 预备 · 更新清单

## [worker-a] Worker A · v1
- scope：`x`
- **P2** 复核 handlers 注册与 yuangon 目录结构一致
- **P1** 修复 P-S 页面标题/Head 管理：业务路由标题错误
- **P1** 修复付款回调签名校验失败
"""
    patches = """
# Vibe 预备 · 补丁清单

## [worker-a] Worker A · v1
- scope：`x`
- **P2** 暂无 recent_failures；按摘要「待审改动 / pytest」段落人工复核是否需要补丁
- **P0** 修复近期失败：Server disconnected without sending a response.
- **P0** 修复近期失败：{'task': 'craft pipeline step: workflow', 'status': 'skipped', 'error': ''}
- **P0** 修复近期失败：{'status': 'blocked_by_risk_gate', 'error': ''}
"""

    out = parse_and_store_action_items(
        day="2026-06-28",
        record_id=1,
        updates_markdown=updates,
        patches_markdown=patches,
        rt_version="test",
    )

    assert out["update"] == 1
    assert out["patch"] == 0
    rows = list_action_items(day="2026-06-28", limit=20)
    assert [row["text"] for row in rows] == ["**P1** 修复付款回调签名校验失败"]


def test_parse_compacts_cross_day_duplicate_open_items(monkeypatch):
    monkeypatch.delenv("MODSTORE_ACTION_ITEMS_KEEP_LOW_SIGNAL", raising=False)
    _reset_action_items_table()

    from sqlalchemy import text

    from modstore_server.digest_action_items import parse_and_store_action_items, stats
    from modstore_server.models import get_engine

    markdown = """
# Vibe 预备 · 补丁清单

## [worker-a] Worker A · v1
- scope：`x`
- **P1** 修复 catalog 404 并补充回归断言
"""

    first = parse_and_store_action_items(
        day="2026-06-27",
        record_id=1,
        patches_markdown=markdown,
        rt_version="test",
    )
    second = parse_and_store_action_items(
        day="2026-06-28",
        record_id=2,
        patches_markdown=markdown,
        rt_version="test",
    )

    assert first["patch"] == 1
    assert second["patch"] == 1
    assert second["closed_duplicates"] == 1

    with get_engine().begin() as conn:
        rows = conn.execute(
            text("SELECT day, status FROM daily_action_items ORDER BY day")
        ).all()
    assert rows == [("2026-06-27", "closed"), ("2026-06-28", "open")]

    latest = stats(day="2026-06-28")
    assert latest["total"] == 1
    assert latest["by_status"] == {"open": 1}
