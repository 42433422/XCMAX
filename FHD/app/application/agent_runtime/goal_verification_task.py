"""Durable review checkpoints on the original SQL run and worker lease.

This adapter owns no executor, wallet or business queue. A resumed checkpoint
can only review the frozen candidate; the existing runtime owns compensation.
"""

from __future__ import annotations

import copy
import time
from typing import Any

from app.application.agent_runtime.verification_budget import (
    JOB_KEY,
    VERIFIER_VERSION,
    verification_reserve,
)
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    REPAIRABLE_GOAL_REVIEW_ERRORS,
    AgentRuntimeContractError,
    canonical_digest,
    goal_answers,
    goal_evidence_snapshot,
    goal_report_coverage,
    valid_compensation_review,
    validate_runtime_goal,
)
from app.domain.task_lifecycle.agent_runtime_results import (
    model_unsettled,
    receipt_settled_failure,
    receipt_state,
    receipt_verified,
    verified_receipt_artifacts,
)
from app.domain.task_lifecycle.goal_review_models import GoalReview
from app.infrastructure.xiaox.binding import XiaoxBindingError

_RECOVERABLE = frozenset(
    {
        "goal_verification_timeout",
        "goal_verification_transport_error",
        "goal_verification_interrupted",
    }
)


def current_review_inputs(
    binding: Any,
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    rows: list[dict[str, Any]],
    output: str,
) -> bool:
    try:
        return validate_runtime_goal(binding.run) == contract["digest"] and snapshot == (
            goal_evidence_snapshot(contract, rows, output, goal_answers(binding.run))
        )
    except AgentRuntimeContractError:
        return False


def review_repair_checkpoint(
    input_identity: dict[str, Any], review: dict[str, Any], wire: dict[str, Any]
) -> dict[str, Any]:
    """Bind the original judgment and correction prompt before the second request."""
    context = copy.deepcopy(
        {
            "input": input_identity,
            "verifier_version": VERIFIER_VERSION,
            "review": review,
            "wire": wire,
        }
    )
    return {**context, "digest": canonical_digest(context)}


def restore_review_repair(
    run: Any, replay_response: dict[str, Any] | None, input_identity: dict[str, Any]
) -> dict[str, Any] | None:
    """A replay keeps the same restrictions as its original metered correction."""
    job = run.metadata.get(JOB_KEY) or {}
    contexts = [
        source["review_repair"]
        for source in (job, replay_response or {})
        if source.get("review_repair") is not None
    ]
    if not contexts:
        return None
    context = contexts[0]
    if (
        not isinstance(context, dict)
        or any(value != context for value in contexts[1:])
        or set(context) != {"input", "verifier_version", "review", "wire", "digest"}
        or context["input"] != input_identity
        or context["verifier_version"] != VERIFIER_VERSION
        or context["digest"]
        != canonical_digest({key: value for key, value in context.items() if key != "digest"})
        or not isinstance(context["review"], dict)
        or GoalReview.model_validate(context["review"]).model_dump() != context["review"]
    ):
        raise ValueError("Original source repair checkpoint is invalid or changed")
    wire = context["wire"]
    if (
        not isinstance(wire, dict)
        or set(wire) != {"review", "errors", "allowed_fields"}
        or wire["allowed_fields"] != ["goal_id", "source_id", "source"]
        or not isinstance(wire["review"], dict)
        or not isinstance(wire["review"].get("goals"), list)
        or len(wire["review"]["goals"]) != len(context["review"]["goals"])
        or not all(isinstance(goal, dict) for goal in wire["review"]["goals"])
        or not isinstance(wire["errors"], list)
        or not wire["errors"]
        or not all(
            isinstance(error, str) and error.startswith(REPAIRABLE_GOAL_REVIEW_ERRORS)
            for error in wire["errors"]
        )
    ):
        raise ValueError("Original source repair prompt is invalid")
    return copy.deepcopy(context)


def _current_rows(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"call_id": key, **call} for key, call in (metadata.get("calls") or {}).items()]


