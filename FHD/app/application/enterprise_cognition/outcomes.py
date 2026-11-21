"""Join Business Harness receipts to authoritative before/after observations.

This is product binding glue, not a second execution or causal inference engine.
The existing run repository freezes a measurement; MemoryV2 stores its governed
candidate. Observing a change after an action does not establish causation.
"""

from __future__ import annotations

import copy
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.application.agent_orchestrator.approval_grant import _params_hash
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.business_harness import ensure_terminal_business_result
from app.application.agent_orchestrator.run_audit_scope import _result_scope
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import get_agent_run_repository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.agent_task_context import scoped_personal_memory_id
from app.application.memory_v2_facade import get_user_memory_service
from app.domain.enterprise_cognition.outcome_evidence import (
    OutcomeEvidenceError,
    authority_sample,
)
from app.domain.enterprise_cognition.outcome_evidence import (
    metric_number as _number,
)
from app.domain.enterprise_cognition.outcome_evidence import (
    observation_time as _time,
)
from app.domain.task_lifecycle.results import (
    execution_result_error,
    execution_result_requires_reconciliation,
)
from app.utils.operational_errors import INFRA_TRANSIENT, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_EVENT = "enterprise.outcome_observed"


def _unknown(reason: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "observation_verified": False,
        "business_success": None,
        "attribution": "unproven",
        "reason_code": reason,
        "memory_status": "not_written",
    }


def _execution_evidence(run: AgentRun, bound_at: datetime) -> tuple[dict[str, Any], list[dict]]:
    result = ensure_terminal_business_result(run)
    if (
        run.status != "completed"
        or result.get("status") != "completed"
        or result.get("success") is not True
        or not result.get("task_id")
        or not run.steps
        or run.metadata.get("non_retryable")
        or (run.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required"
    ):
        raise OutcomeEvidenceError("execution_not_verified")
    approvals = {
        event.data.get("step_id"): event
        for event in run.events
        if event.event_type == "step.approved" and event.data.get("approved_by")
    }
    calls = []
    binding = (run.metadata.get("runtime_context") or {}).get("enterprise_cognition") or {}
    goal = binding.get("goal") or {}
    action_bindings = {item.get("node_id"): item for item in binding.get("action_bindings", [])}
    required = ((run.metadata.get("plan") or {}).get("metadata") or {}).get(
        "approval_required_node_ids", []
    )
    for step in run.steps:
        from app.application.agent_orchestrator.clarification import control_verification_report

        if control_verification_report(run, step) is not None:
            continue
        spec = get_tool_action_spec(step.tool_id, step.action)
        if spec is None:
            raise OutcomeEvidenceError("capability_contract_unavailable")
        requires_approval = not spec.read_only or step.node_id in required or step.risk == "high"
        if not spec.read_only:
            action_binding = action_bindings.get(step.node_id) or {}
            if (
                any(
                    action_binding.get(key) != goal.get(key) for key in ("entity_type", "entity_id")
                )
                or action_binding.get("tool_id") != step.tool_id
                or action_binding.get("action") != step.action
                or action_binding.get("params_sha256") != canonical_hash(step.params)
                or action_binding.get("selector") != "order_id"
                or str(step.params.get("order_id") or "") != goal.get("entity_id")
            ):
                raise OutcomeEvidenceError("action_entity_binding_missing")
        matching = [
            call
            for call in run.tool_calls
            if call.step_id == step.step_id
            and call.node_id == step.node_id
            and call.tool_id == step.tool_id
            and call.action == step.action
            and call.params == step.params
            and call.status == "completed"
            and call.output
            and call.output.get("success") is not False
            and not execution_result_error(call.output)
            and not execution_result_requires_reconciliation(call.output)
        ]
        approval = approvals.get(step.step_id)
        if (
            step.status != "completed"
            or not matching
            or (
                requires_approval
                and (
                    approval is None
                    or approval.data.get("task_id") != result["task_id"]
                    or approval.data.get("tool_id") != step.tool_id
                    or approval.data.get("action") != step.action
                    or approval.data.get("params_sha256") != _params_hash(step)
                    or not isinstance(approval.data.get("plan_sha256"), str)
                    or len(approval.data["plan_sha256"]) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in approval.data["plan_sha256"]
                    )
                    or approval.data["plan_sha256"] != run.metadata.get("plan_sha256")
                )
            )
        ):
            raise OutcomeEvidenceError("action_receipt_or_approval_missing")
        call = matching[-1]
        if not call.call_id or not (bound_at <= _time(call.started_at) <= _time(call.finished_at)):
            raise OutcomeEvidenceError("action_observation_order_invalid")
        if approval and not (bound_at <= _time(approval.created_at) <= _time(call.started_at)):
            raise OutcomeEvidenceError("action_observation_order_invalid")
        calls.append(
            {
                "call_id": call.call_id,
                "step_id": step.step_id,
                "tool_id": step.tool_id,
                "action": step.action,
                "permission": call.permission,
                "started_at": call.started_at,
                "finished_at": call.finished_at,
                "approval_result": "approved" if approval else "not_required_read_only",
                "approval_event_id": approval.event_id if approval else "",
                "approved_by": str(approval.data["approved_by"]) if approval else "",
                "approval_params_sha256": str(approval.data.get("params_sha256") or "")
                if approval
                else "",
                "plan_sha256": str(approval.data.get("plan_sha256") or "") if approval else "",
            }
        )
    approved = [call for call in calls if call["approval_result"] == "approved"]
    if approved:
        latest = approved[-1]
        receipt = run.metadata.get("approval_receipt") or {}
        if receipt.get("task_id") != result["task_id"] or any(
            receipt.get(key) != latest[key]
            for key in ("step_id", "tool_id", "action", "approved_by")
        ):
            raise OutcomeEvidenceError("approval_receipt_mismatch")
    return result, calls


