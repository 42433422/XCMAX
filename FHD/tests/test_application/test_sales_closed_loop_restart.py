"""正式持久业务图等待原审批；进程重启与会话撤回不能重写、重放或扩大目标。"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.db.db_base import Base
from app.db.models import (
    InventoryLedger,
    InventoryTransaction,
    JournalEntry,
    SalesOrder,
    SalesOrderItem,
)
from app.infrastructure.tenant_scope import tenant_scope

SENTENCE = (
    "帮我给测试客户 A 销售 10 件产品 B，每件 100 元。先检查客户和库存，生成订单给我确认。"
    "批准后完成出库、发货和开票；收款必须依据实际到账凭证登记。最后核对订单、库存、发货、发票和收款，并导出结果。"
)


def _prepare(db_path: Path):
    import app.db.models.agent
    import app.db.models.approval
    import app.db.models.user

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import app.db as database
    import app.db.session as session_module

    database.HostSessionLocal = factory
    database.SessionLocal = factory
    session_module.SessionLocal = factory
    from app.domain.shared_services.ai_action_audit_service import ensure_ai_action_audit_table

    ensure_ai_action_audit_table()
    from app.application.agent_orchestrator.run_repository import (
        set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.run_sql_repository import (
        SQLAlchemyAgentRunRepository,
    )

    set_agent_run_repository_for_tests(SQLAlchemyAgentRunRepository(session_factory=factory))
    return factory


def _seed(factory, tenant_id: int = 1) -> int:
    from datetime import datetime

    from app.db.models import Customer, InventoryLedger, Product, Warehouse
    from app.db.models.user import User

    with tenant_scope(tenant_id):
        db = factory()
        customer = Customer(customer_name="测试客户 A")
        product = Product(name="产品 B", unit="件", model_number="TEST-B-001", is_active=1)
        warehouse = Warehouse(
            code="WH-A" if tenant_id == 1 else f"WH-{tenant_id}",
            name=f"企业{tenant_id}仓",
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        user = User(
            username="sales-approver" if tenant_id == 1 else f"sales-approver-{tenant_id}",
            password="x",
            display_name="销售审批人",
            role="admin",
            tenant_id=tenant_id,
            is_active=True,
        )
        db.add_all([customer, product, warehouse, user])
        db.flush()
        now = datetime.now()
        db.add(
            InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=20,
                available_quantity=20,
                reserved_quantity=0,
                unit="件",
                in_date=now.date(),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        user_id = int(user.id)
        db.close()
    return user_id


def _historical_plan():
    from app.application.workflow.workflow_types import plan_from_dict

    payload = {
        "idempotency_key": "sales-restart-contract",
        "order": {
            "customer_name": "测试客户 A",
            "customer_resolution": "current_tenant_exact_name",
            "currency": "CNY",
            "items": [
                {
                    "product_name": "产品 B",
                    "product_resolution": "current_tenant_exact_name",
                    "quantity": 10,
                    "unit": "件",
                    "unit_price": 100,
                    "line_total": 1000,
                }
            ],
            "total_amount": 1000,
        },
        "fulfillment": {
            "requested": True,
            "quantity": 10,
            "unit": "件",
            "warehouse_resolution": "current_tenant_default",
        },
        "invoice": {"requested": True, "amount": 1000, "currency": "CNY"},
        "payment_allocation": {
            "requested": False,
            "amount": 1000,
            "currency": "CNY",
            "receipt_voucher": None,
        },
    }
    plan = {
        "plan_id": "sales-restart-plan",
        "intent": "sales_write",
        "risk_level": "high",
        "metadata": {"approval_required_node_ids": ["sales_execute_closed_loop"]},
        "nodes": [
            {
                "node_id": "sales_execute_closed_loop",
                "tool_id": "sales",
                "action": "execute_closed_loop",
                "params": {"payload": payload},
                "risk": "high",
                "idempotent": True,
            },
            {
                "node_id": "verify_sales_result",
                "tool_id": "sales",
                "action": "verify_closed_loop",
                "params": {"payload": payload},
                "risk": "low",
                "idempotent": True,
                "depends_on": ["sales_execute_closed_loop"],
            },
            {
                "node_id": "export_sales",
                "tool_id": "reports",
                "action": "export",
                "params": {"report_type": "sales"},
                "risk": "low",
                "idempotent": True,
                "depends_on": ["verify_sales_result"],
            },
        ],
    }
    restored = plan_from_dict(plan)
    assert restored is not None
    return restored


def _actor(factory, user_id):
    from datetime import timedelta

    from starlette.requests import Request

    from app.db.models.permission import DEFAULT_ROLES, Permission, Role
    from app.db.models.user import Session as UserSession
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.utils.time import utc_now_naive

    session_id = "sales-restart-session"
    with factory.begin() as db:
        if db.query(UserSession).filter_by(session_id=session_id).first() is None:
            db.add(
                UserSession(
                    session_id=session_id,
                    user_id=user_id,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )
            role = Role(name="admin")
            permissions = next(r["permissions"] for r in DEFAULT_ROLES if r["name"] == "admin")
            for code in [*permissions, "tool.finance.ledger_query"]:
                role.permissions.append(Permission(code=code, name=code))
            db.add(role)
    request = Request(
        {"type": "http", "method": "POST", "headers": [(b"x-session-id", session_id.encode())]}
    )
    return authenticated_runtime_context({}, require_agent_principal(request, x_user_id=None))


def confirm_phase(db_path: Path, marker: Path) -> None:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.ai_chat.conversation_history import persist_chat_turn
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.workflow_types import plan_from_dict

    factory = _prepare(db_path)
    user_id = _seed(factory)
    context = _actor(factory, user_id)
    with tenant_scope(1):
        # This restart suite retains a historical approval graph across the
        # rollout. New public tasks are covered by the fixed Xiaox suites.
        from uuid import uuid4

        from app.application.agent_orchestrator.business_harness import (
            ensure_business_harness_context,
        )
        from app.application.ai_chat.dialogue_memory import bind_chat_turn_context

        historical_context = {
            **context,
            "conversation_id": str(user_id),
            "turn_id": uuid4().hex,
        }
        bind_chat_turn_context(SENTENCE, historical_context)
        historical_context = ensure_business_harness_context(historical_context, message=SENTENCE)
        waiting_run = AgentOrchestrator(repository=get_agent_run_repository()).start_run_from_plan(
            user_id=str(user_id),
            message=SENTENCE,
            plan=_historical_plan(),
            runtime_context=historical_context,
        )
        assert waiting_run.status == "waiting_user", waiting_run.to_dict()
        stored_plan = plan_from_dict(waiting_run.metadata["plan"])
        assert stored_plan is not None
        approvals = ApprovalService()
        request = approvals.create_approval_request(
            plan_id=stored_plan.plan_id,
            node=stored_plan.nodes[0],
            runtime_context={**historical_context, "_approval_agent_run_required": True},
            plan=stored_plan,
            require_persistence=True,
        )
        request_no, run_id = request.request_id, waiting_run.run_id
        assert approvals.attach_pending_agent_run(
            request_no, agent_run_id=run_id, approved_step_id="sales_execute_closed_loop"
        )
        saved = persist_chat_turn(
            str(user_id),
            SENTENCE,
            historical_context,
            {
                "success": True,
                "response": "原任务已保存，正在等待原审批。",
                "data": {"execution_state": "waiting_user", "run_id": run_id},
            },
        )
        assert saved["status"] == "saved", saved
    waiting_run = get_agent_run_repository().get(run_id)
    assert waiting_run.metadata["runtime_context"]["_conversation_revision"] == 0
    from app.db.models.approval import ApprovalRequest

    runtime = get_agent_run_repository().get(run_id).metadata["runtime_context"]
    assert type(runtime["_conversation_revision"]) is int
    assert runtime["_conversation_revision"] == 0
    with tenant_scope(1):
        db = factory()
        row = db.query(ApprovalRequest).filter_by(request_no=request_no).one()
        request_id = int(row.id)
        orders = db.query(SalesOrder).count()
        db.close()
    marker.write_text(
        json.dumps(
            {
                "request_no": request_no,
                "request_id": request_id,
                "user_id": user_id,
                "orders": orders,
                "run_id": run_id,
                "conversation_id": runtime["conversation_id"],
                "conversation_revision": runtime["_conversation_revision"],
            }
        ),
        encoding="utf-8",
    )
    if os.environ.get("WAIT") == "1":
        time.sleep(30)


def invalidate_phase(db_path: Path, marker: Path, action: str) -> None:
    from app.application.task_conversation_store import task_conversation_store
    from app.db.models import AIConversation, AIConversationSession

    factory = _prepare(db_path)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    identity = {"session_id": payload["conversation_id"], "user_id": payload["user_id"]}
    with tenant_scope(1):
        if action == "delete":
            assert task_conversation_store.delete_session(**identity)
        else:
            with factory() as db:
                message = db.query(AIConversation).filter_by(role="user").first()
                message_id = int(message.id)
            assert task_conversation_store.delete_messages_from(**identity, message_id=message_id)
        with factory() as db:
            session = (
                db.query(AIConversationSession).filter_by(session_id=identity["session_id"]).one()
            )
            assert session.revision == payload["conversation_revision"] + 1
            assert (session.deleted_at is not None) == (action == "delete")


def approve_phase(db_path: Path, marker: Path, result_path: Path) -> None:
    from unittest.mock import Mock, patch

    factory = _prepare(db_path)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    with patch(
        "app.application.approval_workspace_app_service.notify_mobile_user",
        lambda *_args, **_kwargs: None,
    ):
        with patch(
            "app.application.approval_workspace_app_service._resolve_actor",
            return_value=payload["user_id"],
        ):
            from app.application.approval_workspace_app_service import approve_request

            with tenant_scope(1):
                response = approve_request(payload["request_id"], Mock(), body={"opinion": "同意"})
    if not isinstance(response, dict):
        body = response.body.decode() if hasattr(response, "body") else str(response)
        raise AssertionError(f"approve failed: {getattr(response, 'status_code', '')} {body}")
    execution = response["data"]["workflow_execution"]
    if execution.get("success") is not True or execution.get("nodes_executed") != 3:
        raise AssertionError(json.dumps(execution, ensure_ascii=False))
    with tenant_scope(1):
        db = factory()
        order = db.query(SalesOrder).one()
        item = db.query(SalesOrderItem).one()
        outbound = db.query(InventoryTransaction).filter_by(transaction_type="out").one()
        journal = db.query(JournalEntry).one()
        ledger = db.query(InventoryLedger).one()
        evidence = {
            "success": response["success"],
            "request_no": payload["request_no"],
            "order_no": order.order_no,
            "quantity": str(item.quantity),
            "amount": str(order.total_amount),
            "payment_state": order.payment_state,
            "paid_amount": str(order.paid_amount or 0),
            "stock": str(ledger.available_quantity),
            "outbound_quantity": str(outbound.quantity),
            "journal_balanced": journal.is_balanced(),
            "journal_count": db.query(JournalEntry).count(),
            "order_count": db.query(SalesOrder).count(),
            "audit_actions": list(db.execute(text("SELECT action FROM ai_action_audit")).scalars()),
        }
        for action in (
            "approval.submit_ai_workflow",
            "approval.approve_ai_workflow",
            "approval.execute_ai_workflow",
        ):
            assert evidence["audit_actions"].count(action) == 1
        db.close()
    from app.application.agent_orchestrator.artifact_files import read_verified_spreadsheet
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository

    runs = get_agent_run_repository().list_recent(limit=5)
    run = next(item for item in runs if item.status == "completed")
    export = next(step for step in run.steps if step.node_id == "export_sales")
    workbook = read_verified_spreadsheet(run.run_id, export.output["artifacts"][0])
    evidence["export_sha256"] = hashlib.sha256(workbook).hexdigest()
    evidence["nodes"] = [step.node_id for step in run.steps]
    result_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    assert evidence["order_count"] == 1
    assert Decimal(evidence["quantity"]) == Decimal("10")
    assert Decimal(evidence["amount"]) == Decimal("1000")
    assert Decimal(evidence["stock"]) == Decimal("10")
    assert Decimal(evidence["outbound_quantity"]) == Decimal("-10")
    assert evidence["payment_state"] == "unpaid"
    assert Decimal(evidence["paid_amount"]) == Decimal("0")
    assert evidence["journal_balanced"] is True


def _spawn(
    phase: str, db_path: Path, marker: Path, result_path: Path, *, wait: bool
) -> subprocess.Popen:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["SALES_DB"] = str(db_path)
    env["SALES_MARKER"] = str(marker)
    env["SALES_RESULT"] = str(result_path)
    env["WAIT"] = "1" if wait else "0"
    env["XCAGI_DIALOGUE_MEMORY_DIR"] = str(db_path.parent / "dialogue-memory")
    env["XCAGI_USER_MEMORY_DIR"] = str(db_path.parent / "user-memory")
    env["XCAGI_USER_MEMORY_JSON_PATH"] = str(db_path.parent / "user-memory" / "memory_store.json")
    env["XCAGI_TOOL_IDEMPOTENCY_PATH"] = str(db_path.parent / "tool-idempotency.sqlite")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH", "")]
    )
    log = db_path.with_name(f"{phase}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, __file__, phase],
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    process.log_handle = log
    return process


def _wait_for(path: Path, proc: subprocess.Popen, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        if proc.poll() is not None:
            raise AssertionError(
                f"worker exited {proc.returncode} before writing {path.name}: "
                + Path(proc.log_handle.name).read_text(encoding="utf-8")[-6000:]
            )
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {path.name}")


def sale_fault_phase(db_path: Path, marker: Path, output: Path, phase: str) -> None:
    """Exercise the actual transaction in a disposable process, without a model call."""
    from app.application.sales_app_service import SalesAppService

    factory = _prepare(db_path)
    if phase == "sale_seed":
        _seed(factory)
        _seed(factory, tenant_id=2)
        marker.write_text("seeded", encoding="utf-8")
        return

    def stop_before_response(*_args):
        marker.write_text(json.dumps({"phase": phase, "pid": os.getpid()}), encoding="utf-8")
        while True:
            time.sleep(0.05)

    if phase == "sale_stock_written":

        def after_statement(_conn, _cursor, statement, *_args):
            if statement.lower().lstrip().startswith("insert into inventory_transactions"):
                stop_before_response()

        event.listen(factory.kw["bind"], "after_cursor_execute", after_statement)
    elif phase == "sale_committed":
        event.listen(factory.class_, "after_commit", stop_before_response)

    payload = _historical_plan().nodes[0].params["payload"]
    with tenant_scope(1):
        result = SalesAppService().execute_closed_loop(payload)
    assert result["success"] is True, result
    output.write_text(json.dumps(result, default=str), encoding="utf-8")


def _sale_snapshot(db_path: Path, *, completed: bool) -> None:
    """Read durable rows independently of the worker's ORM and returned receipt."""
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        for table in (
            "sales_orders",
            "sales_order_items",
            "inventory_transactions",
            "journal_entries",
        ):
            assert db.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=1").fetchone() == (
                int(completed),
            )
            assert db.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=2").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM receivable_allocations").fetchone() == (0,)
        stock = dict(db.execute("SELECT tenant_id, available_quantity FROM inventory_ledger"))
        assert stock == {1: 10 if completed else 20, 2: 20}
        if completed:
            assert db.execute(
                "SELECT total_amount, invoice_status, payment_state FROM sales_orders WHERE tenant_id=1"
            ).fetchone() == (1000, "invoiced", "unpaid")
            assert db.execute(
                "SELECT quantity FROM inventory_transactions WHERE tenant_id=1"
            ).fetchone() == (-10,)


