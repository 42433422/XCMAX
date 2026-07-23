from __future__ import annotations

import json

from modstore_server.public_company_hall import (
    DEPARTMENT_ORDER,
    _publicize_feed_text,
    _sort_feed,
    build_public_company_hall,
    write_public_company_hall,
)


def test_build_company_hall_has_six_departments_and_presence_model(monkeypatch):
    monkeypatch.setenv("MODSTORE_ACTION_ITEMS_KEEP_LOW_SIGNAL", "1")
    from sqlalchemy import text

    from modstore_server.digest_action_items import ensure_table, parse_and_store_action_items
    from modstore_server.models import get_engine

    ensure_table()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM daily_action_items"))

    parse_and_store_action_items(
        day="2026-07-22",
        record_id=9201,
        patches_markdown="""
## [task-router-officer] 任务派发员 · v1
- **P0** 修复公开公司大厅状态投影：工作中须来自真实行动条目
""",
        updates_markdown="",
        rt_version="1.0.0.0",
    )
    hall = build_public_company_hall(day="2026-07-22")
    assert hall["schema"] == "xcagi.public_company_hall/v1"
    assert len(hall["departments"]) == 6
    assert [d["id"] for d in hall["departments"]] == list(DEPARTMENT_ORDER)
    assert hall["counts"]["roster"] >= 40
    assert (
        hall["counts"]["working"] + hall["counts"]["alert"] + hall["counts"]["idle"]
        == hall["counts"]["roster"]
    )
    # at least the patch owner should be working or alert (P0)
    workers = [e for e in hall["employees"] if e["employee_id"] == "task-router-officer"]
    assert workers
    assert workers[0]["presence"] in {"working", "alert"}
    assert "presence_model" in hall
    assert isinstance(hall.get("feed"), list)
    assert hall.get("cadence", {}).get("mode") == "event_driven"
    assert "next_window" in (hall.get("cadence") or {})
    assert isinstance((hall.get("board") or {}).get("breakpoints"), list)
    assert isinstance((hall.get("board") or {}).get("goals"), list)
    assert "idle" in (hall.get("presence_model") or {})


def test_write_public_company_hall(tmp_path, monkeypatch):
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path))
    corp = tmp_path / "成都修茈科技有限公司"
    corp.mkdir(parents=True)
    out = write_public_company_hall(day=None)
    assert out["ok"] is True
    target = corp / "download-company-hall.json"
    assert target.is_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema"] == "xcagi.public_company_hall/v1"


def test_company_hall_feed_merges_sources_by_full_timestamp():
    feed = [
        {
            "employee_id": "action-owner",
            "source": "action_board",
            "day": "2026-07-21",
            "ts": "17:09",
            "occurred_at": "2026-07-21T17:09:27+00:00",
        },
        {
            "employee_id": "newest-metric",
            "source": "execution_metric",
            "day": "2026-07-22",
            "ts": "03:20",
            "occurred_at": "2026-07-22T03:20:00+00:00",
        },
        {
            "employee_id": "middle-metric",
            "source": "execution_metric",
            "day": "2026-07-21",
            "ts": "22:07",
            "occurred_at": "2026-07-21T22:07:00+00:00",
        },
    ]

    ordered = _sort_feed(feed)

    assert [item["employee_id"] for item in ordered] == [
        "newest-metric",
        "middle-metric",
        "action-owner",
    ]


def test_publicize_feed_text_strips_role_prompt_and_keeps_task():
    summary, detail = _publicize_feed_text(
        "你是事故处理小组的 scout。事件类型：ops.intake.email。"
        "问题摘要：官网邮件接入超时需人工复核。"
        "执行模式：execute；风险级别：low。必须使用真实日志核对。"
    )
    assert "你是" not in summary
    assert "执行模式" not in summary
    assert "官网邮件接入超时" in summary
    assert "官网邮件接入超时" in detail
    assert len(summary) <= len(detail)


def test_publicize_feed_text_prefers_gangwei_task_field():
    summary, detail = _publicize_feed_text(
        "岗位任务：汇总伙伴交付、验收和 SLA 状态。"
        "执行模式：execute；风险级别：low。"
        "验收回执：状态关联真实交付回执；延期明确责任与下一步。必须使用真实数据。"
    )
    assert summary.startswith("汇总伙伴交付")
    assert "执行模式" not in summary
    assert "汇总伙伴交付" in detail


def test_publicize_feed_text_hides_scout_instruction_prompt():
    summary, detail = _publicize_feed_text(
        "你是事故处理小组的 scout。事件类型：ops.incident.email。"
        "问题摘要：ops.incident.email。 回复必须说人话：先给结论/状态，再说下一步。"
    )
    assert "你是" not in summary
    assert "回复必须说人话" not in summary
    assert "scout" not in summary.lower()
    assert "ops.incident.email" in summary
    assert "事故巡检" in summary
    assert "你是" not in detail
    assert "回复必须说人话" not in detail


def test_publicize_feed_text_hides_json_dump_instruction():
    summary, detail = _publicize_feed_text(
        "不要直接倾倒 JSON、内部字段或英文模板。你的任务是判断最可能的原因、影响范围与下一步。"
    )
    assert "不要直接倾倒" not in summary
    assert "你的任务是" not in summary
    assert "JSON" not in summary
    assert "提示词已隐藏" in summary or "事故巡检" in summary
    assert "不要直接倾倒" not in detail
