"""Explicit owner consent for a fixed recurring operation, expiry and run quota."""

import hashlib
import json
import uuid
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.schedule_repository import ScheduleRepository
from app.application.agent_orchestrator.task_schedule import normalize_scheduled_at
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.db.models.agent_schedule import AgentScheduleRecord as Schedule
from app.db.models.schedule_authorization import ScheduleAuthorizationRecord as Grant
from app.db.models.schedule_authorization import ScheduleAuthorizationUseRecord as Use
from app.infrastructure.auth.agent_principal import AgentPrincipal


def scope_hash(payload: dict[str, Any]) -> str:
    check = validate_tool_call(payload["tool_id"], payload["action"], payload["params"])
    if not check.ok or check.spec is None:
        raise ValueError("周期操作当前不可用")
    scope = {
        "payload": payload,
        "risk": check.spec.risk,
        "permission": check.spec.permission,
        "input_schema": check.spec.input_schema,
    }
    return hashlib.sha256(
        json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def matches_run(row: Schedule, run: AgentRun) -> bool:
    payload = json.loads(row.payload_json)
    context = run.metadata.get("runtime_context") or {}
    return bool(
        run.user_id == row.user_id
        and str(context.get("tenant_id") or "") == row.tenant_id
        and len(run.steps) == 1
        and run.steps[0].tool_id == payload["tool_id"]
        and run.steps[0].action == payload["action"]
        and run.steps[0].params == payload["params"]
    )


class ScheduleAuthorizations:
    def __init__(self, repository: ScheduleRepository | None = None):
        self.repository = repository or ScheduleRepository()

    def grant(
        self,
        schedule_id: str,
        principal: AgentPrincipal,
        *,
        expires_at: str,
        max_runs: int,
        expected_scope_hash: str,
    ) -> dict[str, Any]:
        expiry = normalize_scheduled_at(expires_at)
        now = utc_now_iso()
        if not expiry or expiry <= now or type(max_runs) is not int or not 1 <= max_runs <= 1000000:
            raise ValueError("授权必须指定未来到期时间和 1 到 1000000 次任务上限")
        with self.repository.session() as db:
            # Serialize replacement grants on the schedule row on both SQLite
            # and PostgreSQL, including when no previous grant exists.
            db.query(Schedule).filter_by(
                schedule_id=schedule_id, user_id=principal.user_id, tenant_id=principal.tenant_id
            ).update({"updated_at": now}, synchronize_session=False)
            row = (
                db.query(Schedule)
                .filter_by(
                    schedule_id=schedule_id,
                    user_id=principal.user_id,
                    tenant_id=principal.tenant_id,
                )
                .one_or_none()
            )
            if row is None or row.state == "cancelled":
                raise ValueError("计划不存在或已取消")
            digest = scope_hash(json.loads(row.payload_json))
            if digest != expected_scope_hash:
                raise ValueError("计划范围已变化，请重新查看后授权")
            db.query(Grant).filter_by(schedule_id=schedule_id, state="active").update(
                {"state": "revoked"}
            )
            grant = Grant(
                authorization_id=uuid.uuid4().hex,
                schedule_id=schedule_id,
                user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                state="active",
                scope_hash=digest,
                expires_at=expiry,
                max_runs=max_runs,
                reserved_runs=0,
                created_at=now,
            )
            db.add(grant)
            db.flush()
            return self._public(grant)

    @staticmethod
    def _public(grant: Grant) -> dict[str, Any]:
        state = grant.state
        if state == "active" and grant.expires_at <= utc_now_iso():
            state = "expired"
        elif state == "active" and grant.reserved_runs >= grant.max_runs:
            state = "exhausted"
        return {
            "authorization_id": grant.authorization_id,
            "state": state,
            "expires_at": grant.expires_at,
            "max_runs": grant.max_runs,
            "reserved_runs": grant.reserved_runs,
            "scope_hash": grant.scope_hash,
        }

    def list_active(self, principal: AgentPrincipal) -> dict[str, dict[str, Any]]:
        with self.repository.session() as db:
            rows = (
                db.query(Grant)
                .filter_by(user_id=principal.user_id, tenant_id=principal.tenant_id, state="active")
                .all()
            )
            return {row.schedule_id: self._public(row) for row in rows}

    def inspect(self, schedule_id: str, principal: AgentPrincipal) -> dict[str, Any]:
        with self.repository.session() as db:
            row = (
                db.query(Schedule)
                .filter_by(
                    schedule_id=schedule_id,
                    user_id=principal.user_id,
                    tenant_id=principal.tenant_id,
                )
                .one_or_none()
            )
            if row is None:
                raise ValueError("计划不存在")
            grant = (
                db.query(Grant)
                .filter_by(schedule_id=schedule_id, state="active")
                .order_by(Grant.created_at.desc())
                .first()
            )
            payload = json.loads(row.payload_json)
            return {
                "scope_hash": scope_hash(payload),
                "operation": payload,
                "authorization": self._public(grant) if grant else None,
            }

    def revoke(self, schedule_id: str, principal: AgentPrincipal) -> bool:
        with self.repository.session() as db:
            return bool(
                db.query(Grant)
                .filter_by(
                    schedule_id=schedule_id,
                    user_id=principal.user_id,
                    tenant_id=principal.tenant_id,
                    state="active",
                )
                .update({"state": "revoked"}, synchronize_session=False)
            )

    def reserve(self, schedule_id: str, run: AgentRun, *, now: str | None = None) -> str:
        current = normalize_scheduled_at(now or utc_now_iso())
        with self.repository.session() as db:
            row = db.get(Schedule, schedule_id)
            if row is None or row.state != "active" or not matches_run(row, run):
                return ""
            digest = scope_hash(json.loads(row.payload_json))
            existing = db.query(Use).filter_by(run_id=run.run_id).all()
            for receipt in existing:
                if self._valid(db, receipt.authorization_id, row, digest, current):
                    return receipt.authorization_id
            grants = (
                db.query(Grant)
                .filter_by(schedule_id=schedule_id, state="active", scope_hash=digest)
                .all()
            )
            for grant in grants:
                updated = (
                    db.query(Grant)
                    .filter(
                        Grant.authorization_id == grant.authorization_id,
                        Grant.state == "active",
                        Grant.expires_at > current,
                        Grant.reserved_runs < Grant.max_runs,
                    )
                    .update(
                        {Grant.reserved_runs: Grant.reserved_runs + 1}, synchronize_session=False
                    )
                )
                if updated == 1:
                    db.add(
                        Use(
                            run_id=run.run_id,
                            authorization_id=grant.authorization_id,
                            created_at=current,
                        )
                    )
                    return grant.authorization_id
        return ""

    @staticmethod
    def _valid(db, grant_id: str, row: Schedule, digest: str, current: str) -> bool:
        grant = db.get(Grant, grant_id)
        return bool(
            grant
            and grant.state == "active"
            and grant.expires_at > current
            and grant.schedule_id == row.schedule_id
            and grant.scope_hash == digest
            and grant.user_id == row.user_id
            and grant.tenant_id == row.tenant_id
        )

    def valid_for_execution(self, run: AgentRun, *, now: str | None = None) -> bool:
        reference = run.metadata.get("schedule_authorization")
        if not isinstance(reference, dict):
            return False
        with self.repository.session() as db:
            row = db.get(Schedule, reference.get("schedule_id"))
            receipt = db.get(Use, (run.run_id, reference.get("authorization_id")))
            if row is None or row.state != "active" or receipt is None or not matches_run(row, run):
                return False
            if receipt.authorization_id != reference.get("authorization_id"):
                return False
            from app.db.models.user import User

            if not run.user_id.isdigit():
                return False
            actor = db.get(User, int(run.user_id))
            if actor is None or not actor.is_active or str(actor.tenant_id or "") != row.tenant_id:
                return False
            context = run.metadata.get("runtime_context") or {}
            if context.get("mod_scope") is not None:
                from app.application.agent_orchestrator.task_mod_scope import (
                    validate_task_mod_scope,
                )

                validate_task_mod_scope(context["mod_scope"], run.user_id, row.tenant_id)
            return self._valid(
                db,
                receipt.authorization_id,
                row,
                scope_hash(json.loads(row.payload_json)),
                normalize_scheduled_at(now or utc_now_iso()),
            )


def check_scheduled_dispatch(run: AgentRun) -> bool:
    if "schedule_authorization" not in run.metadata:
        return True
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        return ScheduleAuthorizations().valid_for_execution(run)
    except RECOVERABLE_ERRORS:
        return False