def _settled_response_available(job: dict[str, Any], metadata: dict[str, Any]) -> bool:
    progress = job.get("progress") or {}
    if (
        progress.get("state") == "response_received"
        and progress.get("verifier_version") == VERIFIER_VERSION
        and progress.get("input")
        == {key: job.get(key) for key in ("goal_digest", "evidence_digest", "response_digest")}
        and isinstance(progress.get("response"), dict)
        and progress.get("response_digest") == canonical_digest(progress["response"])
    ):
        return True
    return any(
        row.get("state") == "completed"
        and row.get("purpose") == "verification"
        and row.get("verification_job_id") == job.get("job_id")
        and row.get("verification_input_digest") == job.get("input_digest")
        and row.get("verification_version") == VERIFIER_VERSION
        and isinstance(row.get("verification_response"), dict)
        and row.get("verification_response_digest")
        == canonical_digest(row["verification_response"])
        for row in (metadata.get("model_requests") or {}).values()
    )


def _retry_state(
    job: dict[str, Any],
    metadata: dict[str, Any],
    *,
    recoverable: bool,
) -> dict[str, Any]:
    exhausted = int(job.get("attempts") or 0) >= 3 or bool(
        metadata.get("verification_budget")
        and verification_reserve(metadata)[0] <= 0
        and not _settled_response_available(job, metadata)
    )
    return {
        "state": "pending" if recoverable and not exhausted else "blocked",
        "terminal_code": "goal_verification_budget_exhausted" if recoverable and exhausted else "",
    }


def _identity(run: Any, rows: list[dict], output: str) -> dict[str, Any]:
    validate_runtime_goal(run)
    contract = run.metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, rows, output, goal_answers(run))
    if snapshot["conflicts"]:
        raise XiaoxBindingError("goal_evidence_conflict", "原核验回执身份冲突")
    identity = {
        "version": VERIFIER_VERSION,
        "protocol": GOAL_PROTOCOL,
        "run_id": run.run_id,
        "goal_digest": contract["digest"],
        "evidence_digest": snapshot["digest"],
        "response_digest": canonical_digest(output),
        "route_digest": canonical_digest(
            (run.metadata.get("xiaox_runtime") or {}).get("runtime_config") or {}
        ),
    }
    digest = canonical_digest(identity)
    return {**identity, "input_digest": digest, "job_id": "verify_" + digest}


def verify_artifact_bytes(rows: list[dict[str, Any]]) -> None:
    """Reopen host artifacts; unchanged metadata is not proof of unchanged bytes."""
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file

    verified = {
        (artifact["run_id"], artifact["artifact_id"], artifact["metadata"]["sha256"])
        for artifact in verified_receipt_artifacts(rows)
    }
    for row in rows:
        child_id = str(row.get("child_run_id") or "")
        for artifact in (row.get("receipt") or {}).get("artifacts") or []:
            if not isinstance(artifact, dict) or artifact.get("artifact_type") not in {
                "file",
                "office_document",
            }:
                continue
            if (
                child_id,
                artifact.get("artifact_id"),
                (artifact.get("metadata") or {}).get("sha256"),
            ) not in verified:
                continue
            uri = str(artifact.get("uri") or "")
            if not uri.startswith("/api/agent/runs/"):
                continue  # Other adapters retain their original verification contract.
            expected = f"/api/agent/runs/{child_id}/artifacts/{artifact.get('artifact_id')}"
            if not child_id or uri != expected:
                raise XiaoxBindingError("goal_artifact_changed", "核验文件不属于原业务回执")
            try:
                read_verified_run_file(child_id, artifact)
            except (OSError, ValueError, KeyError) as exc:
                raise XiaoxBindingError(
                    "goal_artifact_changed", "原核验文件已变化或不可读取"
                ) from exc