def _finish_sale_process(proc: subprocess.Popen) -> None:
    try:
        proc.wait(timeout=60)
        assert proc.returncode == 0, Path(proc.log_handle.name).read_text(encoding="utf-8")[-6000:]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        proc.log_handle.close()


@pytest.mark.parametrize("interrupt_point", ["stock_written", "committed"])
def test_sale_process_loss_and_backup_restore_preserve_one_original_effect(
    tmp_path: Path, monkeypatch, interrupt_point
):
    """Kill during a write or after commit, then retry and restore the same business."""
    from app.domain.shared_services.database_service import DatabaseService

    db_path, marker = tmp_path / "sales.db", tmp_path / "seeded"
    result_path = tmp_path / "first-result.json"
    _finish_sale_process(_spawn("sale_seed", db_path, marker, result_path, wait=False))
    _sale_snapshot(db_path, completed=False)
    marker.unlink()
    interrupted = _spawn(f"sale_{interrupt_point}", db_path, marker, result_path, wait=False)
    try:
        _wait_for(marker, interrupted)
        _sale_snapshot(db_path, completed=interrupt_point == "committed")
        interrupted.kill()
        interrupted.wait(timeout=10)
        assert interrupted.returncode != 0
    finally:
        if interrupted.poll() is None:
            interrupted.kill()
            interrupted.wait(timeout=10)
        interrupted.log_handle.close()
    assert not result_path.exists(), "the client must not have received a success response"
    _sale_snapshot(db_path, completed=interrupt_point == "committed")
    _finish_sale_process(_spawn("sale_retry", db_path, marker, result_path, wait=False))
    assert json.loads(result_path.read_text())["replayed"] is (interrupt_point == "committed")
    _sale_snapshot(db_path, completed=True)

    service = DatabaseService()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_get_db_path", lambda: str(db_path))
    monkeypatch.setattr(service, "_get_backup_dir", lambda: str(backup_dir))
    backup = service.backup_database()
    assert backup["success"] is True, backup
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("UPDATE inventory_ledger SET quantity=0, available_quantity=0 WHERE tenant_id=1")
        db.commit()
    restored = service.restore_database(backup["filename"])
    assert restored["success"] is True, restored
    _sale_snapshot(db_path, completed=True)

    # Two fresh workers receive retries after the lost response and real restore.
    retries = [
        _spawn(phase, db_path, marker, tmp_path / f"{phase}.json", wait=False)
        for phase in ("sale_repeat", "sale_duplicate")
    ]
    try:
        for retry in retries:
            _finish_sale_process(retry)
    finally:
        for retry in retries:
            if retry.poll() is None:
                retry.kill()
                retry.wait(timeout=10)
            retry.log_handle.close()
    for phase in ("sale_repeat", "sale_duplicate"):
        result = json.loads((tmp_path / f"{phase}.json").read_text())
        assert result["success"] is True and result["replayed"] is True
    _sale_snapshot(db_path, completed=True)


