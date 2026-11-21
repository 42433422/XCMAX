"""Bind actual, owned WorkflowExecution receipts to generated graphs and experiments."""

from __future__ import annotations

import hashlib
from datetime import UTC, timedelta

from sqlalchemy import select

from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.customer_value_classification import parse_datetime
from modstore_server.eventing.db_outbox import enqueue
from modstore_server.models import (
    OutboxEvent,
    RetortEvolutionRun,
    User,
    Workflow,
    WorkflowExecution,
    WorkflowSandboxRun,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_CUSTOMER_MEASUREMENT,
    WORKFLOW_EXECUTION_MEASUREMENT,
)
from modstore_server.workflow_nl_training import _digest
from modstore_server.workflow_sandbox_state import (
    GRAPH_GUARD_FAILED,
    workflow_graph_fingerprint,
)

START_EVENT = "workflow.execution.feedback_started"


def _owned_graph(db, execution, fingerprint):
    workflow = db.get(Workflow, execution.workflow_id, populate_existing=True)
    return (
        workflow is not None
        and workflow.user_id == execution.user_id
        and workflow_graph_fingerprint(db, workflow.id) == fingerprint
    )


def _admitted(db, binding, *, completing=False, promoted=False):
    from modstore_server import retort_experiment_runtime as runtime
    from modstore_server.retort_feedback_experiments import (
        approved_policy,
        traffic_block_reason,
    )

    assignment = binding.get("assignment") or {}
    customer = assignment.get("measurement_scope") == WORKFLOW_CUSTOMER_MEASUREMENT
    if assignment.get("measurement_scope") not in {
        WORKFLOW_EXECUTION_MEASUREMENT,
        WORKFLOW_CUSTOMER_MEASUREMENT,
    }:
        return False
    row = db.get(RetortEvolutionRun, assignment.get("request_id"), populate_existing=True)
    user = db.get(User, binding["user_id"], populate_existing=True)
    if (
        row is None
        or user is None
        or user.deleted_at is not None
        or user.account_state in {"disabled", "suspended", "blocked", "deleted"}
        or getattr(user, "is_active", True) is False
    ):
        return False
    try:
        spec, effects = approved_policy(row)
        if traffic_block_reason(db, row, effects):
            return False
        progress, life = effects.get("experiment") or {}, spec["lifecycle"]
        expected, current = progress.get("identity") or {}, runtime._identity()
        now = runtime.datetime.now(UTC)
        end = parse_datetime(progress.get("exposure_ends_at"))
        limit = parse_datetime(progress.get("evaluation_at" if completing else "lease_until"))
        variation = assignment.get("variation_id")
        if variation not in {"0", "1"}:
            return False
        common = (
            progress.get("execution_source_verified") is True
            and expected.get("git_sha")
            and all(
                current.get(key, "") == expected.get(key, "")
                for key in ("git_sha", "artifact_sha256", "image_digest", "release_id")
            )
            and assignment["release_sha"] == progress.get("release_sha")
            and assignment["policy_digest"] == progress.get("policy_digest")
            and assignment["experiment_id"] == progress.get("experiment_id")
            and assignment["user_id"] == binding["user_id"]
            and assignment["workflow_id"] == binding["workflow_id"]
            and assignment["subject_id"] == str(binding["user_id"])
            and assignment["tracking_key"] == f"xcagi-retort-{row.id}"
            and assignment["value_sha256"]
            == hashlib.sha256(
                life["treatment_prompt" if variation == "1" else "control_prompt"].encode()
            ).hexdigest()
            and binding["user_id"] in life["cohort_user_ids"]
        )
        if promoted:
            return bool(
                common
                and progress.get("traffic") == "candidate"
                and progress.get("decision") == "promote"
                and progress.get("rollout_verified") is True
            )
        return bool(
            common
            and not progress.get("closed_at")
            and not progress.get("final_measurement")
            and progress.get("decision") != "rollback"
            and end
            and limit
            and ((customer or now <= limit) if completing else now < min(end, limit))
            and (completing or progress.get("traffic") == "experiment")
        )
    except (ValueError, TypeError, KeyError):
        return False