def _observe(run: AgentRun, binding: dict, after: dict, now: datetime) -> dict[str, Any]:
    goal = binding["goal"]
    bound_at = _time(binding.get("bound_at"))
    scope = {
        "tenant_id": tenant_id_of_run(run),
        "actor_id": run.user_id,
        "mod_id": str((run.metadata.get("runtime_context") or {}).get("mod_id") or ""),
    }
    baseline = authority_sample(binding["baseline"], goal, scope=scope)
    current = authority_sample(after, goal, scope=scope)
    result, calls = _execution_evidence(run, bound_at)
    if not (
        _time(baseline["observed_at"]) <= bound_at < _time(baseline["expires_at"])
        and max(_time(call["finished_at"]) for call in calls)
        <= _time(current["observed_at"])
        <= now
        < _time(current["expires_at"])
        and baseline["source"] == current["source"]
    ):
        raise OutcomeEvidenceError("stale_or_incomparable_observation")
    before_value, after_value = _number(baseline["value"]), _number(current["value"])
    if before_value != after_value and baseline["source_version"] == current["source_version"]:
        raise OutcomeEvidenceError("source_version_conflict")
    direction = goal.get("direction")
    if direction not in {"increase", "decrease"}:
        raise OutcomeEvidenceError("invalid_metric_direction")
    delta = after_value - before_value
    improvement = delta if direction == "increase" else -delta
    change = "improved" if improvement > 0 else "worsened" if improvement < 0 else "no_change"
    target = _number(goal.get("target"))
    runtime = run.metadata["runtime_context"]
    observed = {
        "protocol": "xcagi.enterprise-outcome.v1",
        "tenant_id": tenant_id_of_run(run),
        "actor_id": str(run.user_id),
        "mod_id": str(runtime.get("mod_id") or ""),
        "run_id": run.run_id,
        "task_id": result["task_id"],
        "goal_id": goal["goal_id"],
        "goal_binding_sha256": goal["binding_sha256"],
        "entity_type": goal["entity_type"],
        "entity_id": goal["entity_id"],
        "metric": goal["metric"],
        "unit": goal["unit"],
        "status": change,
        "observation_verified": True,
        "business_success": None,
        "attribution": "unproven",
        "target_met": after_value >= target if direction == "increase" else after_value <= target,
        "delta": str(delta),
        "before": baseline,
        "after": current,
        "actions": calls,
        "statement": (
            f"任务 {result['task_id']} 执行后，{goal['entity_type']} {goal['entity_id']} 的"
            f" {goal['metric']} 从 {before_value} 变为 {after_value} {goal['unit']}；"
            f"观察结果 {change}。权威数据已回查，动作与指标变化的因果关系未证实。"
        ),
        "evidence": [
            {
                "source": "business_harness",
                "run_id": run.run_id,
                "task_id": result["task_id"],
                "projection_key": result["projection_key"],
                "actions": calls,
            },
            {"source": "authoritative_before", **baseline},
            {"source": "authoritative_after", **current},
        ],
    }
    observed["observation_id"] = canonical_hash(observed)
    return observed