@pytest.mark.parametrize(
    "kill,invalidate", [(False, None), (True, None), (False, "delete"), (False, "withdraw")]
)
def test_persisted_sales_plan_survives_restart_and_exports_once(
    tmp_path: Path, kill: bool, invalidate
):
    db_path = tmp_path / "sales.db"
    marker = tmp_path / "marker.json"
    result_path = tmp_path / "result.json"
    confirm = _spawn("confirm", db_path, marker, result_path, wait=kill)
    try:
        _wait_for(marker, confirm)
        if kill:
            os.kill(confirm.pid, signal.SIGKILL)
            confirm.wait(timeout=10)
            assert confirm.returncode != 0
        else:
            confirm.wait(timeout=60)
            assert confirm.returncode == 0, Path(confirm.log_handle.name).read_text(
                encoding="utf-8"
            )
    finally:
        if confirm.poll() is None:
            confirm.kill()
            confirm.wait(timeout=10)
        confirm.log_handle.close()
    before = json.loads(marker.read_text(encoding="utf-8"))
    assert before["orders"] == 0
    if invalidate:
        changed = _spawn(invalidate, db_path, marker, result_path, wait=False)
        try:
            changed.wait(timeout=60)
            assert changed.returncode == 0, Path(changed.log_handle.name).read_text(
                encoding="utf-8"
            )
        finally:
            if changed.poll() is None:
                changed.kill()
                changed.wait(timeout=10)
            changed.log_handle.close()
    approve = _spawn("approve", db_path, marker, result_path, wait=False)
    approve.wait(timeout=90)
    approve.log_handle.close()
    if invalidate:
        assert approve.returncode != 0
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect() as db:
                stored = json.loads(
                    db.exec_driver_sql(
                        "SELECT payload_json FROM agent_runs WHERE run_id = ?", (before["run_id"],)
                    ).scalar_one()
                )
                assert stored["status"] == "blocked"
                assert stored["error"] == "原会话已变更、删除或授权失效，拒绝恢复旧上下文"
                assert stored["metadata"]["runtime_context"]["_conversation_revision"] == 0
                assert all(step["status"] != "completed" for step in stored["steps"])
                audit_actions = set(
                    db.exec_driver_sql("SELECT action FROM ai_action_audit").scalars()
                )
                assert {
                    "approval.submit_ai_workflow",
                    "approval.execute_ai_workflow_failed",
                } <= audit_actions
                assert "approval.approve_ai_workflow" not in audit_actions
                for model in (SalesOrder, SalesOrderItem, InventoryTransaction, JournalEntry):
                    assert (
                        db.exec_driver_sql(
                            f"SELECT count(*) FROM {model.__tablename__}"
                        ).scalar_one()
                        == 0
                    )
                assert Decimal(
                    str(
                        db.exec_driver_sql(
                            "SELECT available_quantity FROM inventory_ledger"
                        ).scalar_one()
                    )
                ) == Decimal("20")
        finally:
            engine.dispose()
        assert not result_path.exists()
        return
    assert approve.returncode == 0, (db_path.with_name("approve.log")).read_text(encoding="utf-8")[
        -2000:
    ]
    evidence = json.loads(result_path.read_text(encoding="utf-8"))
    assert evidence["request_no"] == before["request_no"]
    assert evidence["order_count"] == 1
    assert evidence["payment_state"] == "unpaid"
    assert evidence["nodes"] == [
        "sales_execute_closed_loop",
        "verify_sales_result",
        "export_sales",
    ]
    assert len(evidence["export_sha256"]) == 64
    replay = _spawn("replay", db_path, marker, result_path, wait=False)
    replay.wait(timeout=60)
    replay.log_handle.close()
    assert replay.returncode != 0
    assert "当前状态不可审批：approved" in db_path.with_name("replay.log").read_text(
        encoding="utf-8"
    )


if __name__ == "__main__":
    phase = sys.argv[1]
    database = Path(os.environ["SALES_DB"])
    marker_path = Path(os.environ["SALES_MARKER"])
    output = Path(os.environ["SALES_RESULT"])
    if phase.startswith("sale_"):
        sale_fault_phase(database, marker_path, output, phase)
    elif phase == "confirm":
        confirm_phase(database, marker_path)
    elif phase in {"delete", "withdraw"}:
        invalidate_phase(database, marker_path, phase)
    elif phase in {"approve", "replay"}:
        approve_phase(database, marker_path, output)
    else:
        raise SystemExit(f"unknown phase {phase}")
