"""Real-persistence tests for ``app.application.workflow.approval_persistence``.

These tests prove the durable workflow snapshot guards against a **real** SQLite
database (in-memory, bound to the actual ORM ``Base``). They do **not** mock
``load_durable_workflow_snapshot`` / ``mark_durable_request_approved_and_load``;
they exercise the real loader against genuinely persisted ``approval_requests``
rows, so the tenant / plan_id / params / terminal / replay guards are verified
end-to-end.

Covered per the review:
- Snapshot tenant guard: valid current tenant + valid snapshot tenant equality;
  snapshot tenant ``null`` / invalid / mismatch → fail-closed.
- Restored ``plan_id`` equality and exact ``dict`` params.
- ``mark_durable_request_approved_and_load``: pending → approved (no ``NameError``
  from ``datetime``), terminal status → fail-closed.
- ``mark_durable_outcome``: success → ``approved``; failure → ``cancelled``,
  bounded ``workflow_execution_failed`` code, no raw exception leak.
- Terminal / no-replay semantics for both statuses.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.workflow.approval_persistence import (
    SNAPSHOT_KEY,
    WORKFLOW_EXECUTION_FAILED_CODE,
    WORKFLOW_EXECUTION_SUCCESS_CODE,
    load_durable_workflow_snapshot,
    mark_durable_outcome,
    mark_durable_request_approved_and_load,
)
from app.db.base import Base
from app.db.models.approval import ApprovalRequest, ApprovalStatus

SNAPSHOT_VERSION = 1


def _valid_business_data(tenant_id=1, plan_id="plan-1", params=None):
    params = dict(params or {"unit_name": "Acme"})
    return {
        "plan_id": plan_id,
        "node_id": "write_customer",
        "tool_id": "business_db",
        "action": "write",
        "params": params,
        SNAPSHOT_KEY: {
            "version": SNAPSHOT_VERSION,
            "plan_id": plan_id,
            "tenant_id": tenant_id,
            "node": {
                "node_id": "write_customer",
                "tool_id": "business_db",
                "action": "write",
                "params": params,
            },
            "plan": {
                "plan_id": plan_id,
                "intent": "business_db_write",
                "todo_steps": [],
                "risk_level": "low",
                "metadata": {},
                "nodes": [
                    {
                        "node_id": "write_customer",
                        "tool_id": "business_db",
                        "action": "write",
                        "params": params,
                        "risk": "low",
                        "idempotent": False,
                        "description": "",
                        "depends_on": [],
                        "next": None,
                        "branches": [],
                    }
                ],
            },
            "runtime_context": {"message": "write customer"},
            "agent_run_id": "",
            "approved_step_id": "",
        },
    }


@pytest.fixture
def db():
    """Real in-memory SQLAlchemy session isolated through ``SessionLocal``.

    Patching the context-manager symbol itself can be captured by another module's
    ``from app.db.session import get_db`` while this fixture is active and leak the
    disposed in-memory database into later tests.  ``get_db`` resolves
    ``SessionLocal`` at call time, so replacing only that factory preserves the
    production session boundary without leaving an imported stale alias behind.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with patch("app.db.session.SessionLocal", TestingSession):
        yield TestingSession


def _insert_request(
    db,
    *,
    request_no,
    business_data,
    status=ApprovalStatus.PENDING.value,
    business_type="workflow_tool",
):
    row = ApprovalRequest(
        request_no=request_no,
        flow_id=1,
        business_type=business_type,
        business_data=json.dumps(business_data, ensure_ascii=False),
        applicant_id=1,
        applicant_name="tester",
        title="AI 工作流写库",
        status=status,
        priority="normal",
    )
    session = db()
    try:
        session.add(row)
        session.commit()
        return row.id
    finally:
        session.close()