def _frozen(run: AgentRun, goal: dict) -> dict[str, Any] | None:
    rows = [event.data.get("observation") for event in run.events if event.event_type == _EVENT]
    if not rows:
        return None
    body = rows[0]
    if (
        not isinstance(body, dict)
        or any(row != body for row in rows)
        or body.get("observation_id")
        != canonical_hash({key: value for key, value in body.items() if key != "observation_id"})
        or body.get("run_id") != run.run_id
        or body.get("goal_binding_sha256") != goal.get("binding_sha256")
        or (body.get("actor_id"), body.get("tenant_id"), body.get("mod_id")) != _result_scope(run)
    ):
        raise OutcomeEvidenceError("frozen_observation_conflict")
    return copy.deepcopy(body)


class OutcomeService:
    def __init__(self, *, repository=None, projection=None, memory_service=None, clock=None):
        self.repository = repository
        self.projection = projection
        self.memory_service = memory_service
        self.clock = clock or (lambda: datetime.now(UTC))

    def evaluate(
        self, run_id: str, *, tenant_id: str, actor_id: str, mod_id: str | None = None
    ) -> dict[str, Any]:
        """Re-read authority, freeze one observation with run CAS, then propose memory."""
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository

        repository = self.repository or get_agent_run_repository()
        projection = self.projection
        if projection is None:
            from app.application.enterprise_cognition.projection import get_projection_service

            projection = get_projection_service()
        if mod_id is None:
            from app.request_active_mod_ctx import get_request_active_mod_id

            mod_id = get_request_active_mod_id()
        tenant_id, actor_id = str(tenant_id), str(actor_id)
        run = repository.get(run_id)
        if run is None or _result_scope(run) != (actor_id, tenant_id, mod_id):
            return _unknown("run_not_accessible")
        previous = copy.deepcopy(run)
        runtime = run.metadata.get("runtime_context") or {}
        if str(runtime.get("mod_id") or "") != mod_id:
            return _unknown("run_not_accessible")
        binding = runtime.get("enterprise_cognition") or {}
        plan_binding = ((run.metadata.get("plan") or {}).get("metadata") or {}).get(
            "enterprise_cognition"
        )
        if not binding or binding != plan_binding:
            return _unknown("approved_plan_binding_mismatch")
        goal = binding.get("goal") or {}
        if not all(
            goal.get(key)
            for key in ("goal_id", "entity_type", "entity_id", "metric", "unit", "binding_sha256")
        ):
            return _unknown("goal_binding_missing")
        goal_body = {
            key: value for key, value in goal.items() if key not in {"binding_sha256", "created_at"}
        }
        if canonical_hash(goal_body) != goal["binding_sha256"] or (
            str(goal.get("actor_id") or ""),
            str(goal.get("tenant_id") or ""),
            goal.get("mod_id"),
        ) != (actor_id, tenant_id, mod_id):
            return _unknown("goal_binding_conflict")
        if not binding.get("baseline") or not binding.get("bound_at"):
            return _unknown("baseline_missing")
        after = projection.get(
            goal["entity_type"],
            goal["entity_id"],
            tenant_id=tenant_id,
            actor_id=actor_id,
            mod_id=str(runtime.get("mod_id") or ""),
            force_refresh=True,
        )
        if after.get("freshness") != "fresh":
            return _unknown("authority_readback_unavailable")
        try:
            observation = _frozen(run, goal)
        except OutcomeEvidenceError as exc:
            return _unknown(str(exc))
        if observation is None:
            try:
                observation = _observe(run, binding, after, self.clock())
            except OutcomeEvidenceError as exc:
                return _unknown(str(exc))
            run.add_event(_EVENT, "经营指标已回查；因果归因仍未证实", {"observation": observation})
            try:
                saved = repository.save_if_unchanged(run, previous)
            except INFRA_TRANSIENT:
                logger.warning("Enterprise observation commit needs readback for run %s", run_id)
                saved = False
            if not saved:
                try:
                    winner = repository.get(run_id)
                except INFRA_TRANSIENT:
                    return _unknown("observation_persistence_unconfirmed")
                if winner is None or _result_scope(winner) != (actor_id, tenant_id, mod_id):
                    return _unknown("run_changed_during_observation")
                try:
                    observation = _frozen(winner, goal)
                except OutcomeEvidenceError as exc:
                    return _unknown(str(exc))
                if observation is None:
                    return _unknown("run_changed_during_observation")
        try:
            memory = record_outcome_observation(
                observation,
                tenant_id=tenant_id,
                mod_id=str(runtime.get("mod_id") or ""),
                memory_service=self.memory_service,
            )
        except INFRA_TRANSIENT:
            logger.exception("Enterprise outcome memory remains pending for run %s", run.run_id)
            memory = {"memory_status": "retry_required", "reason_code": "memory_unavailable"}
        return {**copy.deepcopy(observation), **memory}


