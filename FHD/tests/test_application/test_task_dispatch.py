"""派工调度域测试：路由 / 仓储 / 状态机 / 服务闭环。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.task_dispatch.repository import WorkOrderRepository
from app.application.task_dispatch.router import DispatchRouter, RoutingDecision
from app.application.task_dispatch.service import TaskDispatchService
from app.application.task_dispatch.status import WorkOrderStatus, can_transition


# ── fixtures ────────────────────────────────────────────────────────────
@pytest.fixture()
def repo(tmp_path) -> WorkOrderRepository:
    engine = create_engine(f"sqlite:///{tmp_path / 'work-orders.db'}")
    session_factory = sessionmaker(bind=engine)
    return WorkOrderRepository(session_factory=session_factory)


@pytest.fixture()
def router() -> DispatchRouter:
    return DispatchRouter(
        super_catalog=[
            {"id": "claude-super-employee", "name": "超级员工-Claude", "aliases": {"claude"}},
            {"id": "codex-super-employee", "name": "超级员工-Codex", "aliases": {"codex"}},
        ],
        platform_catalog=[
            {"id": "cs-officer", "name": "cs-officer", "aliases": {"cs-officer", "客服"}},
        ],
    )


# ── 状态机 ───────────────────────────────────────────────────────────────
def test_state_machine_allows_forward_only() -> None:
    assert can_transition("pending", "dispatched") is True
    assert can_transition("dispatched", "running") is True
    assert can_transition("running", "succeeded") is True
    # 不得从终态复活
    assert can_transition("succeeded", "running") is False
    assert can_transition("failed", "dispatched") is False
    assert can_transition("pending", "succeeded") is False


# ── 路由 ─────────────────────────────────────────────────────────────────
def test_router_no_cue_returns_none(router: DispatchRouter) -> None:
    assert router.route("claude 是什么意思") is None  # 有名无派工动词
    assert router.route("帮我查一下库存") is None  # 有动词无受派人


def test_router_nl_match_super(router: DispatchRouter) -> None:
    decision = router.route("让claude去修复登录bug")
    assert decision is not None
    assert decision.assignee_tier == "super"
    assert decision.assignee_id == "claude-super-employee"


def test_router_nl_match_platform(router: DispatchRouter) -> None:
    decision = router.route("把这个工单交给客服处理")
    assert decision is not None
    assert decision.assignee_tier == "platform"
    assert decision.assignee_id == "cs-officer"


def test_router_explicit_context_dispatch(router: DispatchRouter) -> None:
    decision = router.route(
        "随便一句话",
        context={"dispatch": {"assignee_id": "cs-officer", "tier": "platform"}},
    )
    assert decision is not None
    assert decision.assignee_id == "cs-officer"
    assert decision.reason == "explicit-dispatch-context"


# ── 仓储 ─────────────────────────────────────────────────────────────────
def test_repository_crud(repo: WorkOrderRepository) -> None:
    created = repo.create(
        work_order_id="wo1",
        requester_user_id="u1",
        assignee_tier="platform",
        assignee_id="cs-officer",
        assignee_name="cs-officer",
        title="处理工单",
        instruction="把这个工单交给客服处理",
        status=WorkOrderStatus.PENDING.value,
    )
    assert created["work_order_id"] == "wo1"
    assert created["status"] == "pending"

    repo.update("wo1", status=WorkOrderStatus.SUCCEEDED.value, result_summary="done")
    fetched = repo.get("wo1")
    assert fetched is not None
    assert fetched["status"] == "succeeded"
    assert fetched["result_summary"] == "done"

    recent = repo.list_recent(requester_user_id="u1")
    assert [r["work_order_id"] for r in recent] == ["wo1"]


# ── 服务闭环 ─────────────────────────────────────────────────────────────
def _service(
    repo: WorkOrderRepository, router: DispatchRouter, *, super_raw=None, platform_raw=None
):
    def super_factory(_assignee_id: str) -> Any:
        class _FakeSuper:
            def invoke(self, *, user_id, message, context):  # noqa: ARG002
                return super_raw

        return _FakeSuper()

    def platform_executor(employee_id, task, *, user_id=0):  # noqa: ARG001
        return platform_raw

    return TaskDispatchService(
        repository=repo,
        router=router,
        super_employee_factory=super_factory,
        platform_executor=platform_executor,
    )


def _run_sync(svc: TaskDispatchService, message: str, user_id: str = "7") -> dict:
    """同步派工：route → dispatch（入队即执行）。"""
    decision = svc.route(message)
    assert decision is not None
    return svc.dispatch(decision, message=message, requester_user_id=user_id)


def test_dispatch_super_completed_marks_succeeded(repo, router) -> None:
    raw = {
        "dispatch": {"status": "completed", "accepted": True, "request_id": "rq1"},
        "assistant_message": {"body": "登录bug已修复并提交。"},
    }
    svc = _service(repo, router, super_raw=raw)
    out = _run_sync(svc, "让claude去修复登录bug")
    assert out["status"] == WorkOrderStatus.SUCCEEDED.value
    assert "登录bug已修复" in out["result_summary"]
    wo = out["work_order"]
    assert wo["assignee_tier"] == "super"
    assert wo["request_id"] == "rq1"
    assert repo.get(wo["work_order_id"])["status"] == "succeeded"


def test_dispatch_super_queued_marks_running(repo, router) -> None:
    raw = {"dispatch": {"status": "queued", "accepted": True}}
    svc = _service(repo, router, super_raw=raw)
    out = _run_sync(svc, "让codex去跑全量测试")
    assert out["status"] == WorkOrderStatus.RUNNING.value
    assert out["ok"] is False  # running 非成功终态


def test_dispatch_platform_success(repo, router) -> None:
    raw = {
        "success": True,
        "result": {"outputs": [{"handler": "h", "ok": True, "output": "工单已处理完毕。"}]},
    }
    svc = _service(repo, router, platform_raw=raw)
    out = _run_sync(svc, "把这个工单交给客服处理")
    assert out["status"] == WorkOrderStatus.SUCCEEDED.value
    assert "工单已处理完毕" in out["result_summary"]


def test_dispatch_platform_blocked_marks_failed(repo, router) -> None:
    raw = {"success": False, "blocked_by_risk_gate": True, "result": {}}
    svc = _service(repo, router, platform_raw=raw)
    out = _run_sync(svc, "让客服去删库")
    assert out["status"] == WorkOrderStatus.FAILED.value


def test_dispatch_exception_becomes_failed_work_order(repo, router) -> None:
    def boom_executor(employee_id, task, *, user_id=0):  # noqa: ARG001
        raise RuntimeError("executor down")

    svc = TaskDispatchService(repository=repo, router=router, platform_executor=boom_executor)
    out = _run_sync(svc, "把工单交给客服处理")
    assert out["status"] == WorkOrderStatus.FAILED.value
    assert "executor down" in out["work_order"]["error"]


def test_no_dispatch_returns_none(repo, router) -> None:
    svc = _service(repo, router)
    assert svc.handle_chat_dispatch(user_id="7", message="今天天气怎么样") is None


# ── 异步入队 + worker ─────────────────────────────────────────────────────
def test_handle_chat_dispatch_enqueues_without_executing(repo, router) -> None:
    calls = {"n": 0}

    def executor(employee_id, task, *, user_id=0):  # noqa: ARG001
        calls["n"] += 1
        return {"success": True, "result": {"outputs": [{"output": "ok"}]}}

    svc = TaskDispatchService(repository=repo, router=router, platform_executor=executor)
    out = svc.handle_chat_dispatch(user_id="7", message="把这个工单交给客服处理")
    assert out["queued"] is True
    assert out["status"] == WorkOrderStatus.PENDING.value
    assert calls["n"] == 0  # 入队不执行
    assert repo.get(out["work_order"]["work_order_id"])["status"] == "pending"


def test_worker_drains_pending(repo, router) -> None:
    raw = {"success": True, "result": {"outputs": [{"output": "已处理"}]}}
    svc = _service(repo, router, platform_raw=raw)
    out = svc.handle_chat_dispatch(user_id="7", message="把这个工单交给客服处理")
    wo_id = out["work_order"]["work_order_id"]

    from app.application.task_dispatch.worker import WorkOrderWorker

    worker = WorkOrderWorker(service=svc)
    assert worker.drain_once() == 1
    assert repo.get(wo_id)["status"] == "succeeded"
    # 抽干后无待执行
    assert worker.drain_once() == 0


def test_execute_work_order_idempotent_on_terminal(repo, router) -> None:
    calls = {"n": 0}

    def executor(employee_id, task, *, user_id=0):  # noqa: ARG001
        calls["n"] += 1
        return {"success": True, "result": {"outputs": [{"output": "ok"}]}}

    svc = TaskDispatchService(repository=repo, router=router, platform_executor=executor)
    decision = svc.route("把这个工单交给客服处理")
    rec = svc.enqueue(decision, message="把这个工单交给客服处理", requester_user_id="7")
    wo_id = rec["work_order_id"]
    assert svc.execute_work_order(wo_id)["status"] == "succeeded"
    again = svc.execute_work_order(wo_id)
    assert again["status"] == "succeeded"
    assert calls["n"] == 1  # 终态不重复执行


def test_retry_succeeds_after_transient_error(repo, router) -> None:
    calls = {"n": 0}

    def flaky(employee_id, task, *, user_id=0):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"success": True, "result": {"outputs": [{"output": "ok after retry"}]}}

    svc = TaskDispatchService(repository=repo, router=router, platform_executor=flaky)
    out = _run_sync(svc, "把这个工单交给客服处理")
    assert out["status"] == "succeeded"
    assert calls["n"] == 2  # 重试一次后成功


# ── 结果回流 AI 交流圈 ────────────────────────────────────────────────────
def test_super_terminal_posts_to_circle(repo, router, monkeypatch) -> None:
    posts: list[tuple] = []
    monkeypatch.setattr(
        "app.application.ai_circle_service.record_employee_activity",
        lambda emp, **kw: posts.append((emp, kw)),
    )
    raw = {
        "dispatch": {"status": "completed", "accepted": True},
        "assistant_message": {"body": "done"},
    }
    svc = _service(repo, router, super_raw=raw)
    _run_sync(svc, "让claude去修复登录bug")
    assert len(posts) == 1
    assert posts[0][1]["success"] is True


def test_platform_skips_circle_to_avoid_duplicate(repo, router, monkeypatch) -> None:
    posts: list[str] = []
    monkeypatch.setattr(
        "app.application.ai_circle_service.record_employee_activity",
        lambda emp, **kw: posts.append(emp),
    )
    raw = {"success": True, "result": {"outputs": [{"output": "ok"}]}}
    svc = _service(repo, router, platform_raw=raw)
    _run_sync(svc, "把这个工单交给客服处理")
    assert posts == []  # tier-3 由 EmployeeAgent 自身发帖，派工层不重复


# ── 第三个超级员工 Cursor + 会话隔离 ──────────────────────────────────────
def test_super_factory_maps_cursor() -> None:
    from app.application.cursor_super_employee_service import CursorSuperEmployeeService
    from app.application.task_dispatch.service import _default_super_factory

    assert isinstance(_default_super_factory("cursor-super-employee"), CursorSuperEmployeeService)


def test_real_router_routes_to_cursor() -> None:
    """真实 SSOT 目录(已含 cursor) → NL 路由能命中 cursor。"""
    from app.application.task_dispatch.router import DispatchRouter

    decision = DispatchRouter().route("让cursor去修复登录bug")
    assert decision is not None
    assert decision.assignee_id == "cursor-super-employee"
    assert decision.assignee_tier == "super"


def test_dispatch_super_passes_conversation_id_for_isolation(repo, router) -> None:
    captured: dict = {}

    def super_factory(_assignee_id: str):
        class _FakeSuper:
            def invoke(self, *, user_id, message, context):  # noqa: ARG002
                captured.update(context)
                return {"dispatch": {"status": "completed", "accepted": True}}

        return _FakeSuper()

    svc = TaskDispatchService(repository=repo, router=router, super_employee_factory=super_factory)
    out = _run_sync(svc, "让claude去修复登录bug")
    # 每工单一独立会话键 → conversation_id == work_order_id
    assert captured["conversation_id"] == out["work_order"]["work_order_id"]


# ── 聊天主链路接线 ───────────────────────────────────────────────────────
def test_chat_service_dispatch_branch_returns_response(monkeypatch) -> None:
    """小C 活入口 _try_handle_task_dispatch 命中派工时返回标准对话响应。"""
    import app.application.task_dispatch as td
    from app.application.ai_chat_app_service import AIChatApplicationService

    class _FakeDispatch:
        def handle_chat_dispatch(self, *, user_id, message, context=None):  # noqa: ARG002
            return {
                "work_order": {
                    "work_order_id": "wo-x",
                    "assignee_tier": "super",
                    "assignee_name": "超级员工-Claude",
                },
                "status": td.WorkOrderStatus.SUCCEEDED.value,
                "ok": True,
                "result_summary": "登录bug已修复并提交。",
            }

    monkeypatch.setattr(td, "get_task_dispatch_service", lambda: _FakeDispatch())

    svc = AIChatApplicationService()
    resp = svc._try_handle_task_dispatch(
        user_id="7", message="让claude去修复登录bug", source=None, context={}
    )
    assert resp is not None
    assert resp["success"] is True
    assert resp["data"]["action"] == "task_dispatch"
    assert "超级员工-Claude" in resp["response"]
    assert "登录bug已修复" in resp["response"]
    assert resp["data"]["data"]["work_order"]["work_order_id"] == "wo-x"


def test_chat_service_dispatch_branch_passes_through_when_no_dispatch(monkeypatch) -> None:
    import app.application.task_dispatch as td
    from app.application.ai_chat_app_service import AIChatApplicationService

    class _FakeDispatch:
        def handle_chat_dispatch(self, *, user_id, message, context=None):  # noqa: ARG002
            return None

    monkeypatch.setattr(td, "get_task_dispatch_service", lambda: _FakeDispatch())

    svc = AIChatApplicationService()
    resp = svc._try_handle_task_dispatch(
        user_id="7", message="今天天气怎么样", source=None, context={}
    )
    assert resp is None


def test_chat_service_dispatch_branch_renders_queued(monkeypatch) -> None:
    """异步入队的受理回执渲染为「正在后台执行」。"""
    import app.application.task_dispatch as td
    from app.application.ai_chat_app_service import AIChatApplicationService

    class _FakeDispatch:
        def handle_chat_dispatch(self, *, user_id, message, context=None):  # noqa: ARG002
            return {
                "work_order": {
                    "work_order_id": "wo-q",
                    "assignee_tier": "platform",
                    "assignee_name": "cs-officer",
                },
                "status": td.WorkOrderStatus.PENDING.value,
                "queued": True,
                "ok": False,
                "result_summary": "已派工给「cs-officer」，正在后台执行。",
            }

    monkeypatch.setattr(td, "get_task_dispatch_service", lambda: _FakeDispatch())

    svc = AIChatApplicationService()
    resp = svc._try_handle_task_dispatch(
        user_id="7", message="把工单交给客服处理", source=None, context={}
    )
    assert resp is not None
    assert "正在后台执行" in resp["response"]
    assert resp["data"]["data"]["status"] == td.WorkOrderStatus.PENDING.value
