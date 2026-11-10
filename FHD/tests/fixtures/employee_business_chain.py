"""Real customer/order/report tools for the four-employee chain and recovery cases."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.artifact_files import verified_spreadsheet_path
from app.application.employee_runtime.executor import execute_employee_task_local
from app.application.employee_runtime.task_continuity import load_employee_task_ledger
from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.task_lifecycle import TaskLifecycleRecord

EMPLOYEES = [f"employee-{name}" for name in "abcd"]
CUSTOMER = "四人员工链客户甲"
_ACTOR = ContextVar("business_chain_test_actor", default=None)


def invoke(workspace: Path, action: str, **payload) -> dict:
    return execute_employee_task_local(
        EMPLOYEES[0],
        "查询客户订单，生成销售 Excel，并汇总销售额",
        {
            "continuity_action": action,
            "workspace_root": str(workspace),
            "tenant_id": "11",
            "user_id": "11",
            **payload,
        },
        user_id=11,
        workspace_root=str(workspace),
        runtime_context=_ACTOR.get() or {},
    )


def business_plan() -> dict:
    filters = {
        "customer_id": "{{customer.data[0].id}}",
        "start_date": "2026-11-01",
        "end_date": "2026-11-30",
    }
    return {
        "employees": EMPLOYEES,
        "permissions": [
            "customers.query",
            "sales.query",
            "reports.export",
            "reports.sales_summary",
        ],
        "steps": [
            {
                "step_id": "customer",
                "tool": "customers",
                "action": "query",
                "params": {"keyword": CUSTOMER},
            },
            {"step_id": "orders", "tool": "sales", "action": "query", "params": dict(filters)},
            {
                "step_id": "export",
                "tool": "reports",
                "action": "export",
                "params": {
                    **filters,
                    "group_by": "customer",
                    "report_type": "sales",
                    "filename": "四人员工销售报表",
                },
            },
            {
                "step_id": "summary",
                "tool": "reports",
                "action": "sales_summary",
                "params": {**filters, "group_by": "customer"},
            },
        ],
    }


@contextmanager
def business_workspace(workspace: Path):
    children_before = {child.pid for child in multiprocessing.active_children()}
    workspace.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{workspace / 'business.sqlite'}")
    from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
    from tests.fixtures.employee_test_identity import seed_employee_identity

    factory = seed_employee_identity(engine, session_id="chain-session", username="chain-actor")

    @contextmanager
    def sessions():
        with factory() as db:
            yield db
            db.commit()

    with factory() as db:
        for identity, tenant, name in ((101, 11, CUSTOMER), (202, 22, "其他企业客户")):
            db.add(PurchaseUnit(id=identity, unit_name=name, tenant_id=tenant, is_active=True))
            db.add(Customer(id=identity, customer_name=name, tenant_id=tenant))
        for identity, tenant, customer, amount, month in (
            (1, 11, 101, 120, 11),
            (2, 11, 101, 80, 11),
            (3, 11, 101, 700, 10),
            (4, 22, 202, 999, 11),
        ):
            db.add(
                SalesOrder(
                    id=identity,
                    order_no=f"CHAIN-{identity}",
                    customer_id=customer,
                    customer_name=CUSTOMER if tenant == 11 else "其他企业客户",
                    state="confirmed",
                    status="confirmed",
                    total_amount=amount,
                    tenant_id=tenant,
                    created_at=datetime(2026, month, 6),
                )
            )
            db.add(
                SalesOrderItem(
                    id=identity,
                    order_id=identity,
                    product_name="业务链产品",
                    quantity=1,
                    unit_price=amount,
                    amount=amount,
                    tenant_id=tenant,
                )
            )
        db.commit()
    folder = workspace / "employees"
    folder.mkdir()
    for employee in EMPLOYEES:
        (folder / f"{employee}.json").write_text(
            json.dumps({"employee_id": employee, "tenant_id": "11", "available": True}),
            encoding="utf-8",
        )
    try:
        with ExitStack() as stack:
            stack.enter_context(patch("app.db.HostSessionLocal", factory))
            stack.enter_context(patch("app.db.session.SessionLocal", factory))
            stack.enter_context(
                patch("app.application.customer_app_service.get_customers_session", factory)
            )
            stack.enter_context(patch("app.application.sales_app_service.get_db", sessions))
            stack.enter_context(patch("app.domain.shared_services.report_service.get_db", sessions))
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {
                        "XCAGI_DATA_DIR": str(workspace / "data"),
                        "DATABASE_URL": str(engine.url),
                        "XCAGI_PRODUCT_SKU": "enterprise",
                        "SECRET_KEY": "employee-chain-isolated-secret-32bytes",
                        "AUDIT_LOG_PATH": str(workspace / "audit.jsonl"),
                        "XCAGI_TOOL_IDEMPOTENCY_PATH": str(workspace / "idempotency.sqlite"),
                    },
                )
            )
            binding = bind_agent_actor_scope(session_id="chain-session", user_id="11")
            token = _ACTOR.set(
                {
                    "tenant_id": "11",
                    "user_id": "11",
                    "actor_id": "11",
                    "_actor_authorization": binding,
                }
            )
            try:
                yield
            finally:
                _ACTOR.reset(token)
    finally:
        # Preserve the observed product failure; reclaim only this fixture's
        # surviving workers so a failed cleanup cannot hang pytest shutdown.
        for child in multiprocessing.active_children():
            if child.pid not in children_before and child.is_alive():
                child.kill()
                child.join(timeout=5)
        engine.dispose()


def _records(workspace: Path, task_id: str) -> tuple[dict, dict, dict]:
    ledger = load_employee_task_ledger(workspace)
    task = ledger["tasks"][task_id]
    completed = (task.get("chain") or {}).get("completed") or {}
    records = {key: ledger["handoffs"][value] for key, value in completed.items()}
    outputs = {
        key: row["result_payload"]["result"]["final_output"]["node_outputs"]["handoff-work"]
        for key, row in records.items()
    }
    return ledger, records, outputs


def _artifacts(workspace: Path, task_id: str) -> list[dict]:
    _, records, _ = _records(workspace, task_id)
    result = []
    for record in records.values():
        receipt = record["result_payload"]
        for artifact in receipt["result"]["final_output"].get("artifacts") or []:
            if (
                artifact.get("mime_type")
                != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ):
                continue
            path = verified_spreadsheet_path(receipt["child_task_id"], artifact)
            result.append(
                {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "mtime_ns": path.stat().st_mtime_ns,
                }
            )
    return result


def run_business_chain(workspace: Path, *, fail_last_hop: bool = False) -> dict:
    with business_workspace(workspace):
        started = invoke(workspace, "start")
        task_id = str(started["task_id"])
        plan = business_plan()
        card = workspace / "employees" / f"{EMPLOYEES[-1]}.json"
        if fail_last_hop:
            card.write_text(
                json.dumps({"employee_id": EMPLOYEES[-1], "tenant_id": "11", "available": False}),
                encoding="utf-8",
            )
        first = invoke(workspace, "chain", task_id=task_id, **plan)
        before, completed_before, _ = _records(workspace, task_id)
        artifacts_before = _artifacts(workspace, task_id)
        if fail_last_hop:
            card.write_text(
                json.dumps({"employee_id": EMPLOYEES[-1], "tenant_id": "11", "available": True}),
                encoding="utf-8",
            )
        result = invoke(workspace, "retry_handoff", task_id=task_id) if fail_last_hop else first
        after, completed, outputs = _records(workspace, task_id)
        artifacts = _artifacts(workspace, task_id)
        replay = invoke(workspace, "retry_handoff", task_id=task_id) if fail_last_hop else result
        replayed, _, _ = _records(workspace, task_id)
        replay_artifacts = _artifacts(workspace, task_id)

        calls = {
            key: value for key, value in after["tool_calls"].items() if value["task_id"] == task_id
        }
        before_calls = {
            key: value for key, value in before["tool_calls"].items() if value["task_id"] == task_id
        }
        receipts = [
            completed[key]["result_payload"]
            for key in ("customer", "orders", "export", "summary")
            if key in completed
        ]
        actual_orders = outputs.get("orders", {}).get("data", [])
        summary = outputs.get("summary", {}).get("summary", {})
        workbook_rows = []
        if len(artifacts) == 1:
            book = load_workbook(artifacts[0]["path"], read_only=True, data_only=True)
            try:
                workbook_rows = list(book.active.iter_rows(values_only=True))
            finally:
                book.close()
        complete = (
            result.get("business_success") is True
            and [row.get("employee_id") for row in receipts] == EMPLOYEES
            and len({row.get("child_task_id") for row in receipts}) == 4
            and all(
                row.get("parent_task_id") == task_id and row.get("tenant_id") == "11"
                for row in receipts
            )
            and {row.get("id") for row in actual_orders} == {1, 2}
            and summary.get("total_amount") == 200
            and workbook_rows == [("customer_name", "order_count", "amount"), (CUSTOMER, 2, 200)]
        )
        recovered = (
            fail_last_hop
            and first.get("business_success") is False
            and first.get("handoff", {}).get("target_employee") == EMPLOYEES[-1]
            and first.get("handoff", {}).get("status") == "failed"
            and set(completed_before) == {"customer", "orders", "export"}
            and all(after["tool_calls"].get(key) == value for key, value in before_calls.items())
            and len(calls) == len(before_calls) + 1
            and artifacts_before == artifacts == replay_artifacts
            and replayed["tool_calls"] == after["tool_calls"]
            and replay.get("business_success") is True
            and all(value["invocations"] == 1 for value in replayed["side_effects"].values())
        )
        return {
            "task_id": task_id,
            "complete": complete,
            "recovered": recovered,
            "first_result": first,
            "result": result,
            "receipts": receipts,
            "tool_calls": list(calls.values()),
            "summary": summary,
            "workbook_rows": workbook_rows,
            "artifacts": artifacts,
            "completed_before": list(completed_before),
            "error": result.get("error_code") or "",
        }