def get_outcome_service() -> OutcomeService:
    return OutcomeService()


def observe_terminal_run(run_id: str, *, repository=None) -> dict[str, Any] | None:
    """Post-commit worker hook; failures never alter or re-dispatch the task."""
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.infrastructure.auth.agent_mod_scope import (
        agent_mod_execution_scope,
        validate_actor_context,
    )
    from app.infrastructure.tenant_scope import owned_tenant_scope

    try:
        repository = repository or get_agent_run_repository()
        run = repository.get(run_id)
        if run is None:
            return None
        runtime = run.metadata.get("runtime_context") or {}
        if not runtime.get("enterprise_cognition") or run.status != "completed":
            return None
        scope = _result_scope(run)
        if scope is None or validate_actor_context(runtime) is not None:
            return _unknown("observation_authorization_unavailable")
        actor_id, tenant_id, mod_id = scope
        with (
            owned_tenant_scope(int(tenant_id)),
            agent_mod_execution_scope(runtime.get("_mod_authorization")),
        ):
            observation = OutcomeService(repository=repository).evaluate(
                run_id, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id
            )
            if observation.get("observation_verified") is True:
                from app.application.business_harness_projection import (
                    project_enterprise_outcome_to_conversation,
                )

                try:
                    message_id = project_enterprise_outcome_to_conversation(
                        run_id, observation, repository=repository
                    )
                    has_conversation = bool(
                        runtime.get("conversation_id") or runtime.get("session_id")
                    )
                    observation["chat_projection_status"] = (
                        ("recorded" if message_id is not None else "retry_required")
                        if has_conversation
                        else "not_applicable"
                    )
                except RECOVERABLE_ERRORS:
                    observation["chat_projection_status"] = "retry_required"
                    logger.warning(
                        "Enterprise observation chat projection needs retry for run %s",
                        run_id,
                        exc_info=True,
                    )
        return observation
    except RECOVERABLE_ERRORS:
        logger.warning(
            "Enterprise terminal observation needs retry for run %s", run_id, exc_info=True
        )
        return _unknown("terminal_observation_retry_required")


