"""每日 IM 主动工作汇报：文案构建 + 推送开关。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from modstore_server.models import (
    EmployeeExecutionMetric,
    IncidentEvent,
    PendingBriefTask,
    PendingHumanQuestion,
    get_session_factory,
    init_db,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield


def _seed_ledger() -> None:
    sf = get_session_factory()
    with sf() as session:
        session.add(
            EmployeeExecutionMetric(
                user_id=1,
                employee_id="emp-busy",
                task="t",
                status="success",
                duration_ms=10,
            )
        )
        session.add(
            EmployeeExecutionMetric(
                user_id=1,
                employee_id="emp-busy",
                task="t2",
                status="failed",
                duration_ms=10,
            )
        )
        session.add(
            PendingBriefTask(
                owner_employee_id="emp-busy",
                source_kind="boss_im",
                task_brief="盘点库存",
                fingerprint="daily-report-t1",
                status="done",
            )
        )
        session.add(
            PendingHumanQuestion(
                user_id=1,
                employee_id="emp-busy",
                task="t",
                question="要不要先发版？",
                fingerprint="daily-report-q1",
            )
        )
        session.commit()


def test_build_report_reflects_ledger():
    """种账本后：统计里数字到位，文案里关键段落到齐（DB 可能有其它用例的残留行，只断言下限）。"""
    from modstore_server.boss_daily_im_report import (
        _collect_stats,
        build_boss_daily_im_report,
    )

    _seed_ledger()
    stats = _collect_stats()
    assert stats["runs_total"] >= 2
    assert stats["runs_success"] >= 1
    assert stats["tasks_done"] >= 1
    assert stats["boss_im_done"] >= 1
    assert stats["questions_pending"] >= 1
    assert any(eid == "emp-busy" for eid, _ in stats["top_employees"])

    text = build_boss_daily_im_report()
    assert "员工团队日报" in text
    assert "emp-busy" in text
    assert "个问题在等你回复" in text


def test_send_respects_disable_env(monkeypatch):
    from modstore_server.boss_daily_im_report import send_boss_daily_im_report

    monkeypatch.setenv("MODSTORE_BOSS_IM_REPORT_ENABLED", "0")
    out = send_boss_daily_im_report()
    assert out == {"ok": True, "sent": False, "skipped_reason": "disabled"}


def test_send_pushes_via_bridge(monkeypatch):
    from modstore_server.boss_daily_im_report import send_boss_daily_im_report

    monkeypatch.delenv("MODSTORE_BOSS_IM_REPORT_ENABLED", raising=False)
    calls: List[Dict[str, Any]] = []

    def _fake_notify(employee_id: str, **kwargs: Any) -> bool:
        calls.append({"employee_id": employee_id, **kwargs})
        return True

    monkeypatch.setattr("modstore_server.employee_im_bridge.notify_boss", _fake_notify)
    out = send_boss_daily_im_report()
    assert out["ok"] is True and out["sent"] is True
    assert calls and calls[0]["hook"] == "daily_report"
    assert calls[0]["employee_id"] == "xc-digital-butler"
    assert "员工团队日报" in calls[0]["body"]


# --------------------------------------------------------------------------- #
# 感知→修复→验证 漏斗（45/55 失衡看板）
# --------------------------------------------------------------------------- #


def _seed_incident_with_followups(
    *,
    dispatched_count: int = 1,
    claim_ok: bool = False,
    follow_ups: list,
) -> int:
    """种一条 IncidentEvent 到 DB，payload_json 含 _team_claim.follow_ups。返回 event_id。"""
    sf = get_session_factory()
    with sf() as session:
        ev = IncidentEvent(
            event_type="on_error",
            source="unit",
            payload_json=json.dumps(
                {
                    "summary": "test",
                    "_team_claim": {
                        "ok": claim_ok,
                        "follow_ups": follow_ups,
                    },
                },
                ensure_ascii=False,
            ),
            dispatched_count=dispatched_count,
        )
        session.add(ev)
        session.commit()
        session.refresh(ev)
        return int(ev.id)


def test_funnel_collects_perceive_dispatch_handler_failed_recovered():
    """漏斗四个核心计数正确：感知 / 已 dispatch / handler_failed / 已恢复。"""
    from modstore_server.boss_daily_im_report import _collect_stats

    # 3 个 incident：
    #  - 已 dispatch，claim.ok=True（已恢复）
    #  - 已 dispatch，handler_failed with follow_ups（未恢复）
    #  - 未 dispatch
    _seed_incident_with_followups(dispatched_count=1, claim_ok=True, follow_ups=[])
    _seed_incident_with_followups(
        dispatched_count=1,
        claim_ok=False,
        follow_ups=[
            {
                "role": "fix",
                "failure_kind": "transient",
                "action": "transient_retry",
                "ok": False,
            }
        ],
    )
    _seed_incident_with_followups(dispatched_count=0, claim_ok=False, follow_ups=[])

    stats = _collect_stats(hours=24)
    assert stats["funnel_incidents_perceived"] >= 3
    assert stats["funnel_incidents_dispatched"] >= 2
    assert stats["funnel_incidents_handler_failed"] >= 1
    assert stats["funnel_incidents_recovered_ok"] >= 1


def test_funnel_classifies_followups_by_failure_kind():
    """漏斗 follow_ups 按 failure_kind 分类：quota/transient/prompt 三种分流计数正确。"""
    from modstore_server.boss_daily_im_report import _collect_stats

    _seed_incident_with_followups(
        dispatched_count=1,
        follow_ups=[
            {"role": "fix", "action": "quota_blocked_need_human", "ok": False},
            {"role": "verify", "action": "transient_retry", "ok": True},
            {"role": "scout", "action": "fallback_task_market", "ok": True},
        ],
    )

    stats = _collect_stats(hours=24)
    assert stats["funnel_followups_quota_blocked"] >= 1
    assert stats["funnel_followups_transient_retry"] >= 1
    assert stats["funnel_followups_prompt_market"] >= 1


def test_funnel_renders_failure_rate_in_report():
    """日报文案渲染「事故漏斗」行，含感知/dispatch/handler_failed/失败率/已恢复。"""
    from modstore_server.boss_daily_im_report import build_boss_daily_im_report

    # 制造 5 dispatch / 4 handler_failed → 失败率 80%
    _seed_incident_with_followups(
        dispatched_count=1,
        claim_ok=True,
        follow_ups=[],
    )
    for _ in range(4):
        _seed_incident_with_followups(
            dispatched_count=1,
            claim_ok=False,
            follow_ups=[{"role": "fix", "action": "transient_retry", "ok": False}],
        )

    text = build_boss_daily_im_report()
    assert "事故漏斗" in text
    assert "感知" in text
    assert "已 dispatch" in text
    assert "handler_failed" in text
    assert "失败率" in text
    assert "已恢复" in text
    # 自动分流明细行（存在 transient_retry 时显示）
    assert "自动分流" in text
    assert "瞬时重试" in text


def test_funnel_skipped_when_no_incidents(monkeypatch, tmp_path):
    """没有 incident 时不输出漏斗行（避免噪音）。

    用独立 tmp_path DB 隔离其他测试残留。
    """
    import modstore_server.models as _models

    _models._engine = None
    _models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "empty.sqlite"))
    _models.init_db()
    try:
        from modstore_server.boss_daily_im_report import build_boss_daily_im_report

        text = build_boss_daily_im_report()
        assert "事故漏斗" not in text
    finally:
        _models._engine = None
        _models._SessionFactory = None
