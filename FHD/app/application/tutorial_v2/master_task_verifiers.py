"""Master-data and task-evidence verifiers for Tutorial V2."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.application.tutorial_v2.common import json_load as _load_json
from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord, AgentTaskRecord
from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.tutorial import TutorialRun
from app.infrastructure.tenant_scope import tenant_scope


class TutorialMasterTaskVerifierMixin:
    def _verify_customer(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        with tenant_scope(run.workspace.tutorial_tenant_id):
            core_rows = db.query(Customer).filter(Customer.customer_name == "客户B").all()
            purchase_unit_rows = (
                db.query(PurchaseUnit).filter(PurchaseUnit.unit_name == "客户B").all()
            )
        # The active customer-management page persists the shared customer/purchase-unit
        # entity.  A core Customer is also accepted for compatibility, but ambiguous
        # duplicates across the two stores fail closed.
        core_only = len(core_rows) == 1 and not purchase_unit_rows
        purchase_unit_only = len(purchase_unit_rows) == 1 and not core_rows
        ok = core_only or purchase_unit_only
        row = core_rows[0] if core_only else purchase_unit_rows[0] if purchase_unit_only else None
        return (
            ok,
            "verification_passed" if ok else "customer_not_ready",
            [
                {
                    "type": "customer" if core_only else "purchase_unit",
                    "id": row.id,
                }
            ]
            if row is not None
            else [],
            {
                "customer_count": len(core_rows) + len(purchase_unit_rows),
                "core_customer_count": len(core_rows),
                "purchase_unit_count": len(purchase_unit_rows),
            },
        )

    def _verify_product(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        with tenant_scope(run.workspace.tutorial_tenant_id):
            rows = db.query(Product).filter(Product.name == "A 产品").all()
        ok = (
            len(rows) == 1
            and Decimal(str(rows[0].price or 0)) == Decimal("100")
            and int(rows[0].quantity or 0) == 100
        )
        return (
            ok,
            "verification_passed" if ok else "product_not_ready",
            [{"type": "product", "id": rows[0].id}] if ok else [],
            {
                "product_count": len(rows),
                "price": float(rows[0].price or 0) if len(rows) == 1 else 0,
                "inventory": int(rows[0].quantity or 0) if len(rows) == 1 else 0,
            },
        )

    def _task_rows(self, db: Session, run: TutorialRun) -> list[AgentTaskRecord]:
        rows = (
            db.query(AgentTaskRecord)
            .filter(
                AgentTaskRecord.tenant_id == str(run.workspace.tutorial_tenant_id),
                AgentTaskRecord.user_id == str(run.user_id),
                AgentTaskRecord.status == "completed",
            )
            .order_by(AgentTaskRecord.updated_at.desc())
            .all()
        )
        return [
            row
            for row in rows
            if any(marker in str(row.title or "") for marker in ("查询", "库存", "查看"))
            and str(row.task_type or "") not in {"sales_write", "write"}
        ]

    def _observed_task_execution_count(
        self,
        db: Session,
        run: TutorialRun,
        task: AgentTaskRecord,
    ) -> int:
        if not task.active_run_id:
            return 0
        run_record = (
            db.query(AgentRunRecord)
            .filter(
                AgentRunRecord.run_id == task.active_run_id,
                AgentRunRecord.user_id == str(run.user_id),
                AgentRunRecord.status == "completed",
            )
            .first()
        )
        payload = _load_json(run_record.payload_json, {}) if run_record else {}
        steps = payload.get("steps") if isinstance(payload, dict) else None
        calls = payload.get("tool_calls") if isinstance(payload, dict) else None
        final_output = payload.get("final_output") if isinstance(payload, dict) else None
        events = payload.get("events") if isinstance(payload, dict) else None
        has_completed_step = isinstance(steps, list) and any(
            isinstance(item, dict) and item.get("status") == "completed" for item in steps
        )
        has_completed_call = isinstance(calls, list) and any(
            isinstance(item, dict) and item.get("status") == "completed" for item in calls
        )
        has_terminal_event = isinstance(events, list) and any(
            isinstance(item, dict) and item.get("event_type") == "run.completed" for item in events
        )
        has_result = isinstance(final_output, dict) and bool(final_output)
        return int((has_completed_step or has_completed_call or has_terminal_event) and has_result)

    def _verify_task(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        tasks = self._task_rows(db, run)
        queue_executions = 0
        observed_executions = 0
        if tasks:
            queue_executions = (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.task_id == tasks[0].task_id)
                .count()
            )
            observed_executions = self._observed_task_execution_count(db, run, tasks[0])
        executions = queue_executions + observed_executions
        ok = bool(tasks) and executions > 0
        code = (
            "verification_passed"
            if ok
            else ("task_evidence_not_ready" if tasks else "task_not_completed")
        )
        return (
            ok,
            code,
            [{"type": "agent_task", "id": tasks[0].task_id}] if ok else [],
            {
                "completed_task_count": len(tasks),
                "execution_count": executions,
                "queue_execution_count": queue_executions,
                "observed_execution_count": observed_executions,
                "run_count": int(tasks[0].run_count) if tasks else 0,
            },
        )

    def _verify_task_evidence_viewed(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        ok, code, refs, counts = self._verify_task(db, run, context)
        tasks = self._task_rows(db, run)
        viewed = bool(tasks) and tasks[0].attention_state != "result_unread"
        if not ok or not viewed:
            return False, "task_evidence_not_ready", [], {**counts, "result_viewed": int(viewed)}
        return True, code, refs, {**counts, "result_viewed": 1}

    def _verify_second_readonly_task(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        tasks = self._task_rows(db, run)
        distinct_titles = {str(item.title or "").strip() for item in tasks if item.title}
        customer_queries = [item for item in tasks if "客户" in str(item.title or "")]
        product_queries = [item for item in tasks if "产品" in str(item.title or "")]
        viewed = [item for item in tasks if item.attention_state != "result_unread"]
        execution_count = 0
        for item in tasks:
            execution_count += (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.task_id == item.task_id)
                .count()
            )
            execution_count += self._observed_task_execution_count(db, run, item)
        ok = bool(
            len(distinct_titles) >= 2
            and customer_queries
            and product_queries
            and len(viewed) >= 2
            and execution_count >= 2
        )
        refs = [{"type": "agent_task", "id": item.task_id} for item in tasks[:2]] if ok else []
        return (
            ok,
            "verification_passed" if ok else "second_task_not_ready",
            refs,
            {
                "distinct_readonly_task_count": len(distinct_titles),
                "customer_query_count": len(customer_queries),
                "product_query_count": len(product_queries),
                "viewed_result_count": len(viewed),
                "execution_count": execution_count,
            },
        )
