"""老板 IM 消息入站闭环：答问题 / 转新任务 + ACK / 执行回音 / 报告 hook 抑制。"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from modstore_server.models import (
    PendingBriefTask,
    PendingHumanQuestion,
    User,
    get_session_factory,
    init_db,
)


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "unit-test-internal-key")
    init_db()
    yield


@pytest.fixture
def notify_calls(monkeypatch) -> List[Dict[str, Any]]:
    """替身 employee_im_bridge.notify_boss，记录每次调用。"""
    calls: List[Dict[str, Any]] = []

    def _fake_notify(employee_id: str, **kwargs: Any) -> bool:
        calls.append({"employee_id": employee_id, **kwargs})
        return True

    monkeypatch.setattr("modstore_server.employee_im_bridge.notify_boss", _fake_notify)
    return calls


def _seed_pending_question(user_id: int, employee_id: str, question: str = "先做哪个？") -> int:
    sf = get_session_factory()
    with sf() as session:
        if session.get(User, user_id) is None:
            session.add(
                User(
                    id=user_id,
                    username=f"boss-{user_id}",
                    email=f"boss-{user_id}@pytest.local",
                    password_hash="x",
                )
            )
            session.flush()
        row = PendingHumanQuestion(
            user_id=user_id,
            employee_id=employee_id,
            task="unit",
            question=question,
            fingerprint=f"utq-{user_id}-{employee_id}-{question}",
        )
        session.add(row)
        session.commit()
        return int(row.id)


def _boss_im_tasks(employee_id: str) -> List[PendingBriefTask]:
    sf = get_session_factory()
    with sf() as session:
        return (
            session.query(PendingBriefTask)
            .filter(
                PendingBriefTask.source_kind == "boss_im",
                PendingBriefTask.owner_employee_id == employee_id,
            )
            .all()
        )


def test_boss_message_answers_pending_question(notify_calls):
    from modstore_server.boss_im_inbound import handle_boss_im_message

    qid = _seed_pending_question(7, "emp-answer-path")
    out = handle_boss_im_message(user_id=7, employee_id="emp-answer-path", text="先做 A")
    assert out["ok"] and out["mode"] == "question_answered"
    assert int(out["question_id"]) == qid
    # 是答案不是新指令：不建任务、不发 ACK
    assert not _boss_im_tasks("emp-answer-path")
    assert not notify_calls

    sf = get_session_factory()
    with sf() as session:
        row = session.get(PendingHumanQuestion, qid)
        assert row.status == "answered" and row.answer == "先做 A"


def test_boss_message_without_pending_becomes_task_with_ack(notify_calls):
    from modstore_server.boss_im_inbound import handle_boss_im_message

    out = handle_boss_im_message(user_id=9, employee_id="emp-task-path", text="帮我盘点一下库存")
    assert out["ok"] and out["mode"] == "task_enqueued"
    tasks = _boss_im_tasks("emp-task-path")
    assert len(tasks) == 1
    assert tasks[0].task_brief == "帮我盘点一下库存"
    assert tasks[0].status == "pending"

    assert out["ack_sent"] is True
    assert len(notify_calls) == 1
    ack = notify_calls[0]
    assert ack["hook"] == "ack"
    assert ack["boss_user_id"] == 9
    assert ack["owner_user_id"] == 9
    assert "收到" in ack["body"]


def test_same_text_twice_creates_two_tasks(notify_calls):
    """聊天指令允许重复文本（区别于 daily_brief 永久去重指纹）。"""
    from modstore_server.boss_im_inbound import handle_boss_im_message

    for _ in range(2):
        out = handle_boss_im_message(user_id=9, employee_id="emp-dup", text="继续")
        assert out["ok"] and out["mode"] == "task_enqueued"
    assert len(_boss_im_tasks("emp-dup")) == 2


def test_dispatch_boss_im_task_executes_and_replies(monkeypatch, notify_calls):
    from modstore_server.boss_im_inbound import dispatch_boss_im_task, enqueue_boss_im_task

    seen_exec: Dict[str, Any] = {}

    def _fake_execute(employee_id, task, input_data, user_id, **kwargs):
        seen_exec.update(
            {"employee_id": employee_id, "task": task, "input": input_data, "user_id": user_id}
        )
        return {
            "employee_id": employee_id,
            "result": {"outputs": [{"handler": "echo", "output": "库存盘点完成：共 42 件"}]},
            "reasoning_excerpt": "",
        }

    monkeypatch.setattr("modstore_server.employee_executor.execute_employee_task", _fake_execute)

    enq = enqueue_boss_im_task(boss_user_id=11, employee_id="emp-exec", text="盘点库存")
    out = dispatch_boss_im_task(int(enq["task_id"]), actor_user_id=3)
    assert out["ok"] is True
    assert out["replied_via_im"] is True
    assert "42 件" in out["reply"]

    # 直达点名员工执行 + 抑制执行器内部 report hook（由本路径发唯一回复）
    assert seen_exec["employee_id"] == "emp-exec"
    assert seen_exec["input"]["im_reply_managed"] is True
    assert seen_exec["input"]["boss_user_id"] == 11

    reply = notify_calls[-1]
    assert reply["hook"] == "reply"
    assert reply["boss_user_id"] == 11
    assert "42 件" in reply["body"]

    sf = get_session_factory()
    with sf() as session:
        row = session.get(PendingBriefTask, int(enq["task_id"]))
        assert row.status == "done"


def test_dispatch_boss_im_task_failure_still_replies(monkeypatch, notify_calls):
    from modstore_server.boss_im_inbound import dispatch_boss_im_task, enqueue_boss_im_task

    def _boom(*args, **kwargs):
        raise RuntimeError("LLM 配额用尽")

    monkeypatch.setattr("modstore_server.employee_executor.execute_employee_task", _boom)

    enq = enqueue_boss_im_task(boss_user_id=12, employee_id="emp-fail", text="做个报表")
    out = dispatch_boss_im_task(int(enq["task_id"]))
    assert out["ok"] is False
    # 失败也有回音，不静默
    reply = notify_calls[-1]
    assert reply["hook"] == "reply"
    assert "失败" in reply["body"]

    sf = get_session_factory()
    with sf() as session:
        row = session.get(PendingBriefTask, int(enq["task_id"]))
        assert row.status == "failed"
        assert "配额" in row.error


def test_dispatch_loop_routes_boss_im_directly(monkeypatch, notify_calls):
    """dispatch_pending_brief_tasks 对 boss_im 行走直达路径，不走 task_router 再路由。"""
    from modstore_server.boss_im_inbound import enqueue_boss_im_task
    from modstore_server.employee_autonomy_service import dispatch_pending_brief_tasks

    routed: List[str] = []

    def _fake_route(task_brief, **kwargs):
        routed.append(task_brief)
        return {"ok": True, "results": []}

    def _fake_boss_dispatch(task_id, actor_user_id=0):
        sf = get_session_factory()
        with sf() as session:
            row = session.get(PendingBriefTask, int(task_id))
            row.status = "done"
            session.commit()
        return {"ok": True, "task_id": task_id}

    monkeypatch.setattr("modstore_server.task_router.route_and_dispatch", _fake_route)
    monkeypatch.setattr(
        "modstore_server.boss_im_inbound.dispatch_boss_im_task", _fake_boss_dispatch
    )

    enq = enqueue_boss_im_task(boss_user_id=13, employee_id="emp-loop", text="修复导出乱码")
    out = dispatch_pending_brief_tasks(limit=10)
    assert out["ok"] is True
    assert not routed, "boss_im 任务不应流入 task_router"

    sf = get_session_factory()
    with sf() as session:
        row = session.get(PendingBriefTask, int(enq["task_id"]))
        assert row.status == "done"


def test_internal_answer_latest_endpoint_enqueues_task(client, notify_calls):
    res = client.post(
        "/api/admin/employee-autonomy/internal/answer-latest",
        headers={"X-Internal-Api-Key": "unit-test-internal-key"},
        json={"user_id": 21, "employee_id": "emp-endpoint", "answer": "把周报整理出来"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["mode"] == "task_enqueued"
    assert _boss_im_tasks("emp-endpoint")


def test_internal_answer_latest_endpoint_still_answers_questions(client, notify_calls):
    qid = _seed_pending_question(22, "emp-endpoint-q")
    res = client.post(
        "/api/admin/employee-autonomy/internal/answer-latest",
        headers={"X-Internal-Api-Key": "unit-test-internal-key"},
        json={"user_id": 22, "employee_id": "emp-endpoint-q", "answer": "按方案 B"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["mode"] == "question_answered"
    assert int(body["question_id"]) == qid


def test_report_hook_suppressed_for_managed_im_reply(notify_calls):
    """im_reply_managed 输入标记抑制 _actions_real 的 report hook，避免老板收到双份回复。"""
    from modstore_server.employee_executor import _actions_real

    _actions_real({}, {"reasoning": "干完了", "input": {"im_reply_managed": True}}, "t", "emp-a", 1)
    assert not notify_calls

    _actions_real({}, {"reasoning": "干完了", "input": {}}, "t", "emp-a", 1)
    assert len(notify_calls) == 1
    assert notify_calls[0]["hook"] == "report"