def begin_execution_feedback(db, execution):
    """Called before the actual engine, in the same transaction as the running receipt."""
    from modstore_server import retort_experiment_runtime as runtime

    inputs = json_loads(execution.input_data, None)
    requested = isinstance(inputs, dict) and "customer_delivery" in inputs
    workflow = db.get(Workflow, execution.workflow_id, populate_existing=True)
    if workflow is None or workflow.user_id != execution.user_id:
        return
    fingerprint = workflow_graph_fingerprint(db, workflow.id)
    generation, report = None, None
    with db.scalars(
        select(WorkflowSandboxRun)
        .where(
            WorkflowSandboxRun.workflow_id == workflow.id,
            WorkflowSandboxRun.user_id == execution.user_id,
            WorkflowSandboxRun.graph_fingerprint == fingerprint,
            WorkflowSandboxRun.validate_only.is_(True),
            WorkflowSandboxRun.ok.is_(True),
            WorkflowSandboxRun.report_json.contains("natural_language_generation", autoescape=True),
        )
        .order_by(WorkflowSandboxRun.id.desc())
    ).yield_per(100) as rows:
        for row in rows:
            value = json_loads(row.report_json, {})
            if value.get("phase") == "natural_language_generation":
                generation, report = row, value
                break
    if generation is None:
        if requested:
            raise ValueError("workflow_customer_generation_required")
        return
    if not isinstance(inputs, dict):
        return
    binding = {
        "execution_id": execution.id,
        "workflow_id": workflow.id,
        "user_id": execution.user_id,
        "generation_run_id": generation.id,
        "graph_fingerprint": fingerprint,
        "input_sha256": _digest(inputs),
        "started_at": runtime.datetime.now(UTC).isoformat(),
        "assignment": report.get("assignment"),
    }
    binding["metric_admitted"] = _admitted(db, binding)
    assignment = binding["assignment"] or {}
    customer = assignment.get("measurement_scope") == WORKFLOW_CUSTOMER_MEASUREMENT
    if requested and not customer:
        raise ValueError("workflow_customer_experiment_required")
    if customer:
        from modstore_server.retort_feedback_experiments import approved_policy
        from modstore_server.workflow_customer_delivery import prepare_customer_delivery

        if not requested or any(key in inputs for key in ("execution_id", "workflow_execution_id")):
            raise ValueError("workflow_customer_execution_contract_required")
        if not binding["metric_admitted"] and not _admitted(db, binding, promoted=True):
            raise ValueError("workflow_customer_experiment_no_longer_approved")
        row = db.get(RetortEvolutionRun, assignment["request_id"])
        policy, _effects = approved_policy(row)
        source = policy["lifecycle"]["customer_outcomes"]
        binding["customer_delivery"] = prepare_customer_delivery(db, execution, binding, source)
        binding["customer_outcome_due_at"] = (
            runtime.datetime.now(UTC) + timedelta(hours=source["observation_hours"])
        ).isoformat()
    blocked = (
        assignment.get("measurement_scope")
        in {WORKFLOW_EXECUTION_MEASUREMENT, WORKFLOW_CUSTOMER_MEASUREMENT}
        and assignment.get("variation_id") == "1"
        and not binding["metric_admitted"]
        and not _admitted(db, binding, promoted=True)
    )
    binding["execution_allowed"] = not blocked
    enqueue(db, START_EVENT, str(execution.id), binding, event_id=f"{START_EVENT}:{execution.id}")
    if binding["metric_admitted"]:
        runtime._enqueue_exposure(
            db,
            {
                **binding["assignment"],
                "assigned_at": binding["started_at"],
                "execution_id": execution.id,
            },
        )
    return {
        "blocked": "workflow_experiment_graph_no_longer_approved" if blocked else None,
        "graph_fingerprint": fingerprint,
        **({"customer_delivery": True} if customer else {}),
    }


