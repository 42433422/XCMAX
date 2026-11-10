"""真实 process_chat 确认后，杀掉进程再审批，原计划继续执行且只写一次。"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
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
    from app.application.agent_orchestrator.run_repository import (
        set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.run_sql_repository import (
        SQLAlchemyAgentRunRepository,
    )

    set_agent_run_repository_for_tests(SQLAlchemyAgentRunRepository(session_factory=factory))
    return factory


def _seed(factory) -> int:
    from datetime import datetime

    from app.db.models import Customer, InventoryLedger, Product, Warehouse
    from app.db.models.user import User

    with tenant_scope(1):
        db = factory()
        customer = Customer(customer_name="测试客户 A")
        product = Product(name="产品 B", unit="件", model_number="TEST-B-001", is_active=1)
        warehouse = Warehouse(
            code="WH-A",
            name="企业1仓",
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        user = User(
            username="sales-approver",
            password="x",
            display_name="销售审批人",
            role="admin",
            tenant_id=1,
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


def _chat_service():
    from unittest.mock import Mock, patch

    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.planner import LLMWorkflowPlanner

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
        "mode": "workflow",
        "intent": "sales_write",
        "risk_level": "high",
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
    conversation = Mock(get_context=Mock(return_value=None))
    with patch(
        "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=conversation
    ):
        service = AIChatApplicationService()
    service.workflow_planner = LLMWorkflowPlanner(
        ai_service=conversation,
        completion=lambda **_: {
            "choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]
        },
    )
    return service


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
            for code in next(r["permissions"] for r in DEFAULT_ROLES if r["name"] == "admin"):
                role.permissions.append(Permission(code=code, name=code))
            db.add(role)
    request = Request(
        {"type": "http", "method": "POST", "headers": [(b"x-session-id", session_id.encode())]}
    )
    return authenticated_runtime_context({}, require_agent_principal(request, x_user_id=None))


def confirm_phase(db_path: Path, marker: Path) -> None:
    factory = _prepare(db_path)
    user_id = _seed(factory)
    service = _chat_service()
    context = _actor(factory, user_id)
    with tenant_scope(1):
        first = service.process_chat(
            user_id=str(user_id),
            message=SENTENCE,
            context=context,
            source="pro",
        )
        assert first["data"]["action"] == "workflow_confirmation_required", first
        second = service.process_chat(
            user_id=str(user_id),
            message="确认",
            context=context,
            source="pro",
        )
    assert second["data"]["action"] == "approval_pending", second
    request_no = second["data"]["data"]["approval_request_ids"][0]
    from app.db.models.approval import ApprovalRequest

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
            }
        ),
        encoding="utf-8",
    )
    if os.environ.get("WAIT") == "1":
        time.sleep(30)


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
        }
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


@pytest.mark.parametrize("kill", [False, True])
def test_process_chat_survives_restart_and_exports_once(tmp_path: Path, kill: bool):
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
    finally:
        if confirm.poll() is None:
            confirm.kill()
            confirm.wait(timeout=10)
        confirm.log_handle.close()
    before = json.loads(marker.read_text(encoding="utf-8"))
    assert before["orders"] == 0
    approve = _spawn("approve", db_path, marker, result_path, wait=False)
    approve.wait(timeout=90)
    approve.log_handle.close()
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
    replay = _spawn("approve", db_path, marker, result_path, wait=False)
    replay.wait(timeout=60)
    replay.log_handle.close()
    assert replay.returncode != 0


if __name__ == "__main__":
    phase = sys.argv[1]
    database = Path(os.environ["SALES_DB"])
    marker_path = Path(os.environ["SALES_MARKER"])
    output = Path(os.environ["SALES_RESULT"])
    if phase == "confirm":
        confirm_phase(database, marker_path)
    elif phase == "approve":
        approve_phase(database, marker_path, output)
    else:
        raise SystemExit(f"unknown phase {phase}")
