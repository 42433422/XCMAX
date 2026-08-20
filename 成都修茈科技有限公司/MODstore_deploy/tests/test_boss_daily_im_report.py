"""每日 IM 主动工作汇报：文案构建 + 推送开关。"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from modstore_server.models import (
    EmployeeExecutionMetric,
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