def resumable_verification(
    run: Any,
    rows: list[dict],
    *,
    now: float | None = None,
    respect_backoff: bool = True,
) -> bool:
    """A settled checkpoint can resume; unknown metering never authorizes a retry."""
    job = run.metadata.get(JOB_KEY) or {}
    metadata = run.metadata.get("xiaox_runtime") or {}
    current_time = time.time() if now is None else now
    if (
        job.get("state") not in {"pending", "running"}
        or job.get("version") != VERIFIER_VERSION
        or int(job.get("attempts") or 0) >= 3
        or (
            metadata.get("verification_budget")
            and verification_reserve(metadata)[0] <= 0
            and not _settled_response_available(job, metadata)
        )
        or (respect_backoff and float(job.get("next_attempt_at") or 0) > current_time)
        or model_unsettled(metadata)
        or run.metadata.get("non_retryable")
        or run.status in {"completed", "cancelled", "paused", "rejected", "failed"}
        or not isinstance(job.get("output"), str)
    ):
        return False
    try:
        job_id = job.get("job_id")
        return isinstance(job_id, str) and job_id == _identity(run, rows, job["output"])["job_id"]
    except (KeyError, TypeError, ValueError):
        return False


def compensable_verification(run: Any, rows: list[dict]) -> bool:
    """Only the original current gap report may request a budgeted continuation."""
    job = run.metadata.get(JOB_KEY) or {}
    metadata = run.metadata.get("xiaox_runtime") or {}
    report = run.metadata.get("runtime_goal_verification") or {}
    if (
        job.get("state") != "needs_work"
        or job.get("version") != VERIFIER_VERSION
        or report.get("verifier_version") != VERIFIER_VERSION
        or report.get("status") != "needs_work"
        or report.get("accepted") is not False
        or not isinstance(report.get("review"), dict)
        or model_unsettled(metadata)
        or run.metadata.get("non_retryable")
        or run.status in {"completed", "cancelled", "paused", "rejected", "failed", "waiting_user"}
        or not isinstance(job.get("output"), str)
        or (metadata.get("verification_budget") and verification_reserve(metadata)[0] <= 0)
        or any(
            receipt_state(row) not in {"missing", "skipped"}
            and not (receipt_verified(row) or receipt_settled_failure(row))
            for row in rows
        )
    ):
        return False
    try:
        identity = _identity(run, rows, job["output"])
        return (
            job.get("job_id") == identity["job_id"]
            and job.get("report_digest") == report.get("report_digest")
            and report.get("report_digest")
            == canonical_digest(
                {key: value for key, value in report.items() if key != "report_digest"}
            )
            and all(
                report.get(key) == job.get(key) == identity[key]
                for key in ("goal_digest", "evidence_digest", "response_digest")
            )
            and valid_compensation_review(
                report["review"],
                run.metadata["runtime_goal_contract"],
                goal_evidence_snapshot(
                    run.metadata["runtime_goal_contract"], rows, job["output"], goal_answers(run)
                ),
                job["output"],
            )
        )
    except (KeyError, TypeError, ValueError):
        return False