def _read_status(db, request_no):
    session = db()
    try:
        return (
            session.query(ApprovalRequest).filter(ApprovalRequest.request_no == request_no).first()
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# load_durable_workflow_snapshot — tenant guard / plan_id / params
# ---------------------------------------------------------------------------


class TestLoaderTenantGuard:
    def test_matching_tenant_returns_snapshot(self, db):
        _insert_request(db, request_no="req-ok", business_data=_valid_business_data(tenant_id=1))
        snapshot = load_durable_workflow_snapshot("req-ok", allow_terminal=False)
        assert snapshot is not None
        assert snapshot["plan_id"] == "plan-1"

    def test_null_snapshot_tenant_fail_closed(self, db):
        data = _valid_business_data(tenant_id=None)
        _insert_request(db, request_no="req-null", business_data=data)
        assert load_durable_workflow_snapshot("req-null", allow_terminal=False) is None

    def test_non_numeric_snapshot_tenant_fail_closed(self, db):
        data = _valid_business_data(tenant_id="not-a-number")
        _insert_request(db, request_no="req-bad", business_data=data)
        assert load_durable_workflow_snapshot("req-bad", allow_terminal=False) is None

    def test_tenant_mismatch_fail_closed(self, db):
        # Snapshot tenant 2, current tenant 1 (default test scope) → must fail.
        data = _valid_business_data(tenant_id=2)
        _insert_request(db, request_no="req-mismatch", business_data=data)
        assert load_durable_workflow_snapshot("req-mismatch", allow_terminal=False) is None


class TestLoaderPlanIdAndParams:
    def test_plan_id_mismatch_fail_closed(self, db):
        data = _valid_business_data(plan_id="plan-1")
        # Top-level business_data plan_id differs from snapshot plan_id.
        data["plan_id"] = "plan-evil"
        _insert_request(db, request_no="req-plan-mismatch", business_data=data)
        assert load_durable_workflow_snapshot("req-plan-mismatch", allow_terminal=False) is None

    def test_restored_plan_plan_id_mismatch_fail_closed(self, db):
        data = _valid_business_data(plan_id="plan-1")
        # Snapshot plan block plan_id differs from snapshot plan_id.
        data[SNAPSHOT_KEY]["plan"]["plan_id"] = "plan-other"
        _insert_request(db, request_no="req-restored-mismatch", business_data=data)
        assert load_durable_workflow_snapshot("req-restored-mismatch", allow_terminal=False) is None

    def test_legacy_single_node_derived_plan_id_remains_loadable(self, db):
        data = _valid_business_data(plan_id="plan-parent")
        data[SNAPSHOT_KEY]["plan"]["plan_id"] = "plan-parent:write_customer"
        _insert_request(db, request_no="req-legacy-derived", business_data=data)

        snapshot = load_durable_workflow_snapshot("req-legacy-derived", allow_terminal=False)

        assert snapshot is not None
        assert snapshot["plan"].plan_id == "plan-parent:write_customer"

    def test_legacy_derived_plan_id_rejects_multi_node_plan(self, db):
        data = _valid_business_data(plan_id="plan-parent")
        data[SNAPSHOT_KEY]["plan"]["plan_id"] = "plan-parent:write_customer"
        data[SNAPSHOT_KEY]["plan"]["nodes"].append(
            {
                **data[SNAPSHOT_KEY]["plan"]["nodes"][0],
                "node_id": "unexpected_second_node",
            }
        )
        _insert_request(db, request_no="req-legacy-multi", business_data=data)

        assert load_durable_workflow_snapshot("req-legacy-multi", allow_terminal=False) is None

    def test_non_dict_params_fail_closed(self, db):
        data = _valid_business_data()
        data["params"] = "not-a-dict"
        _insert_request(db, request_no="req-params-str", business_data=data)
        assert load_durable_workflow_snapshot("req-params-str", allow_terminal=False) is None

    def test_params_mismatch_between_biz_and_node_fail_closed(self, db):
        data = _valid_business_data(params={"unit_name": "Acme"})
        data[SNAPSHOT_KEY]["node"]["params"] = {"unit_name": "OtherCo"}
        _insert_request(db, request_no="req-node-params-mismatch", business_data=data)
        assert (
            load_durable_workflow_snapshot("req-node-params-mismatch", allow_terminal=False) is None
        )


class TestLoaderTerminalAndReplay:
    def test_pending_loadable_for_preapproval(self, db):
        _insert_request(db, request_no="req-pending", business_data=_valid_business_data())
        assert load_durable_workflow_snapshot("req-pending", allow_terminal=False) is not None

    def test_approved_loadable_for_execution_resume(self, db):
        _insert_request(
            db,
            request_no="req-approved",
            business_data=_valid_business_data(),
            status=ApprovalStatus.APPROVED.value,
        )
        assert load_durable_workflow_snapshot("req-approved", allow_terminal=True) is not None

    def test_terminal_status_rejected_for_preapproval(self, db):
        _insert_request(
            db,
            request_no="req-terminal",
            business_data=_valid_business_data(),
            status=ApprovalStatus.CANCELLED.value,
        )
        assert load_durable_workflow_snapshot("req-terminal", allow_terminal=False) is None

    def test_pending_rejected_for_execution_resume(self, db):
        _insert_request(db, request_no="req-pending2", business_data=_valid_business_data())
        assert load_durable_workflow_snapshot("req-pending2", allow_terminal=True) is None

    def test_replay_rejected_when_workflow_execution_present(self, db):
        data = _valid_business_data()
        data["workflow_execution"] = {"status": "approved", "success": True}
        _insert_request(db, request_no="req-replay", business_data=data)
        assert load_durable_workflow_snapshot("req-replay", allow_terminal=False) is None
        assert load_durable_workflow_snapshot("req-replay", allow_terminal=True) is None


# ---------------------------------------------------------------------------
# mark_durable_request_approved_and_load — pending → approved, no NameError
# ---------------------------------------------------------------------------


class TestMarkApprovedAndLoad:
    def test_pending_transitions_to_approved(self, db):
        _insert_request(db, request_no="req-mark", business_data=_valid_business_data())
        snapshot = mark_durable_request_approved_and_load("req-mark")
        assert snapshot is not None
        row = _read_status(db, "req-mark")
        assert row.status == ApprovalStatus.APPROVED.value
        assert row.approved_at is not None

    def test_terminal_status_fail_closed_no_change(self, db):
        _insert_request(
            db,
            request_no="req-mark-cancelled",
            business_data=_valid_business_data(),
            status=ApprovalStatus.CANCELLED.value,
        )
        assert mark_durable_request_approved_and_load("req-mark-cancelled") is None
        row = _read_status(db, "req-mark-cancelled")
        assert row.status == ApprovalStatus.CANCELLED.value

    def test_no_name_error_datetime_import(self, db):
        # Regression: the function must not raise NameError for datetime.
        _insert_request(db, request_no="req-mark-dt", business_data=_valid_business_data())
        assert mark_durable_request_approved_and_load("req-mark-dt") is not None


# ---------------------------------------------------------------------------
# mark_durable_outcome — approved / cancelled no-replay, bounded message
# ---------------------------------------------------------------------------


class TestMarkOutcome:
    def test_success_yields_approved(self, db):
        _insert_request(db, request_no="req-out-ok", business_data=_valid_business_data())
        mark_durable_outcome("req-out-ok", success=True)
        row = _read_status(db, "req-out-ok")
        assert row.status == ApprovalStatus.APPROVED.value
        exec_data = json.loads(row.business_data)["workflow_execution"]
        assert exec_data["status"] == ApprovalStatus.APPROVED.value
        assert exec_data["success"] is True
        assert exec_data["code"] == WORKFLOW_EXECUTION_SUCCESS_CODE

    def test_failure_yields_cancelled_with_bounded_code(self, db):
        _insert_request(db, request_no="req-out-fail", business_data=_valid_business_data())
        mark_durable_outcome("req-out-fail", success=False)
        row = _read_status(db, "req-out-fail")
        assert row.status == ApprovalStatus.CANCELLED.value
        assert row.rejection_reason == WORKFLOW_EXECUTION_FAILED_CODE
        exec_data = json.loads(row.business_data)["workflow_execution"]
        assert exec_data["status"] == ApprovalStatus.CANCELLED.value
        assert exec_data["success"] is False
        assert exec_data["code"] == WORKFLOW_EXECUTION_FAILED_CODE

    def test_message_is_bounded_and_truncated(self, db):
        # mark_durable_outcome bounds caller-supplied text (strip newlines, cap length).
        raw = "raw-secret-" + "x" * 500
        _insert_request(db, request_no="req-out-bounded", business_data=_valid_business_data())
        mark_durable_outcome("req-out-bounded", success=False, message=raw)
        row = _read_status(db, "req-out-bounded")
        exec_data = json.loads(row.business_data)["workflow_execution"]
        assert len(exec_data["message"]) <= 200
        assert "\n" not in exec_data["message"]

    def test_no_replay_after_outcome(self, db):
        _insert_request(db, request_no="req-out-replay", business_data=_valid_business_data())
        mark_durable_outcome("req-out-replay", success=True)
        # Terminal approved → not loadable for pre-approval or re-execution.
        assert load_durable_workflow_snapshot("req-out-replay", allow_terminal=False) is None
        assert load_durable_workflow_snapshot("req-out-replay", allow_terminal=True) is None


class TestResumePathNoRawLeakReal:
    """审批通过后恢复执行 → 纯执行不落库、不泄漏原始异常；终态由调用方统一写入。"""

    def test_failed_resume_persists_cancelled_and_bounded_message(self, db):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from app.application.approval_workspace_app_service import (
            _resume_pending_ai_workflow_after_approval,
        )

        _insert_request(db, request_no="req-resume-leak", business_data=_valid_business_data())
        plan = SimpleNamespace(plan_id="plan-1", intent="t", nodes=[object()])
        svc = MagicMock()
        svc.approve.return_value = True
        svc.get_pending_workflow.return_value = {"plan": plan, "runtime_context": {}}
        run_result = SimpleNamespace(
            success=False,
            message="boom-secret-raw-exception-xyz",
            node_results=[],
        )
        engine = MagicMock()
        engine.run.return_value = run_result
        with (
            patch("app.application.workflow.get_approval_service", return_value=svc),
            patch("app.application.workflow.WorkflowEngine", return_value=engine),
            patch("app.fastapi_routes.domains.misc.helpers._dispatch_tool_for_approval"),
        ):
            out = _resume_pending_ai_workflow_after_approval(
                request_no="req-resume-leak", opinion="同意"
            )

        # 纯执行契约：恢复器不落库、不写终态；终态由调用方在自身事务统一写入。
        assert out is not None
        assert out["success"] is False
        assert out["message"] == "AI 工作流执行失败"
        assert "boom-secret-raw-exception-xyz" not in str(out)
        row = _read_status(db, "req-resume-leak")
        assert row.status == ApprovalStatus.PENDING.value
        assert "workflow_execution" not in json.loads(row.business_data or "{}")


class TestAtomicTerminalStateNotOverwrittenByStaleSession:
    """真实 SQLite：审批终态在调用方单事务内原子落库，绝不被陈旧会话覆盖。

    恢复器只返回安全结果、不落库；终态（cancelled/approved + 有界 outcome + 审计）由
    ``_approve_ai_workflow_request_without_node`` 在调用方会话统一提交。用独立的新会话
    复读，证明 DB 中只有单一真实终态，且陈旧会话持有的 pending 视图不会把终态覆盖回去。
    """

    def _seed_pending(self, db, request_no, session):
        # _insert_request 用独立会话落库（pytest 会话工厂），随后在调用方会话内复读，
        # 使返回的 ``req`` 绑定到调用方事务，保证同事务原子提交。
        _insert_request(db, request_no=request_no, business_data=_valid_business_data())
        return (
            session.query(ApprovalRequest).filter(ApprovalRequest.request_no == request_no).first()
        )

    def _run_approve(self, session, req, resume_result):
        from types import SimpleNamespace
        from unittest.mock import patch

        from app.application.approval_workspace_app_service import (
            _approve_ai_workflow_request_without_node,
        )

        with (
            patch(
                "app.application.approval_workspace_app_service._can_review_ai_workflow_request",
                return_value=True,
            ),
            patch(
                "app.application.approval_workspace_app_service._has_pending_ai_workflow",
                return_value=True,
            ),
            patch(
                "app.application.approval_workspace_app_service._ai_workflow_audit_node",
                return_value=SimpleNamespace(id=1, node_name="AI 工作流审批留痕", node_order=1),
            ),
            patch(
                "app.application.approval_workspace_app_service._resume_pending_ai_workflow_after_approval",
                return_value=resume_result,
            ),
            patch("app.application.approval_workspace_app_service.notify_mobile_user"),
        ):
            return _approve_ai_workflow_request_without_node(
                session, req=req, actor=1, approver_name="admin", opinion="同意"
            )

    def test_failure_commits_cancelled_single_truthful_state(self, db):
        """失败 → 陈旧会话（pending 视图）提交后，新会话只读到 cancelled 终态，绝不回写 pending/approved。"""
        from app.application.workflow.approval_persistence import (
            load_durable_workflow_snapshot,
        )

        # 用会话 A 持有陈旧 pending 视图，作为调用方事务。
        session_a = db()
        try:
            req = self._seed_pending(db, "req-atomic-fail", session_a)
            stale_status_view = req.status
            assert stale_status_view == ApprovalStatus.PENDING.value
            result = self._run_approve(
                session_a,
                req,
                {
                    "workflow_executed": True,
                    "success": False,
                    "code": "raw-secret-code",
                    "message": "raw-secret-message",
                },
            )
            # 失败 → 409 安全响应，请求置为 cancelled 终态。
            assert result.status_code == 409
            assert json.loads(result.body)["success"] is False
            # 独立新会话复读：单一真实终态 = cancelled，且带安全 bound 的 workflow_execution。
            fresh = _read_status(db, "req-atomic-fail")
            assert fresh.status == ApprovalStatus.CANCELLED.value
            assert fresh.rejection_reason == WORKFLOW_EXECUTION_FAILED_CODE
            exec_data = json.loads(fresh.business_data)["workflow_execution"]
            assert exec_data["status"] == ApprovalStatus.CANCELLED.value
            assert exec_data["success"] is False
            assert exec_data["code"] == WORKFLOW_EXECUTION_FAILED_CODE
            assert "raw-secret" not in json.dumps(fresh.business_data, ensure_ascii=False)
            # 终态不被任何加载器接受（预审批仅 pending、执行恢复仅 approved）→ 无重放。
            assert load_durable_workflow_snapshot("req-atomic-fail", allow_terminal=False) is None
            assert load_durable_workflow_snapshot("req-atomic-fail", allow_terminal=True) is None
        finally:
            session_a.close()

    def test_success_commits_approved_single_truthful_state(self, db):
        """成功 → 新会话只读到 approved 终态，且不再被陈旧 pending 会话覆盖。"""
        from app.application.workflow.approval_persistence import (
            load_durable_workflow_snapshot,
        )

        session_a = db()
        try:
            req = self._seed_pending(db, "req-atomic-ok", session_a)
            result = self._run_approve(
                session_a,
                req,
                {"workflow_executed": True, "success": True, "code": "", "message": ""},
            )
            assert result["success"] is True
            fresh = _read_status(db, "req-atomic-ok")
            assert fresh.status == ApprovalStatus.APPROVED.value
            assert fresh.approved_at is not None
            exec_data = json.loads(fresh.business_data)["workflow_execution"]
            assert exec_data["status"] == ApprovalStatus.APPROVED.value
            assert exec_data["success"] is True
            assert exec_data["code"] == WORKFLOW_EXECUTION_SUCCESS_CODE
            # approved 是可执行获批态，但预审批加载器拒绝（避免重复审批重新进入）。
            assert load_durable_workflow_snapshot("req-atomic-ok", allow_terminal=False) is None
        finally:
            session_a.close()
