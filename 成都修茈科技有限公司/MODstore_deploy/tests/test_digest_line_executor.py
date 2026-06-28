"""Tests for digest_line_executor (Phase A)."""

from __future__ import annotations

import json

import modstore_server.models as models
from modstore_server.digest_line_executor import execute_digest_line_work_units
from modstore_server.models import (
    DailyDigestRecord,
    EmployeeCollabMessage,
    EmployeeCollabThread,
    get_session_factory,
)


def _seed_digest(ps_md: str, base_version: str = "2026-06-03#main#abc#r1") -> int:
    models.init_db()
    sf = get_session_factory()
    with sf() as session:
        row = DailyDigestRecord(
            day="2026-06-03",
            subject="test digest",
            body_text="body",
            vibe_prep_ps_md=ps_md,
            vibe_prep_meta_json=f'{{"ok": true, "base_version": "{base_version}"}}',
        )
        session.add(row)
        session.flush()
        rid = int(row.id)
        session.commit()
        return rid


def _seed_fallback_digest(ps_md: str) -> int:
    models.init_db()
    sf = get_session_factory()
    with sf() as session:
        row = DailyDigestRecord(
            day="2026-06-28",
            subject="fallback digest",
            body_text="body",
            vibe_prep_ps_md=ps_md,
            vibe_prep_meta_json=json.dumps(
                {
                    "ok": True,
                    "base_version": "2026-06-28#main#abc#r1",
                    "fallback_reason": "LLM 未返回有效 JSON",
                },
                ensure_ascii=False,
            ),
        )
        session.add(row)
        session.flush()
        rid = int(row.id)
        session.commit()
        return rid


def _seed_actions_report_message(employee_id: str, day: str = "2026-06-28") -> None:
    sf = get_session_factory()
    with sf() as session:
        thread = EmployeeCollabThread(
            title="[员工交流圈] P-S · dept=prod_software",
            participants_json=json.dumps([employee_id], ensure_ascii=False),
            context_json="{}",
            created_by_employee_id="collab-reporter",
        )
        session.add(thread)
        session.flush()
        session.add(
            EmployeeCollabMessage(
                thread_id=int(thread.id),
                sender_employee_id=employee_id,
                content="fallback actions",
                payload_json=json.dumps(
                    {
                        "report_key": f"actions|{day}|{employee_id}",
                        "source": "action_items",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()


def test_execute_ps_patches_dispatches(monkeypatch):
    ps = (
        "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n"
        "## [fhd-core-maintainer] 核心\n\n"
        "- **P0** 修 pytest\n"
    )
    rid = _seed_digest(ps)
    calls = []

    def fake_dispatch(subtasks, **kwargs):
        calls.append({"n": len(subtasks), "kwargs": kwargs})
        return {"ok": True, "results": [{"employee_id": "fhd-core-maintainer", "ok": True}]}

    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1")
    monkeypatch.setattr(
        "modstore_server.employee_orchestrator.dispatch_subtasks",
        fake_dispatch,
    )

    out = execute_digest_line_work_units(rid, dispatch_line="P-S", mode="test")
    assert out["ok"] is True
    assert out["unit_count"] == 1
    assert calls and calls[0]["n"] == 1

    out2 = execute_digest_line_work_units(rid, dispatch_line="P-S", mode="test")
    assert out2.get("skipped") is True


def test_execute_skips_when_no_units(monkeypatch):
    ps = "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n" "## [fhd-core-maintainer] 核心\n\n"
    rid = _seed_digest(ps)
    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1")
    out = execute_digest_line_work_units(rid, force=True)
    assert out["ok"] is True
    assert out.get("reason") == "no matching work units"


def test_execute_fallback_breakpoint_units_complete_locally(monkeypatch):
    ps = (
        "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n"
        "## [modstore-backend-api] MODstore 后端 API 员\n\n"
        "- **P0** 修复 Vibe 预备任务生成断点：LLM 未返回有效 JSON（缺少 updates_markdown / patches_markdown）后必须产出可派发断点任务\n"
        "\n"
        "## [task-router-officer] 任务派发员\n\n"
        "- **P0** 修复 Vibe fallback 任务责任路由：LLM 合成失败时不能把所有断点挂给 daily-orchestrator，需按实际责任员工进入 action-items 和 AI 交流圈\n"
        "\n"
        "## [test-qa-runner] 测试质量运行员\n\n"
        "- **P1** 增加回归断言：template fallback 发生时必须进入 action-items、产线执行和 AI 交流圈，避免每日只有主持人消息\n"
    )
    rid = _seed_fallback_digest(ps)

    from modstore_server.digest_action_items import list_action_items, parse_and_store_action_items

    parse_and_store_action_items(
        day="2026-06-28",
        record_id=rid,
        patches_markdown=ps,
        rt_version="test",
    )
    _seed_actions_report_message("modstore-backend-api")
    _seed_actions_report_message("task-router-officer")
    _seed_actions_report_message("test-qa-runner")

    def fail_dispatch(*_args, **_kwargs):
        raise AssertionError("fallback breakpoint units must not call dispatch_subtasks")

    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1")
    monkeypatch.setattr(
        "modstore_server.employee_orchestrator.dispatch_subtasks",
        fail_dispatch,
    )

    out = execute_digest_line_work_units(rid, dispatch_line="P-S", mode="test", force=True)

    assert out["ok"] is True
    assert out["unit_count"] == 3
    assert out["dispatch"]["local_verified_count"] == 3
    assert out["dispatch"]["remote_dispatched_count"] == 0
    assert out["dispatch"]["results_count"] == 3
    assert all(r["ok"] for r in out["dispatch"]["local_results"])
    assert out["action_items_writeback"]["local_verified_merge"]["updated"] == 3

    items = list_action_items(day="2026-06-28", record_id=rid, limit=10)
    assert sorted(item["status"] for item in items) == ["merged", "merged", "merged"]