def complete_execution_feedback(db, execution):
    """Persist the actual terminal atomically; invalidated/late identities remain archival."""
    from modstore_server import retort_experiment_runtime as runtime

    if execution.status not in {"completed", "failed"} or execution.completed_at is None:
        return
    event = db.query(OutboxEvent).filter_by(event_id=f"{START_EVENT}:{execution.id}").first()
    if event is None:
        return
    binding = json_loads(event.payload_json, {})
    if execution.error_message == GRAPH_GUARD_FAILED:
        binding["execution_allowed"] = False
        event.payload_json = json_dumps(binding)
    assignment = binding.get("assignment") or {}
    if assignment.get("measurement_scope") == WORKFLOW_CUSTOMER_MEASUREMENT:
        # The durable run is not customer success. The original experiment's
        # fixed-window reconciler consumes independent customer outcome receipts.
        return
    if assignment.get("measurement_scope") != WORKFLOW_EXECUTION_MEASUREMENT:
        return
    original = {
        **assignment,
        "generation_observation_id": assignment["observation_id"],
        "observation_id": f"workflow-execution:{execution.id}",
        "execution_id": execution.id,
        "generation_run_id": binding["generation_run_id"],
        "graph_fingerprint": binding["graph_fingerprint"],
        "assigned_at": binding["started_at"],
    }
    result = {"ok": execution.status == "completed", "error": execution.error_message or ""}
    if not (
        binding.get("metric_admitted") is True
        and binding.get("execution_allowed") is True
        and binding["user_id"] == execution.user_id
        and binding["input_sha256"] == _digest(json_loads(execution.input_data, None))
        and _owned_graph(db, execution, binding["graph_fingerprint"])
        and _admitted(db, binding, completing=True)
    ):
        enqueue(
            db,
            "experiment.execution_archived",
            assignment["request_id"],
            {
                **original,
                "success": result["ok"],
                "execution_status": execution.status,
                "reason": "execution_identity_or_approval_no_longer_current",
            },
            event_id=f"experiment.execution_archived:{execution.id}",
        )
        return
    duration = (
        runtime.datetime.now(UTC) - parse_datetime(binding["started_at"])
    ).total_seconds() * 1000
    runtime.enqueue_observation(db, original, result=result, duration_ms=max(0, duration))


def execution_failure_records(*, days, cohort, baseline):
    """Replay inputs are private SQL data; a status alone never becomes a training case."""
    from modstore_server import retort_experiment_runtime as runtime
    from modstore_server.retort_experiment_surfaces import WORKFLOW_NL_RESOURCE

    records = []
    with get_session_factory()() as db:
        rows = (
            db.query(WorkflowExecution)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .filter(
                WorkflowExecution.status == "failed",
                WorkflowExecution.user_id == Workflow.user_id,
                WorkflowExecution.user_id.in_(cohort),
                WorkflowExecution.completed_at
                >= runtime.datetime.now(UTC) - timedelta(days=max(1, days)),
            )
            .order_by(WorkflowExecution.id.desc())
            .limit(10000)
        )
        for execution in rows:
            event = (
                db.query(OutboxEvent).filter_by(event_id=f"{START_EVENT}:{execution.id}").first()
            )
            binding = json_loads(event.payload_json, {}) if event else {}
            generation = (
                db.get(WorkflowSandboxRun, binding.get("generation_run_id")) if binding else None
            )
            report = json_loads(generation.report_json, {}) if generation else {}
            source = report.get("generation") or {}
            inputs = json_loads(execution.input_data, None)
            if (
                generation is None
                or generation.user_id != execution.user_id
                or generation.workflow_id != execution.workflow_id
                or binding.get("execution_allowed") is not True
                or source.get("prompt_sha256") != baseline
                or not source.get("task")
                or source.get("context_sha256") != _digest(source.get("context"))
                or not isinstance(inputs, dict)
                or binding.get("input_sha256") != _digest(inputs)
                or not execution.error_message
            ):
                continue
            context = {
                **source["context"],
                "execution_feedback": {
                    "execution_id": execution.id,
                    "input": inputs,
                    "error": execution.error_message,
                    "graph_fingerprint": binding["graph_fingerprint"],
                },
            }
            if len(json_dumps(context).encode()) > 200000:
                continue
            records.append(
                {
                    "status": "failed",
                    "surface": "workflow_nl_prompt",
                    "resource_id": WORKFLOW_NL_RESOURCE,
                    "error": "workflow_execution_failed",
                    "task_excerpt": source["task"],
                    "generation_context": context,
                    "prompt_sha256": baseline,
                    "timestamp": execution.completed_at.isoformat(),
                    "run_id": f"workflow-execution:{execution.id}",
                    "workflow_id": execution.workflow_id,
                    "user_id": execution.user_id,
                    "validation_errors": [execution.error_message],
                }
            )
    return records