def begin_verification(
    store: Any,
    run_id: str,
    *,
    generation: int,
    rows: list[dict],
    output: str,
    raw_output: str | None = None,
) -> dict[str, Any]:
    """Commit the exact review input before any metered or independent I/O."""

    def begin(run: Any, metadata: dict[str, Any]) -> None:
        if metadata.get("generation") != generation:
            raise XiaoxBindingError("token_invalid", "原核验执行权已变化")
        identity = _identity(run, rows, output)
        if _identity(run, _current_rows(metadata), output) != identity:
            raise XiaoxBindingError("goal_verification_changed", "原业务回执已变化，需要重新取证")
        previous = run.metadata.get(JOB_KEY) or {}
        from app.domain.task_lifecycle.react_progress import (
            CONTROL_KEY,
            output_channel,
            requires_actions,
            review_signature,
        )

        control = metadata.get(CONTROL_KEY) or {}
        if output_channel(output) != "reply":
            raise XiaoxBindingError(
                "react_output_protocol_mismatch", "内部协议输出不能作为最终交付核验"
            )
        if (
            previous.get("state") in {"needs_work", "verified"}
            and requires_actions(control)
            and control.get("last_review_signature")
            == review_signature(run, _current_rows(metadata), output)
        ):
            raise XiaoxBindingError("react_evidence_unchanged", "没有新执行证据，不重复独立核验")
        same = previous.get("job_id") == identity["job_id"]
        attempts = int(previous.get("attempts") or 0) if same else 0
        if attempts >= 3:
            raise XiaoxBindingError("goal_verification_budget_exhausted", "独立核验恢复次数已耗尽")
        job = {
            **identity,
            "output": output,
            "raw_output": raw_output if raw_output is not None else output,
            "state": "running",
            "generation": generation,
            "attempts": attempts + 1,
            "started_at": time.time(),
            "next_attempt_at": 0,
            "model_requests_before": sorted((metadata.get("model_requests") or {}).keys()),
        }
        if same and previous.get("progress", {}).get("state") == "response_received":
            job["progress"] = copy.deepcopy(previous["progress"])
        if same and "review_repair" in previous:
            job["review_repair"] = copy.deepcopy(previous["review_repair"])
        run.metadata[JOB_KEY] = job
        metadata["active_phase"] = "verification"
        store._validate_current(run, metadata, generation)
        run.add_event(
            "runtime.goal.verification.started",
            "已保存独立核验检查点",
            {
                "job_id": job["job_id"],
                "attempt": job["attempts"],
                "evidence_digest": job["evidence_digest"],
                "verifier_version": VERIFIER_VERSION,
            },
        )

    saved = store.update(run_id, begin)
    return copy.deepcopy(saved.run.metadata[JOB_KEY])


def save_verification_progress(
    store: Any,
    run_id: str,
    *,
    job_id: str,
    generation: int,
    progress: dict[str, Any],
) -> None:
    """Keep an observed response without allowing late work to restore control."""

    def save(run: Any, metadata: dict[str, Any]) -> None:
        job = run.metadata.get(JOB_KEY) or {}
        if (
            metadata.get("generation") != generation
            or job.get("job_id") != job_id
            or job.get("generation") != generation
            or job.get("state") != "running"
            or run.status in {"cancelled", "paused", "completed", "rejected"}
        ):
            raise XiaoxBindingError("goal_verification_changed", "核验执行权或控制状态已变化")
        if (
            progress.get("state") == "requesting"
            and _identity(run, _current_rows(metadata), job.get("output", ""))["job_id"] != job_id
        ):
            raise XiaoxBindingError("goal_verification_changed", "核验请求前原目标或证据已变化")
        # This is only an observation. It neither extends a deadline nor
        # publishes a verdict; completion rechecks live authority and evidence.
        job["progress"] = copy.deepcopy(progress)
        if isinstance(progress.get("review_repair"), dict):
            job["review_repair"] = copy.deepcopy(progress["review_repair"])
        job["observed_at"] = time.time()

    store.update(run_id, save)


