"""Lifecycle and evidence verification for the V2 hands-on tutorial."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from app.application.tutorial_v2.business_verifiers import TutorialBusinessVerifierMixin
from app.application.tutorial_v2.catalog import COURSE_BY_ID, COURSES, public_course
from app.application.tutorial_v2.common import (
    ACTIVE_RUN_STATUSES,
    SAFE_HINTS,
    SALES_SENTENCE,
    TutorialServiceError,
)
from app.application.tutorial_v2.common import (
    json_dump as _json,
)
from app.application.tutorial_v2.common import (
    json_load as _load_json,
)
from app.application.tutorial_v2.common import (
    utcnow as _now,
)
from app.application.tutorial_v2.master_task_verifiers import TutorialMasterTaskVerifierMixin
from app.application.tutorial_v2.workspace import TutorialWorkspaceMixin
from app.db.base import Base
from app.db.models.tenant import Tenant
from app.db.models.tutorial import TutorialRun, TutorialStepEvidence, TutorialWorkspace
from app.utils.path_io.path_utils import get_app_data_dir

ValidationResult = tuple[
    bool,
    str,
    list[dict[str, Any]],
    dict[str, int | float | str],
]


class TutorialV2Service(
    TutorialWorkspaceMixin,
    TutorialMasterTaskVerifierMixin,
    TutorialBusinessVerifierMixin,
):
    """Source-tenant learning state plus shadow-tenant business verification."""

    def _is_current_version(self, run: TutorialRun) -> bool:
        course = COURSE_BY_ID.get(str(run.course_id))
        return course is not None and int(run.version) == int(course["version"])

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
                if self._is_current_version(run):
                    latest.setdefault(run.course_id, run)
        result: list[dict[str, Any]] = []
        for course in COURSES:
            dto = public_course(course)
            prereqs = set(course["prerequisite_ids"])
            dto["locked"] = not prereqs.issubset(completed)
            dto["missing_prerequisite_ids"] = sorted(prereqs - completed)
            latest_run = latest.get(str(course["id"]))
            dto["run"] = self._run_dto(latest_run) if latest_run else None
            dto["status"] = latest_run.status if latest_run else "not_started"
            dto["progress"] = self._run_dto(latest_run)["progress"] if latest_run else 0
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
        self._ensure_teaching_warehouse(db, workspace)
        missing = set(course["prerequisite_ids"]) - self._completed_course_ids(db, workspace)
        if missing:
            raise TutorialServiceError(
                "prerequisite_incomplete", SAFE_HINTS["prerequisite_incomplete"], 409
            )
        if str(course_id) == "sales-to-cash":
            self._ensure_teaching_inventory(db, workspace)
        user_id, source_tenant_id = self._owner(user)
        current = (
            db.query(TutorialRun)
            .filter(
                TutorialRun.workspace_id == workspace.id,
                TutorialRun.course_id == str(course_id),
                TutorialRun.version == int(course["version"]),
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
                if self._is_current_version(preferred):
                    return cast(TutorialRun, preferred)
        candidates = (
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
            .all()
        )
        return next((row for row in candidates if self._is_current_version(row)), None)

    def enter_run(self, db: Session, user: Any, run_id: str) -> TutorialRun:
        run = self._owned_run(db, user, run_id)
        if not self._is_current_version(run):
            raise TutorialServiceError(
                "tutorial_run_outdated",
                "教程内容已升级，请从课程目录开始新版课程；旧证据仍会保留。",
                409,
            )
        if run.status == "reset":
            raise TutorialServiceError("tutorial_run_retired", "该教学代次已重置。", 409)
        self._ensure_teaching_warehouse(db, run.workspace)
        if run.course_id == "sales-to-cash":
            self._ensure_teaching_inventory(db, run.workspace)
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
        prerequisite_ids = list(COURSE_BY_ID[course_id]["prerequisite_ids"])
        restart_course_id = prerequisite_ids[0] if prerequisite_ids else course_id
        db.commit()
        return self.start_run(db, user, restart_course_id)

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
        if not self._is_current_version(run):
            raise TutorialServiceError(
                "tutorial_run_outdated",
                "教程内容已升级，请从课程目录开始新版课程；旧证据仍会保留。",
                409,
            )
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
            "second_readonly_task": self._verify_second_readonly_task,
            "sales_waiting_approval": self._verify_sales_waiting,
            "sales_approval_reviewed": self._verify_sales_approval_reviewed,
            "sales_closed_loop": self._verify_sales_closed_loop,
            "etl_preview": self._verify_etl_preview,
            "etl_completed": self._verify_etl_completed,
            "trace_task": self._verify_trace_task,
            "trace_approval": self._verify_trace_approval,
            "trace_order": self._verify_trace_order,
            "trace_inventory": self._verify_trace_inventory,
            "trace_invoice": self._verify_trace_finance,
            "trace_receipt": self._verify_trace_finance,
            "trace_vouchers": self._verify_trace_finance,
            "trace_import": self._verify_trace_import,
        }
        validator = validators.get(verifier)
        if validator is None:
            return False, "verifier_unavailable", [], {}
        return cast(ValidationResult, validator(db, run, context))

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