def record_outcome_observation(
    observation: dict[str, Any], *, tenant_id: str, mod_id: str, memory_service: Any = None
) -> dict[str, Any]:
    """Propose one immutable episodic candidate; never confirm or rewrite facts.

    The caller supplies an observation already frozen on the authoritative run.
    MemoryV2 owns transactions, duplicate fingerprints, capacity and governance.
    """
    if (
        not tenant_id
        or observation.get("tenant_id") != tenant_id
        or observation.get("mod_id") != mod_id
        or observation.get("observation_verified") is not True
        or not observation.get("observation_id")
        or not observation.get("evidence")
    ):
        return {"memory_status": "not_written", "reason_code": "unverified_observation"}
    owner = scoped_personal_memory_id(
        {"tenant_id": tenant_id, "actor_id": observation.get("actor_id"), "mod_id": mod_id}
    )
    if not owner:
        return {"memory_status": "not_written", "reason_code": "memory_owner_unavailable"}
    service = memory_service or get_user_memory_service()
    key = "enterprise_outcome:" + observation["observation_id"]
    # Reuse the authority transaction so a deleted or corrected observation is
    # never resurrected between checking its lifecycle and proposing a retry.
    with service._store.transaction():
        existing = next(
            (
                row
                for row in service.list_memories(owner)
                if any(
                    revision.get("key") == key
                    for revision in [
                        row,
                        *(entry.get("previous") or {} for entry in row.get("history", [])),
                    ]
                )
            ),
            None,
        )
        result = (
            {"success": True, "created": False, "candidate": existing}
            if existing
            else service.propose_memory_candidate(
                owner,
                "episodic",
                key,
                copy.deepcopy(observation),
                source="workflow_observation",
                confidence=1.0,
                evidence=copy.deepcopy(observation["evidence"]),
            )
        )
    candidate = result.get("candidate") or {}
    if not result.get("success") or not candidate.get("memory_id"):
        return {
            "memory_status": "not_written",
            "reason_code": result.get("error_code") or "memory_write_unconfirmed",
        }
    return {
        "memory_id": candidate["memory_id"],
        "memory_scope": "personal",
        "memory_status": candidate["status"],
        "memory_created": result.get("created") is True,
        "memory_requires_confirmation": candidate["status"] == "pending",
    }


# Repair the same frozen observation and governed memory candidate after a restart.
_KEY = "enterprise_outcome_recovery"
_LEASE_SECONDS = 120.0


def _eligible(run, now: float) -> bool:
    state = run.metadata.get(_KEY) or {}
    return bool(
        run.status == "completed"
        and (run.metadata.get("runtime_context") or {}).get("enterprise_cognition")
        and state.get("status") != "recorded"
        and float(state.get("next_attempt_at") or 0) <= now
        and float(state.get("lease_until") or 0) <= now
    )


def _candidates(repository, now: float, limit: int):
    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        return repository.list_recent(limit=limit, matches=lambda run: _eligible(run, now))
    from sqlalchemy import JSON, case, cast, func
    from sqlalchemy.sql.elements import ColumnElement

    from app.db.models.agent import AgentRunRecord

    repository._ensure_schema()
    with repository._session_scope(read_only=True) as db:
        column = AgentRunRecord.payload_json
        dialect = db.get_bind().dialect.name
        payload: ColumnElement[Any]
        if dialect == "sqlite":
            payload = case((func.json_valid(column) == 1, column), else_="{}")

            def field(*path):
                return func.json_extract(payload, "$." + ".".join(path))

        elif dialect == "postgresql":
            from sqlalchemy import Float

            payload = cast(
                case((func.pg_input_is_valid(column, "jsonb"), column), else_="{}"), JSON
            )

            def field(*path):
                result = func.json_extract_path_text(payload, *path)
                return (
                    cast(result, Float)
                    if path[-1] in {"next_attempt_at", "lease_until"}
                    else result
                )

        else:
            # The supported persistent runtimes are SQLite and PostgreSQL.
            return []
        query = (
            db.query(AgentRunRecord)
            .filter(
                AgentRunRecord.status == "completed",
                field("metadata", "runtime_context", "enterprise_cognition").is_not(None),
                func.coalesce(field("metadata", _KEY, "status"), "") != "recorded",
                func.coalesce(field("metadata", _KEY, "next_attempt_at"), 0) <= now,
                func.coalesce(field("metadata", _KEY, "lease_until"), 0) <= now,
            )
            .order_by(AgentRunRecord.updated_at.asc(), AgentRunRecord.run_id.asc())
            .limit(limit)
        )
        return [
            run
            for row in query
            if (run := repository._record_to_run(row)) is not None and _eligible(run, now)
        ]