def finish_verification(
    store: Any,
    run_id: str,
    *,
    job_id: str,
    generation: int,
    review: dict[str, Any],
) -> dict[str, Any]:
    """Bind the verdict to current evidence, then commit with the worker's CAS."""
    rows = store.receipt_snapshot(run_id)
    verify_artifact_bytes(rows)

    def finish(run: Any, metadata: dict[str, Any]) -> None:
        store._validate_current(run, metadata, generation)
        job = run.metadata.get(JOB_KEY) or {}
        if (
            job.get("job_id") != job_id
            or job.get("generation") != generation
            or job.get("state") != "running"
            or _identity(run, rows, job.get("output", ""))["job_id"] != job_id
            or _identity(run, _current_rows(metadata), job.get("output", ""))["job_id"] != job_id
        ):
            raise XiaoxBindingError("goal_verification_changed", "核验输入或版本已变化")
        if (
            review.get("verifier_version") != VERIFIER_VERSION
            or review.get("report_digest")
            != canonical_digest(
                {key: value for key, value in review.items() if key != "report_digest"}
            )
            or review.get("accepted") is not (review.get("status") == "verified")
        ):
            raise XiaoxBindingError("goal_verification_report_invalid", "核验报告摘要或状态无效")
        for key in ("goal_digest", "evidence_digest", "response_digest"):
            if review.get(key) != job.get(key):
                raise XiaoxBindingError("goal_verification_changed", "核验结论不属于当前输入")
        if (
            review.get("accepted")
            and not goal_report_coverage(
                run.metadata["runtime_goal_contract"],
                _current_rows(metadata),
                job["output"],
                goal_answers(run),
                review,
            )["completed"]
        ):
            raise XiaoxBindingError(
                "goal_verification_report_invalid", "原始目标尚未得到完整有效的证据证明"
            )
        run.metadata["runtime_goal_verification"] = copy.deepcopy(review)
        code = review.get("error_code") or ""
        state = str(review.get("status") or "unavailable")
        retry = {"state": state, "terminal_code": ""}
        if state not in {"verified", "needs_work"}:
            retry = _retry_state(job, metadata, recoverable=code in _RECOVERABLE)
        elif (
            state == "needs_work"
            and metadata.get("verification_budget")
            and verification_reserve(metadata)[0] <= 0
        ):
            retry = {"state": "blocked", "terminal_code": "goal_verification_budget_exhausted"}
        job.update(
            **retry,
            error_code=code,
            report_digest=review.get("report_digest"),
            finished_at=time.time(),
            next_attempt_at=time.time() + min(60, 5 * 2 ** int(job["attempts"])),
            completed_goals=[
                goal["goal_id"]
                for goal in (review.get("review") or {}).get("goals") or []
                if goal.get("status") in {"satisfied", "not_applicable"}
            ],
            gaps=[
                copy.deepcopy(goal)
                for goal in (review.get("review") or {}).get("goals") or []
                if goal.get("status") == "unmet"
            ],
            violations=copy.deepcopy((review.get("review") or {}).get("violations") or []),
            uncovered_sources=copy.deepcopy(
                (review.get("review") or {}).get("uncovered_sources") or []
            ),
        )
        metadata["active_phase"] = "execution"
        run.add_event(
            "runtime.goal.verified",
            "已独立核对原始目标与实际结果",
            {
                "status": review.get("status"),
                "attempt": job["attempts"],
                "job_id": job_id,
                "report_digest": review.get("report_digest"),
            },
        )

    persisted: dict[str, Any] = store.update(run_id, finish).run.metadata[JOB_KEY]
    return persisted


def interrupted_verification(
    run: Any,
    metadata: dict[str, Any],
    *,
    cancelled: bool,
    fatal_error_code: str | None = None,
) -> None:
    """Retain the checkpoint separately from the original business receipt."""
    job = run.metadata.get(JOB_KEY) or {}
    if job.get("state") != "running" or job.get("generation") != metadata.get("generation"):
        return
    job.update(
        **(
            {"state": "cancelled", "terminal_code": ""}
            if cancelled
            else _retry_state(
                job,
                metadata,
                recoverable=not fatal_error_code,
            )
        ),
        error_code=fatal_error_code or "goal_verification_interrupted",
        next_attempt_at=time.time() + 10,
    )
    metadata["active_phase"] = "execution"


