"""Lifecycle and evidence verification for the V2 hands-on tutorial."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.application.tutorial_v2.catalog import COURSE_BY_ID, COURSES, public_course
from app.db.base import Base
from app.db.models.accounting import JournalEntry
from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord, AgentTaskRecord
from app.db.models.approval import ApprovalRequest
from app.db.models.customer import Customer
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.db.models.product import Product
from app.db.models.receivable_allocation import ReceivableAllocation
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.tenant import Tenant
from app.db.models.tutorial import TutorialRun, TutorialStepEvidence, TutorialWorkspace
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.path_utils import get_app_data_dir

SALES_SENTENCE = "把 A 产品卖给客户B，10 个，单价 100，开票收款"
ACTIVE_RUN_STATUSES = {"active", "paused"}
SAFE_HINTS = {
    "prerequisite_incomplete": "请先完成前置课程。",
    "previous_step_incomplete": "请先验证通过上一必修步骤。",
    "tutorial_context_required": "请点击“进入教学空间”后再验证。",
    "customer_not_ready": "请确认教学空间中只有一条名称精确为“客户B”的客户。",
    "product_not_ready": "请确认“A 产品”的价格为 100、库存为 100，且只有一条。",
    "task_not_completed": "请先完成一项只读查询任务。",
    "task_evidence_not_ready": "请打开已完成任务的结果证据后重试。",
    "approval_not_ready": "请按精确句子提交并确认任务，且暂不要批准。",
    "sales_result_not_ready": "请批准申请后检查订单、库存、开票、收款和凭证。",
    "etl_preview_not_ready": "请先完成上传、字段映射和预览核对。",
    "etl_result_not_ready": "请确认写入并查看逐行导入结果。",
    "trace_view_required": "请先点击“去操作”打开当前步骤要求的页面。",
    "trace_result_not_ready": "当前页面对应的业务证据尚未完整。",
    "verification_passed": "验证通过，下一步已解锁。",
}

ValidationResult = tuple[
    bool,
    str,
    list[dict[str, Any]],
    dict[str, int | float | str],
]


def _now() -> datetime:
    return datetime.utcnow()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


class TutorialServiceError(RuntimeError):
    def __init__(self, code: str, hint: str, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.hint = hint
        self.status_code = status_code


class TutorialV2Service:
    """Source-tenant learning state plus shadow-tenant business verification."""

    def _owner(self, user: Any) -> tuple[int, int]:
        user_id = getattr(user, "id", None)
        source_tenant_id = getattr(user, "tenant_id", None)
        if user_id is None:
            raise TutorialServiceError("authentication_required", "请先登录。", 401)
        if source_tenant_id is None:
            raise TutorialServiceError(
                "source_tenant_required", "当前账号尚未加入企业，无法创建教学空间。", 409
            )
        return int(user_id), int(source_tenant_id)

    def _owned_run(self, db: Session, user: Any, run_id: str) -> TutorialRun:
        user_id, source_tenant_id = self._owner(user)
        run = (
            db.query(TutorialRun)
            .filter(
                TutorialRun.id == str(run_id),
                TutorialRun.user_id == user_id,
                TutorialRun.source_tenant_id == source_tenant_id,
            )
            .first()
        )
        if run is None:
            raise TutorialServiceError("tutorial_run_not_found", "未找到该课程运行。", 404)
        return cast(TutorialRun, run)

    def _active_workspace(self, db: Session, user: Any) -> TutorialWorkspace | None:
        user_id, source_tenant_id = self._owner(user)
        return cast(
            TutorialWorkspace | None,
            db.query(TutorialWorkspace)
            .filter(
                TutorialWorkspace.user_id == user_id,
                TutorialWorkspace.source_tenant_id == source_tenant_id,
                TutorialWorkspace.status == "active",
            )
            .order_by(TutorialWorkspace.generation.desc())
            .first(),
        )

    def _new_workspace(self, db: Session, user: Any) -> TutorialWorkspace:
        user_id, source_tenant_id = self._owner(user)
        generation = (
            int(
                db.query(func.max(TutorialWorkspace.generation))
                .filter(
                    TutorialWorkspace.user_id == user_id,
                    TutorialWorkspace.source_tenant_id == source_tenant_id,
                )
                .scalar()
                or 0
            )
            + 1
        )
        token = uuid.uuid4().hex[:12]
        tenant = Tenant(
            code=f"TUT-{source_tenant_id}-{user_id}-{token}",
            name=f"教学空间 · {user_id} · 第 {generation} 代",
            is_active=True,
            created_at=_now(),
        )
        db.add(tenant)
        db.flush()
        workspace = TutorialWorkspace(
            id=str(uuid.uuid4()),
            source_tenant_id=source_tenant_id,
            user_id=user_id,
            tutorial_tenant_id=int(tenant.id),
            active_key=f"{source_tenant_id}:{user_id}",
            generation=generation,
            status="active",
        )
        db.add(workspace)
        db.flush()
        return workspace

    def _workspace_or_create(self, db: Session, user: Any) -> TutorialWorkspace:
        return self._active_workspace(db, user) or self._new_workspace(db, user)

    def _completed_course_ids(self, db: Session, workspace: TutorialWorkspace) -> set[str]:
        return {
            str(row[0])
            for row in db.query(TutorialRun.course_id)
            .filter(
                TutorialRun.workspace_id == workspace.id,
                TutorialRun.status == "completed",
            )
            .all()
        }

    def _evidence_map(self, run: TutorialRun) -> dict[str, TutorialStepEvidence]:
        return {item.step_id: item for item in run.evidence}

    def _evidence_dto(self, evidence: TutorialStepEvidence) -> dict[str, Any]:
        return {
            "step_id": evidence.step_id,
            "status": evidence.status,
            "result_code": evidence.result_code,
            "entity_refs": _load_json(evidence.entity_refs_json, []),
            "counts": _load_json(evidence.counts_json, {}),
            "attempt_count": evidence.attempt_count,
            "verified_at": evidence.verified_at.isoformat() if evidence.verified_at else None,
        }

    def _run_dto(self, run: TutorialRun) -> dict[str, Any]:
        course = COURSE_BY_ID[run.course_id]
        evidence = self._evidence_map(run)
        steps: list[dict[str, Any]] = []
        for step in public_course(course)["steps"]:
            item = evidence.get(str(step["id"]))
            dto = dict(step)
            dto["evidence"] = self._evidence_dto(item) if item else None
            dto["status"] = item.status if item else "pending"
            steps.append(dto)
        passed = sum(step["status"] == "passed" for step in steps)
        return {
            "id": run.id,
            "workspace_id": run.workspace_id,
            "course_id": run.course_id,
            "version": run.version,
            "status": run.status,
            "current_step_id": run.current_step_id,
            "attempt_count": run.attempt_count,
            "progress": int((passed * 100) / max(1, len(steps))),
            "completed_steps": passed,
            "total_steps": len(steps),
            "generation": run.workspace.generation,
            "teaching_space": True,
            "steps": steps,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def list_courses(self, db: Session, user: Any) -> list[dict[str, Any]]:
        self.purge_expired_workspaces(db)
        workspace = self._active_workspace(db, user)
        completed = self._completed_course_ids(db, workspace) if workspace else set()
        latest: dict[str, TutorialRun] = {}
        if workspace:
            rows = (
                db.query(TutorialRun)
                .filter(TutorialRun.workspace_id == workspace.id)
                .order_by(TutorialRun.created_at.desc())
                .all()
            )
            for run in rows:
                latest.setdefault(run.course_id, run)
        result: list[dict[str, Any]] = []
        for course in COURSES:
            dto = public_course(course)
            prereqs = set(course["prerequisite_ids"])
            dto["locked"] = not prereqs.issubset(completed)
            dto["missing_prerequisite_ids"] = sorted(prereqs - completed)
            run = latest.get(str(course["id"]))
            dto["run"] = self._run_dto(run) if run else None
            dto["status"] = run.status if run else "not_started"
            dto["progress"] = self._run_dto(run)["progress"] if run else 0
            result.append(dto)
        return result

    def purge_expired_workspaces(self, db: Session, *, now: datetime | None = None) -> int:
        """Remove expired shadow business rows while retaining learning evidence."""
        cutoff = now or _now()
        workspaces = (
            db.query(TutorialWorkspace)
            .filter(
                TutorialWorkspace.status == "pending_cleanup",
                TutorialWorkspace.purge_after.is_not(None),
                TutorialWorkspace.purge_after <= cutoff,
            )
            .all()
        )
        for workspace in workspaces:
            tenant_id = int(workspace.tutorial_tenant_id)
            for table in reversed(Base.metadata.sorted_tables):
                if "tenant_id" not in table.c:
                    continue
                db.execute(table.delete().where(table.c.tenant_id == tenant_id))
            upload_root = (Path(get_app_data_dir()).resolve() / "etl" / "uploads").resolve()
            tenant_upload_root = (upload_root / str(tenant_id)).resolve()
            if upload_root in tenant_upload_root.parents and tenant_upload_root.is_dir():
                shutil.rmtree(tenant_upload_root)
            workspace.status = "purged"
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant is not None:
                tenant.is_active = False
        if workspaces:
            db.commit()
        return len(workspaces)

    def start_run(self, db: Session, user: Any, course_id: str) -> TutorialRun:
        course = COURSE_BY_ID.get(str(course_id))
        if course is None:
            raise TutorialServiceError("course_not_found", "未找到该课程。", 404)
        workspace = self._workspace_or_create(db, user)
        missing = set(course["prerequisite_ids"]) - self._completed_course_ids(db, workspace)
        if missing:
            raise TutorialServiceError(
                "prerequisite_incomplete", SAFE_HINTS["prerequisite_incomplete"], 409
            )
        user_id, source_tenant_id = self._owner(user)
        current = (
            db.query(TutorialRun)
            .filter(
                TutorialRun.workspace_id == workspace.id,
                TutorialRun.course_id == str(course_id),
                TutorialRun.status.in_(["active", "paused"]),
            )
            .order_by(TutorialRun.created_at.desc())
            .first()
        )
        paused_any = False
        for active in (
            db.query(TutorialRun)
            .filter(
                TutorialRun.source_tenant_id == source_tenant_id,
                TutorialRun.user_id == user_id,
                TutorialRun.status == "active",
            )
            .all()
        ):
            if current is None or active.id != current.id:
                active.status = "paused"
                active.active_key = None
                active.last_left_at = _now()
                paused_any = True
        if paused_any:
            db.flush()
        if current is not None:
            current.status = "active"
            current.active_key = f"{source_tenant_id}:{user_id}"
            current.last_entered_at = _now()
            db.commit()
            db.refresh(current)
            return cast(TutorialRun, current)
        step_ids = [str(step["id"]) for step in course["steps"]]
        run = TutorialRun(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            source_tenant_id=source_tenant_id,
            user_id=user_id,
            course_id=str(course_id),
            version=int(course["version"]),
            status="active",
            active_key=f"{source_tenant_id}:{user_id}",
            current_step_id=step_ids[0],
            last_entered_at=_now(),
        )
        db.add(run)
        db.flush()
        for step_id in step_ids:
            db.add(TutorialStepEvidence(run_id=run.id, step_id=step_id))
        db.commit()
        db.refresh(run)
        return run

    def current_run(
        self, db: Session, user: Any, *, preferred_run_id: str | None = None
    ) -> TutorialRun | None:
        user_id, source_tenant_id = self._owner(user)
        if preferred_run_id:
            preferred = (
                db.query(TutorialRun)
                .filter(
                    TutorialRun.id == str(preferred_run_id),
                    TutorialRun.user_id == user_id,
                    TutorialRun.source_tenant_id == source_tenant_id,
                    TutorialRun.status.in_(["active", "paused", "completed"]),
                )
                .first()
            )
            if preferred is not None:
                return cast(TutorialRun, preferred)
        return cast(
            TutorialRun | None,
            db.query(TutorialRun)
            .filter(
                TutorialRun.user_id == user_id,
                TutorialRun.source_tenant_id == source_tenant_id,
                TutorialRun.status.in_(["active", "paused"]),
            )
            .order_by(
                (TutorialRun.status == "active").desc(),
                TutorialRun.updated_at.desc(),
            )
            .first(),
        )

    def enter_run(self, db: Session, user: Any, run_id: str) -> TutorialRun:
        run = self._owned_run(db, user, run_id)
        if run.status == "reset":
            raise TutorialServiceError("tutorial_run_retired", "该教学代次已重置。", 409)
        user_id, source_tenant_id = self._owner(user)
        paused_any = False
        for active in (
            db.query(TutorialRun)
            .filter(
                TutorialRun.user_id == user_id,
                TutorialRun.source_tenant_id == source_tenant_id,
                TutorialRun.status == "active",
                TutorialRun.id != run.id,
            )
            .all()
        ):
            active.status = "paused"
            active.active_key = None
            active.last_left_at = _now()
            paused_any = True
        if paused_any:
            db.flush()
        if run.status != "completed":
            run.status = "active"
            run.active_key = f"{source_tenant_id}:{user_id}"
        run.last_entered_at = _now()
        db.commit()
        db.refresh(run)
        return run

    def leave_run(self, db: Session, user: Any, run_id: str) -> TutorialRun:
        run = self._owned_run(db, user, run_id)
        if run.status == "active":
            run.status = "paused"
            run.active_key = None
        run.last_left_at = _now()
        db.commit()
        db.refresh(run)
        return run

    def reset_run(self, db: Session, user: Any, run_id: str) -> TutorialRun:
        run = self._owned_run(db, user, run_id)
        workspace = run.workspace
        now = _now()
        workspace.status = "pending_cleanup"
        workspace.active_key = None
        workspace.retired_at = now
        workspace.purge_after = now + timedelta(days=7)
        tenant = db.query(Tenant).filter(Tenant.id == workspace.tutorial_tenant_id).first()
        if tenant is not None:
            tenant.is_active = False
        for old_run in workspace.runs:
            if old_run.status != "completed":
                old_run.status = "reset"
                old_run.active_key = None
                old_run.last_left_at = now
        course_id = run.course_id
        db.commit()
        return self.start_run(db, user, course_id)

    def _step_definition(self, run: TutorialRun, step_id: str) -> tuple[int, dict[str, Any]]:
        steps = COURSE_BY_ID[run.course_id]["steps"]
        for index, step in enumerate(steps):
            if str(step["id"]) == str(step_id):
                return index, step
        raise TutorialServiceError("tutorial_step_not_found", "未找到该课程步骤。", 404)

    def verify_step(
        self,
        db: Session,
        user: Any,
        run_id: str,
        step_id: str,
        *,
        cookie_run_id: str | None,
        context: dict[str, Any] | None = None,
    ) -> tuple[TutorialRun, TutorialStepEvidence]:
        run = self._owned_run(db, user, run_id)
        if str(cookie_run_id or "") != run.id:
            raise TutorialServiceError(
                "tutorial_context_required", SAFE_HINTS["tutorial_context_required"], 409
            )
        if run.status not in ACTIVE_RUN_STATUSES:
            raise TutorialServiceError("tutorial_run_not_active", "该课程当前不可验证。", 409)
        index, step = self._step_definition(run, step_id)
        evidence = (
            db.query(TutorialStepEvidence)
            .filter(
                TutorialStepEvidence.run_id == run.id,
                TutorialStepEvidence.step_id == str(step_id),
            )
            .one()
        )
        if evidence.status == "passed":
            return run, evidence
        previous = COURSE_BY_ID[run.course_id]["steps"][:index]
        evidence_by_step = self._evidence_map(run)
        if any(
            bool(item.get("required", True))
            and evidence_by_step.get(str(item["id"]), None) is not None
            and evidence_by_step[str(item["id"])].status != "passed"
            for item in previous
        ):
            raise TutorialServiceError(
                "previous_step_incomplete", SAFE_HINTS["previous_step_incomplete"], 409
            )
        run.attempt_count += 1
        evidence.attempt_count += 1
        ok, code, refs, counts = self._run_verifier(
            db,
            run,
            str(step["verifier"]),
            context or {},
        )
        evidence.status = "passed" if ok else "failed"
        evidence.result_code = code
        evidence.entity_refs_json = _json(refs)
        evidence.counts_json = _json(counts)
        evidence.verified_at = _now()
        if ok:
            steps = COURSE_BY_ID[run.course_id]["steps"]
            if index + 1 < len(steps):
                run.current_step_id = str(steps[index + 1]["id"])
            else:
                run.status = "completed"
                run.active_key = None
                run.completed_at = _now()
        else:
            run.current_step_id = str(step_id)
        db.commit()
        db.refresh(run)
        db.refresh(evidence)
        return run, evidence

    def _run_verifier(
        self,
        db: Session,
        run: TutorialRun,
        verifier: str,
        context: dict[str, Any],
    ) -> tuple[bool, str, list[dict[str, Any]], dict[str, int | float | str]]:
        validators = {
            "exact_customer": self._verify_customer,
            "exact_product": self._verify_product,
            "completed_readonly_task": self._verify_task,
            "task_evidence_viewed": self._verify_task_evidence_viewed,
            "sales_waiting_approval": self._verify_sales_waiting,
            "sales_closed_loop": self._verify_sales_closed_loop,
            "etl_preview": self._verify_etl_preview,
            "etl_completed": self._verify_etl_completed,
            "trace_task": self._verify_trace_task,
            "trace_approval": self._verify_trace_approval,
            "trace_order_inventory": self._verify_trace_order,
            "trace_finance": self._verify_trace_finance,
            "trace_import": self._verify_trace_import,
        }
        validator = validators.get(verifier)
        if validator is None:
            return False, "verifier_unavailable", [], {}
        return cast(ValidationResult, validator(db, run, context))

    def _verify_customer(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        with tenant_scope(run.workspace.tutorial_tenant_id):
            rows = db.query(Customer).filter(Customer.customer_name == "客户B").all()
        ok = len(rows) == 1
        return (
            ok,
            "verification_passed" if ok else "customer_not_ready",
            [{"type": "customer", "id": rows[0].id}] if ok else [],
            {"customer_count": len(rows)},
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
            run_record = (
                db.query(AgentRunRecord)
                .filter(
                    AgentRunRecord.run_id == tasks[0].active_run_id,
                    AgentRunRecord.user_id == str(run.user_id),
                    AgentRunRecord.status == "completed",
                )
                .first()
            )
            payload = _load_json(run_record.payload_json, {}) if run_record else {}
            steps = payload.get("steps") if isinstance(payload, dict) else None
            calls = payload.get("tool_calls") if isinstance(payload, dict) else None
            final_output = payload.get("final_output") if isinstance(payload, dict) else None
            has_completed_step = isinstance(steps, list) and any(
                isinstance(item, dict) and item.get("status") == "completed" for item in steps
            )
            has_completed_call = isinstance(calls, list) and any(
                isinstance(item, dict) and item.get("status") == "completed" for item in calls
            )
            has_result = isinstance(final_output, dict) and bool(final_output)
            observed_executions = int(has_completed_step and has_completed_call and has_result)
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

    def _sales_entities(self, db: Session, run: TutorialRun) -> dict[str, Any]:
        tenant_id = run.workspace.tutorial_tenant_id
        with tenant_scope(tenant_id):
            customer_rows = db.query(Customer).filter(Customer.customer_name == "客户B").all()
            product_rows = db.query(Product).filter(Product.name == "A 产品").all()
            orders = db.query(SalesOrder).filter(SalesOrder.customer_name == "客户B").all()
            items = []
            allocations = []
            entries = []
            if len(orders) == 1:
                items = (
                    db.query(SalesOrderItem).filter(SalesOrderItem.order_id == orders[0].id).all()
                )
                allocations = (
                    db.query(ReceivableAllocation)
                    .filter(ReceivableAllocation.sales_order_id == orders[0].id)
                    .all()
                )
                entries = (
                    db.query(JournalEntry)
                    .filter(
                        (JournalEntry.reference_type == "sale")
                        & (JournalEntry.reference_id == orders[0].id)
                        | JournalEntry.id.in_(
                            [row.journal_entry_id for row in allocations if row.journal_entry_id]
                        )
                    )
                    .all()
                )
        return {
            "customers": customer_rows,
            "products": product_rows,
            "orders": orders,
            "items": items,
            "allocations": allocations,
            "entries": entries,
        }

    def _verify_sales_waiting(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        tenant_id = run.workspace.tutorial_tenant_id
        with tenant_scope(tenant_id):
            approvals = (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.status.in_(["pending", "in_progress"]))
                .all()
            )
            matching = [
                item
                for item in approvals
                if SALES_SENTENCE in str(item.business_data or "")
                or SALES_SENTENCE in str(item.description or "")
                or SALES_SENTENCE in str(item.title or "")
            ]
            order_count = db.query(SalesOrder).filter(SalesOrder.customer_name == "客户B").count()
            item_count = db.query(SalesOrderItem).count()
            allocation_count = db.query(ReceivableAllocation).count()
            voucher_count = db.query(JournalEntry).count()
            products = db.query(Product).filter(Product.name == "A 产品").all()
        inventory = int(products[0].quantity or 0) if len(products) == 1 else -1
        ok = (
            len(matching) == 1
            and order_count == 0
            and item_count == 0
            and allocation_count == 0
            and voucher_count == 0
            and inventory == 100
        )
        return (
            ok,
            "verification_passed" if ok else "approval_not_ready",
            [{"type": "approval_request", "id": matching[0].id}] if ok else [],
            {
                "pending_approval_count": len(matching),
                "sales_order_count": order_count,
                "sales_order_item_count": item_count,
                "allocation_count": allocation_count,
                "journal_entry_count": voucher_count,
                "inventory": inventory,
            },
        )

    def _closed_loop_result(self, db: Session, run: TutorialRun):
        data = self._sales_entities(db, run)
        products = data["products"]
        orders = data["orders"]
        items = data["items"]
        allocations = data["allocations"]
        entries = data["entries"]
        order = orders[0] if len(orders) == 1 else None
        product = products[0] if len(products) == 1 else None
        item_ok = (
            len(items) == 1
            and Decimal(str(items[0].quantity or 0)) == Decimal("10")
            and Decimal(str(items[0].unit_price or 0)) == Decimal("100")
        )
        allocation_ok = (
            len(allocations) == 1
            and Decimal(str(allocations[0].allocated_amount or 0)) == Decimal("1000")
            and allocations[0].status == "paid"
        )
        entries_ok = len(entries) >= 2 and all(
            entry.status == "posted"
            and Decimal(str(entry.debit_total or 0)) == Decimal(str(entry.credit_total or 0))
            for entry in entries
        )
        ok = bool(
            len(data["customers"]) == 1
            and product is not None
            and int(product.quantity or 0) == 90
            and order is not None
            and order.invoice_status == "invoiced"
            and order.payment_state == "paid"
            and Decimal(str(order.total_amount or 0)) == Decimal("1000")
            and item_ok
            and allocation_ok
            and entries_ok
        )
        refs: list[dict[str, Any]] = []
        if ok and order is not None and product is not None:
            refs = [
                {"type": "sales_order", "id": order.id},
                {"type": "sales_order_item", "id": items[0].id},
                {"type": "product", "id": product.id},
                {"type": "receivable_allocation", "id": allocations[0].id},
                *[
                    {
                        "type": "journal_entry",
                        "id": entry.id,
                        "role": "invoice" if entry.reference_type == "sale" else "payment",
                    }
                    for entry in entries
                ],
            ]
        invoice_vouchers = sum(entry.reference_type == "sale" for entry in entries)
        payment_vouchers = sum(entry.reference_type == "payment" for entry in entries)
        counts = {
            "sales_order_count": len(orders),
            "sales_order_item_count": len(items),
            "inventory": int(product.quantity or 0) if product else -1,
            "allocation_count": len(allocations),
            "journal_entry_count": len(entries),
            "invoice_voucher_count": invoice_vouchers,
            "payment_voucher_count": payment_vouchers,
            "balanced_journal_entry_count": sum(
                Decimal(str(entry.debit_total or 0)) == Decimal(str(entry.credit_total or 0))
                for entry in entries
            ),
        }
        return ok, refs, counts

    def _verify_sales_closed_loop(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        ok, refs, counts = self._closed_loop_result(db, run)
        return ok, "verification_passed" if ok else "sales_result_not_ready", refs, counts

    def _etl_rows(self, db: Session, run: TutorialRun) -> list[EtlRun]:
        with tenant_scope(run.workspace.tutorial_tenant_id):
            return cast(
                list[EtlRun],
                db.query(EtlRun)
                .join(EtlUpload, EtlUpload.id == EtlRun.upload_id)
                .filter(EtlRun.owner_user_id == run.user_id)
                .filter(EtlUpload.file_name.like("xcagi-tutorial-business-import%"))
                .order_by(EtlRun.created_at.desc())
                .all(),
            )

    def _verify_etl_preview(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        runs = self._etl_rows(db, run)
        previews = [item for item in runs if item.status in {"preview_ready", "completed"}]
        row_count = 0
        if previews:
            with tenant_scope(run.workspace.tutorial_tenant_id):
                row_count = db.query(EtlRunRow).filter(EtlRunRow.run_id == previews[0].id).count()
        ok = bool(previews) and row_count > 0
        return (
            ok,
            "verification_passed" if ok else "etl_preview_not_ready",
            [{"type": "etl_run", "id": previews[0].id}] if ok else [],
            {"preview_run_count": len(previews), "preview_row_count": row_count},
        )

    def _verify_etl_completed(self, db: Session, run: TutorialRun, _context: dict[str, Any]):
        runs = self._etl_rows(db, run)
        completed = [item for item in runs if item.status == "completed"]
        successful = 0
        referenced = 0
        error_rows = 0
        if completed:
            with tenant_scope(run.workspace.tutorial_tenant_id):
                rows = db.query(EtlRunRow).filter(EtlRunRow.run_id == completed[0].id).all()
            successful = sum(row.execution_status == "success" for row in rows)
            referenced = sum(bool(row.match_ref or _load_json(row.after_json, {})) for row in rows)
            error_rows = sum(row.execution_status == "failed" for row in rows)
        ok = bool(completed) and successful > 0 and referenced > 0
        return (
            ok,
            "verification_passed" if ok else "etl_result_not_ready",
            [{"type": "etl_run", "id": completed[0].id}] if ok else [],
            {
                "completed_run_count": len(completed),
                "successful_row_count": successful,
                "referenced_row_count": referenced,
                "error_row_count": error_rows,
            },
        )

    def _visited(self, context: dict[str, Any], expected: set[str]) -> bool:
        return str(context.get("visited_route") or "") in expected

    def _verify_trace_task(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"chat"}):
            return False, "trace_view_required", [], {}
        tasks = (
            db.query(AgentTaskRecord)
            .filter(
                AgentTaskRecord.tenant_id == str(run.workspace.tutorial_tenant_id),
                AgentTaskRecord.user_id == str(run.user_id),
                AgentTaskRecord.status == "completed",
            )
            .order_by(AgentTaskRecord.updated_at.desc())
            .all()
        )
        matching = [
            task
            for task in tasks
            if SALES_SENTENCE in str(task.title or "")
            or SALES_SENTENCE in str(task.metadata_json or "")
        ]
        execution_count = 0
        if len(matching) == 1:
            execution_count = (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.task_id == matching[0].task_id)
                .count()
            )
        ok = len(matching) == 1 and execution_count > 0
        return (
            ok,
            "verification_passed" if ok else "trace_result_not_ready",
            [{"type": "agent_task", "id": matching[0].task_id}] if ok else [],
            {"sales_task_count": len(matching), "execution_count": execution_count},
        )

    def _verify_trace_approval(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"approval-workspace"}):
            return False, "trace_view_required", [], {}
        with tenant_scope(run.workspace.tutorial_tenant_id):
            rows = db.query(ApprovalRequest).filter(ApprovalRequest.status == "approved").all()
        matching = [row for row in rows if SALES_SENTENCE in str(row.business_data or "")]
        ok = len(matching) == 1
        return (
            ok,
            "verification_passed" if ok else "trace_result_not_ready",
            [{"type": "approval_request", "id": matching[0].id}] if ok else [],
            {"approved_request_count": len(matching)},
        )

    def _verify_trace_order(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"inventory", "orders"}):
            return False, "trace_view_required", [], {}
        ok, refs, counts = self._closed_loop_result(db, run)
        return ok, "verification_passed" if ok else "trace_result_not_ready", refs, counts

    def _verify_trace_finance(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"kitten-finance", "orders"}):
            return False, "trace_view_required", [], {}
        ok, refs, counts = self._closed_loop_result(db, run)
        return ok, "verification_passed" if ok else "trace_result_not_ready", refs, counts

    def _verify_trace_import(self, db: Session, run: TutorialRun, context: dict[str, Any]):
        if not self._visited(context, {"business-docking"}):
            return False, "trace_view_required", [], {}
        return self._verify_etl_completed(db, run, context)

    def reports(self, db: Session, user: Any) -> list[dict[str, Any]]:
        _user_id, source_tenant_id = self._owner(user)
        role = str(getattr(user, "role", "") or "").strip().lower()
        tier = str(getattr(user, "tier", "") or "").strip().lower()
        if role not in {"owner", "admin", "superadmin", "super_admin"} and tier != "admin":
            raise TutorialServiceError("tutorial_report_forbidden", "仅企业管理员可查看。", 403)
        rows = (
            db.query(TutorialRun)
            .filter(TutorialRun.source_tenant_id == source_tenant_id)
            .order_by(TutorialRun.updated_at.desc())
            .all()
        )
        return [
            {
                "user_id": row.user_id,
                "course_id": row.course_id,
                "status": row.status,
                "progress": self._run_dto(row)["progress"],
                "attempt_count": row.attempt_count,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "evidence_summary": [
                    {
                        "step_id": item.step_id,
                        "status": item.status,
                        "result_code": item.result_code,
                    }
                    for item in row.evidence
                ],
            }
            for row in rows
        ]

    def run_dto(self, run: TutorialRun) -> dict[str, Any]:
        return self._run_dto(run)

    def safe_hint(self, code: str) -> str:
        return SAFE_HINTS.get(code, "请按课程提示检查后重试。")


__all__ = [
    "SAFE_HINTS",
    "SALES_SENTENCE",
    "TutorialServiceError",
    "TutorialV2Service",
]