def recover_terminal_outcome(
    run_id: str,
    *,
    repository=None,
    observer: Callable[..., dict[str, Any] | None] | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Read original evidence once per lease; never invoke an action or approve it."""
    repository = repository or get_agent_run_repository()
    current_time = time.time() if now is None else float(now)
    try:
        run = repository.get(run_id)
        if run is None or not _eligible(run, current_time):
            return None
        previous = copy.deepcopy(run)
        state = dict(run.metadata.get(_KEY) or {})
        attempt = max(0, int(state.get("attempt") or 0)) + 1
        token = uuid.uuid4().hex
        run.metadata[_KEY] = {
            **state,
            "status": "observing",
            "attempt": attempt,
            "lease_token": token,
            "lease_until": current_time + _LEASE_SECONDS,
        }
        if not repository.save_if_unchanged(run, previous):
            return None
        if observer is None:
            observer = observe_terminal_run
        try:
            result = observer(run_id, repository=repository) or {}
        except RECOVERABLE_ERRORS:
            logger.warning("Outcome readback remains pending run=%s", run_id, exc_info=True)
            result = {"reason_code": "terminal_observation_retry_required"}
        # Evaluate may itself have appended the frozen observation. Read it back
        # before settling this lease; never save a pre-observation snapshot.
        current = repository.get(run_id)
        if current is None or (current.metadata.get(_KEY) or {}).get("lease_token") != token:
            return result
        previous = copy.deepcopy(current)
        recorded = bool(
            result.get("observation_verified") is True
            and result.get("observation_id")
            and result.get("memory_id")
            and result.get("memory_status") not in {None, "not_written", "retry_required"}
            and result.get("chat_projection_status") != "retry_required"
        )
        current.metadata[_KEY] = {
            "status": "recorded" if recorded else "pending",
            "attempt": attempt,
            "lease_until": 0,
            "next_attempt_at": 0 if recorded else current_time + min(300, 5 * 2 ** min(attempt, 6)),
            "reason_code": "" if recorded else str(result.get("reason_code") or "evidence_pending"),
            "observation_id": str(result.get("observation_id") or ""),
            "memory_id": str(result.get("memory_id") or ""),
            "memory_status": str(result.get("memory_status") or "not_written"),
        }
        if recorded:
            current.add_event(
                "enterprise.outcome_recorded",
                "原经营结果已写入证据记忆；未重新执行任何业务动作",
                copy.deepcopy(current.metadata[_KEY]),
            )
        repository.save_if_unchanged(current, previous)
        return result
    except RECOVERABLE_ERRORS:
        # A lost claim/settlement commit leaves the same run discoverable after
        # lease expiry. There is no new request ID or business redispatch.
        logger.warning("Outcome recovery needs original-run readback run=%s", run_id, exc_info=True)
        return {"status": "unknown", "reason_code": "outcome_recovery_persistence_unconfirmed"}


def reconcile_pending_outcomes(
    *, repository=None, limit: int = 10, now: float | None = None, stopped=None, observer=None
) -> int:
    """Periodic/startup repair of completed runs, including a crash before any hook."""
    repository = repository or get_agent_run_repository()
    current_time = time.time() if now is None else float(now)
    attempted = 0
    for run in _candidates(repository, current_time, max(1, min(int(limit), 100))):
        if stopped is not None and stopped():
            break
        if (
            recover_terminal_outcome(
                run.run_id, repository=repository, observer=observer, now=current_time
            )
            is not None
        ):
            attempted += 1
    return attempted