def enqueue_pending_goal_verifications(
    *,
    repository: Any,
    stopped=lambda: False,
    limit=20,
    cursor: dict[str, str] | None = None,
) -> int:
    """Use the existing durable queue; this scan never calls a model or tool."""
    from sqlalchemy import JSON, and_, case, cast, func, or_
    from sqlalchemy.sql.elements import ColumnElement

    from app.application.agent_orchestrator.run_models import utc_now_iso
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.db.models.agent import AgentRunRecord
    from app.infrastructure.xiaox.binding import XiaoxBindingStore
    from app.infrastructure.xiaox.queued_runtime import enqueue_resume, stage_queued_request
    from app.infrastructure.xiaox.receipts import resume_error

    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        return 0
    now = time.time()
    with repository.transaction(read_only=True) as db:
        column = AgentRunRecord.payload_json
        payload: ColumnElement[Any]
        due: ColumnElement[Any]
        if db.get_bind().dialect.name == "sqlite":
            payload = case((func.json_valid(column) == 1, column), else_="{}")
            state = func.json_extract(payload, f"$.metadata.{JOB_KEY}.state")
            due = func.json_extract(payload, f"$.metadata.{JOB_KEY}.next_attempt_at")
        elif db.get_bind().dialect.name == "postgresql":
            payload = cast(
                case((func.pg_input_is_valid(column, "jsonb"), column), else_="{}"), JSON
            )
            state = func.json_extract_path_text(payload, "metadata", JOB_KEY, "state")
            from sqlalchemy import Float

            due = cast(
                func.json_extract_path_text(payload, "metadata", JOB_KEY, "next_attempt_at"), Float
            )
        else:
            return 0
        query = db.query(AgentRunRecord).filter(
            AgentRunRecord.intent == "xiaox.runtime",
            AgentRunRecord.status == "blocked",
            state.in_(("pending", "running", "needs_work")),
            func.coalesce(due, 0) <= now,
        )
        if cursor:
            query = query.filter(
                or_(
                    AgentRunRecord.updated_at > cursor["updated_at"],
                    and_(
                        AgentRunRecord.updated_at == cursor["updated_at"],
                        AgentRunRecord.run_id > cursor["run_id"],
                    ),
                )
            )
        records = (
            query.order_by(AgentRunRecord.updated_at, AgentRunRecord.run_id)
            .limit(max(1, min(int(limit), 100)))
            .all()
        )
        candidates = [
            (repository._record_to_run(record), record.updated_at, record.run_id)
            for record in records
        ]
    if not candidates and cursor is not None:
        cursor.clear()
    store = XiaoxBindingStore(repository)
    queued = 0
    for candidate, updated_at, candidate_id in candidates:
        if stopped():
            break
        if cursor is not None:
            cursor.update(updated_at=updated_at, run_id=candidate_id)
        if candidate is None:
            continue
        try:
            rows = store.receipt_snapshot(candidate.run_id)
            binding = store.get(candidate.run_id)
            compensating = (binding.run.metadata.get(JOB_KEY) or {}).get("state") == "needs_work"
            eligible = compensable_verification if compensating else resumable_verification
            if (
                binding.metadata.get("coordinator_active")
                or not eligible(binding.run, rows)
                or resume_error(store, binding, rows)
            ):
                continue
            verify_artifact_bytes(rows)
            job = binding.run.metadata[JOB_KEY]
            key = f"{'compensate_' if compensating else ''}{job['job_id']}_{job['attempts']}"
            if key in (binding.run.metadata.get("runtime_requests") or {}):
                continue

            def enqueue(parent: Any, metadata: dict[str, Any]) -> None:
                if not eligible(parent, _current_rows(metadata)):
                    raise XiaoxBindingError("goal_verification_changed", "核验检查点已变化")
                parent.metadata.setdefault("runtime_requests", {})[key] = {
                    "digest": job["job_id"],
                    "state": "admitted",
                    "created_at": utc_now_iso(),
                    "source": "independent_goal_compensation"
                    if compensating
                    else "independent_goal_verification",
                }
                stage_queued_request(
                    parent,
                    key,
                    {
                        "task": parent.message,
                        "input_data": copy.deepcopy(parent.metadata.get("_xiaox_input_data")),
                        "history": copy.deepcopy(parent.metadata.get("_xiaox_history")),
                        "answer_to_waiting_input": False,
                    },
                )

            enqueue_resume(store, binding.run, enqueue)
            queued += 1
        except XiaoxBindingError:
            continue  # Cancellation, ownership, metering and the original lease win.
    return queued
