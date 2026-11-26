"""Private real generation failures and the product's deterministic promptfoo assertion."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_EXECUTION_MEASUREMENT,
    WORKFLOW_NL_MEASUREMENT,
    WORKFLOW_NL_RESOURCE,
)

DEFERRED_BUSINESS_REASON = "training_business_replay_requires_host_verification"


def offline_execution_feedback(bundle, variables, passed):
    """Static regression can propose a runtime experiment, never prove its business effect."""
    from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT

    if any(
        (v.get("generation_context", {}).get("execution_feedback") or {}).get("measurement_scope")
        == WORKFLOW_CUSTOMER_MEASUREMENT
        for v in variables
    ):
        return {
            "feedback_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
            "runtime_verified": False,
            "reason": "independent_business_replay_required",
        }
    if (
        bundle.get("surface") == "workflow_nl_prompt"
        and any(
            isinstance(v.get("generation_context", {}).get("execution_feedback"), dict)
            for v in variables
        )
        and passed
        and bundle["prompt_sha256"]["control"] != bundle["prompt_sha256"]["candidate"]
    ):
        return {
            "feedback_scope": WORKFLOW_EXECUTION_MEASUREMENT,
            "runtime_verified": False,
            "reason": "static_regression_passed_runtime_effect_unverified",
        }
    return {}


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _policies():
    if not os.environ.get("MODSTORE_RETORT_PROTOCOLS"):
        return []
    from modstore_server.retort_evolution_api import _templates

    return [
        policy
        for template in _templates().values()
        if (policy := template.get("training_candidate") or {})
        and (policy.get("growthbook", {}).get("lifecycle") or {}).get("surface")
        == "workflow_nl_prompt"
        and policy.get("resource_id") == WORKFLOW_NL_RESOURCE
    ]


def capture_request(db, user, *, workflow, task, system_prompt, context):
    """Freeze model-visible input and conversion context only for configured account cohorts."""
    policies = _policies()
    if len(policies) != 1 or user.id not in policies[0]["growthbook"]["lifecycle"].get(
        "cohort_user_ids", []
    ):
        return None
    from modstore_server.models import ESkill
    from modstore_server.workflow_api.helpers import _serialize_workflow_snapshot

    context = {
        **context,
        "graph": _serialize_workflow_snapshot(db, workflow),
        "skills": [
            {"id": row.id, "name": row.name}
            for row in db.query(ESkill).filter(ESkill.user_id == user.id).all()
        ],
    }
    # Do not silently truncate a reproduction: an oversized case is not trainable.
    if not 1 <= len(task) <= 20000 or len(json.dumps(context).encode()) > 200000:
        return None
    return {
        "task": task,
        "context": context,
        "context_sha256": _digest(context),
        "prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
    }


def record_failure(
    db, user, workflow, reproduction, model_result, applied, *, assignment=None, session=None
):
    """Store generation provenance; successful generation is never business execution."""
    if reproduction is None and assignment is None:
        return
    from modstore_server.models import Workflow, get_session_factory
    from modstore_server.workflow_sandbox_state import record_workflow_sandbox_run

    with get_session_factory()() if session is None else nullcontext(session) as target:
        owned = target.get(Workflow, workflow.id)
        if owned is None or owned.user_id != user.id:
            return
        record_workflow_sandbox_run(
            target,
            workflow_id=owned.id,
            user_id=user.id,
            validate_only=True,
            mock_employees=True,
            report={
                "ok": applied.get("ok") is True and applied.get("sandbox_ok") is True,
                "phase": "natural_language_generation",
                "training_eligible": applied.get("error_code")
                not in {
                    "workflow_observation_commit_failed",
                    "workflow_commit_failed",
                    "workflow_persistence_failed",
                },
                "measurement_scope": WORKFLOW_NL_MEASUREMENT,
                "errors": applied.get("validation_errors") or [applied.get("error", "")],
                "generation": reproduction,
                "assignment": assignment,
                "model_output_sha256": hashlib.sha256(
                    str(model_result.get("content") or "").encode()
                ).hexdigest(),
            },
            commit=session is None,
        )


def failure_records(*, days=14):
    from sqlalchemy import select

    from modstore_server.customer_service_tools import json_loads
    from modstore_server.models import Workflow, WorkflowSandboxRun, get_session_factory
    from modstore_server.workflow_nl_graph import SYSTEM_PROMPT

    policies = _policies()
    if len(policies) != 1:
        return []
    cohort = policies[0]["growthbook"]["lifecycle"].get("cohort_user_ids", [])
    baseline = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
    records = []
    with (
        get_session_factory()() as db,
        db.scalars(
            select(WorkflowSandboxRun)
            .join(Workflow, Workflow.id == WorkflowSandboxRun.workflow_id)
            .where(
                WorkflowSandboxRun.user_id == Workflow.user_id,
                WorkflowSandboxRun.user_id.in_(cohort),
                WorkflowSandboxRun.ok.is_(False),
                WorkflowSandboxRun.validate_only.is_(True),
                WorkflowSandboxRun.created_at >= datetime.now(UTC) - timedelta(days=max(1, days)),
            )
            .order_by(WorkflowSandboxRun.id.desc())
            .limit(10000)
        ) as rows,
    ):
        for row in rows:
            report = json_loads(row.report_json, {})
            source = report.get("generation") or {}
            if (
                report.get("phase") != "natural_language_generation"
                or report.get("training_eligible") is False
                or report.get("measurement_scope") != WORKFLOW_NL_MEASUREMENT
                or source.get("prompt_sha256") != baseline
                or not source.get("task")
                or source.get("context_sha256") != _digest(source.get("context"))
            ):
                continue
            records.append(
                {
                    "status": "failed",
                    "surface": "workflow_nl_prompt",
                    "resource_id": WORKFLOW_NL_RESOURCE,
                    "error": "workflow_generation_static_validation_failed",
                    "task_excerpt": source["task"],
                    "generation_context": source["context"],
                    "prompt_sha256": source["prompt_sha256"],
                    "timestamp": row.created_at.isoformat(),
                    "run_id": f"workflow-generation:{row.id}",
                    "workflow_id": row.workflow_id,
                    "user_id": row.user_id,
                    "validation_errors": report.get("errors", []),
                }
            )
    from modstore_server.workflow_execution_feedback import execution_failure_records

    return records + execution_failure_records(days=days, cohort=cohort, baseline=baseline)


def get_assert(output, context):
    """Promptfoo's Python assertion runs the actual converter and validator in disposable SQL."""
    source = context["vars"]["generation_context"]
    from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT

    if (
        "customer_business_replay" in source
        or (source.get("execution_feedback") or {}).get("measurement_scope")
        == WORKFLOW_CUSTOMER_MEASUREMENT
    ):
        # The model-facing sandbox cannot create a stricter nested namespace.
        # Only the existing host seal may run original packages in a separate,
        # network-denied sandbox; this result never claims business validation.
        if os.environ.get("XCAGI_TRAINING_DEFER_NATIVE_REPLAY") == "1":
            return {
                "pass": False,
                "score": 0,
                "runtime_verified": False,
                "reason": DEFERRED_BUSINESS_REASON,
            }
        from modstore_server.workflow_training_replay import evaluate_business_replay

        return evaluate_business_replay(output, source)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from modstore_server.models import Base, ESkill, User, Workflow
    from modstore_server.workflow_api.helpers import _restore_workflow_from_snapshot
    from modstore_server.workflow_nl_apply import _apply_generated_response

    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="workflow-regression", password_hash="unused")
            db.add(user)
            db.flush()
            workflow = Workflow(user_id=user.id, name=source["graph"]["name"])
            db.add(workflow)
            db.flush()
            _restore_workflow_from_snapshot(db, workflow, source["graph"])
            db.add_all(
                ESkill(id=skill["id"], user_id=user.id, name=skill["name"])
                for skill in source["skills"]
            )
            db.commit()
            result = _apply_generated_response(
                db,
                user,
                workflow=workflow,
                result={"ok": True, "content": output},
                brief=source["brief"],
                target_employee_pack_id=source.get("target_employee_pack_id"),
                target_employee_label=source.get("target_employee_label"),
                preset_nodes=source.get("preset_nodes"),
                validate_in_session=True,
            )
            passed = result.get("ok") is True and result.get("sandbox_ok") is True
            return {
                "pass": passed,
                "score": int(passed),
                "reason": WORKFLOW_NL_MEASUREMENT,
            }
    finally:
        engine.dispose()
