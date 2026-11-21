"""Product surface adapter using GrowthBook allocation and the existing transactional outbox.

Only authenticated, explicitly authorized account IDs participate. Observations
come from actual calls; no scheduler, health check or test task creates traffic.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from modstore_server.customer_service_tools import json_loads
from modstore_server.customer_value_classification import parse_datetime
from modstore_server.models import RetortEvolutionRun, User, get_session_factory
from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_CUSTOMER_MEASUREMENT,
    WORKFLOW_EXECUTION_MEASUREMENT,
    surface_identity,
)
from modstore_server.retort_feedback_experiments import (
    approved_policy,
    traffic_block_reason,
)


def _identity():
    from modstore_server.self_maintenance_loop_api import _release_manifest_payload

    return _release_manifest_payload()


def select_variant(*, surface, resource_id, subject_id, default_value, workflow_id=None):
    """Reusable surface contract: return an actual value plus a private observation handle.

    Only employee cognition and the owned-workflow generator have consumers.
    The latter's static-validation observation is distinct from business execution.
    """
    if not resource_id:
        return default_value, None
    with (
        get_session_factory()() as db,
        db.scalars(
            select(RetortEvolutionRun)
            .where(RetortEvolutionRun.effects_json.contains(str(resource_id), autoescape=True))
            .order_by(RetortEvolutionRun.created_at.desc())
        ).yield_per(100) as rows,
    ):
        user = db.get(User, subject_id) if type(subject_id) is int and subject_id > 0 else None
        for row in rows:
            effects = json_loads(row.effects_json, {})
            policy = (
                effects.get("customer_feedback") or effects.get("training_candidate") or {}
            ).get("growthbook") or {}
            life = policy.get("lifecycle") or {}
            if life.get("surface") != surface or surface_identity(life) != (surface, resource_id):
                continue
            if not effects.get("authorization"):
                continue
            if default_value not in (life.get("control_prompt"), life.get("treatment_prompt")):
                return default_value, None
            policy, effects = approved_policy(row)
            if traffic_block_reason(db, row, effects):
                return life["control_prompt"], None
            if not os.getenv("MODSTORE_RETORT_GROWTHBOOK_URL"):
                return life["control_prompt"], None
            if (
                user is None
                or getattr(user, "is_active", True) is False
                or user.deleted_at is not None
                or user.account_state in {"disabled", "suspended", "blocked", "deleted"}
                or subject_id not in life["cohort_user_ids"]
            ):
                return life["control_prompt"], None
            if surface == "workflow_nl_prompt":
                from modstore_server.models import Workflow

                workflow = db.get(Workflow, workflow_id) if type(workflow_id) is int else None
                if workflow is None or workflow.user_id != subject_id:
                    return life["control_prompt"], None
            progress = effects.get("experiment") or {}
            if not progress:
                return life["control_prompt"], None
            current, expected = _identity(), progress.get("identity") or {}
            if not expected.get("git_sha") or any(
                current.get(key, "") != expected.get(key, "")
                for key in ("git_sha", "artifact_sha256", "image_digest", "release_id")
            ):
                return life["control_prompt"], None
            if (
                progress.get("traffic") == "candidate"
                and progress.get("decision") == "promote"
                and progress.get("rollout_verified") is True
            ):
                if life.get("measurement_scope") == WORKFLOW_CUSTOMER_MEASUREMENT:
                    value = life["treatment_prompt"]
                    return value, {
                        "request_id": row.id,
                        "experiment_id": progress["experiment_id"],
                        "tracking_key": f"xcagi-retort-{row.id}",
                        "variation_id": "1",
                        "subject_id": str(subject_id),
                        "user_id": subject_id,
                        "surface": surface,
                        "resource_id": resource_id,
                        "workflow_id": workflow_id,
                        "measurement_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
                        "release_sha": progress["release_sha"],
                        "policy_digest": progress["policy_digest"],
                        "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
                        "assigned_at": datetime.now(UTC).isoformat(),
                        "observation_id": str(uuid4()),
                        "assignment_stage": "approved_rollout",
                    }
                return life["treatment_prompt"], None
            end, lease = parse_datetime(progress.get("exposure_ends_at")), parse_datetime(
                progress.get("lease_until")
            )
            now = datetime.now(UTC)
            if (
                progress.get("traffic") != "experiment"
                or not end
                or not lease
                or not now < min(end, lease)
            ):
                return life["control_prompt"], None
            from growthbook import Experiment, GrowthBook

            key = f"xcagi-retort-{row.id}"
            sdk = GrowthBook(attributes={"id": str(subject_id)})
            try:
                result = sdk.run(
                    Experiment(
                        key=key,
                        seed=key,
                        variations=[life["control_prompt"], life["treatment_prompt"]],
                        weights=life["weights"],
                        coverage=life["coverage"],
                        hashVersion=2,
                        hashAttribute="id",
                        meta=[{"key": "0"}, {"key": "1"}],
                    )
                )
            finally:
                sdk.destroy()
            if not result.inExperiment or not result.hashUsed:
                return life["control_prompt"], None
            assignment = {
                "request_id": row.id,
                "experiment_id": progress["experiment_id"],
                "tracking_key": key,
                "variation_id": result.key,
                "subject_id": str(subject_id),
                "user_id": subject_id,
                "surface": surface,
                "resource_id": resource_id,
                "release_sha": progress["release_sha"],
                "policy_digest": progress["policy_digest"],
                "value_sha256": hashlib.sha256(result.value.encode()).hexdigest(),
                "assigned_at": now.isoformat(),
                "observation_id": str(uuid4()),
            }
            if surface == "workflow_nl_prompt":
                assignment.update(
                    workflow_id=workflow_id, measurement_scope=life["measurement_scope"]
                )
            return result.value, assignment
    return default_value, None


def _enqueue_exposure(db, assignment):
    from modstore_server.eventing.db_outbox import enqueue

    exposure_key = hashlib.sha256(
        f"{assignment['tracking_key']}:{assignment['subject_id']}:{assignment['variation_id']}".encode()
    ).hexdigest()
    enqueue(
        db,
        "experiment.exposed",
        assignment["request_id"],
        assignment,
        event_id=f"experiment.exposed:{exposure_key}",
    )


def begin_observation(assignment):
    """Persist the assigned exposure before dispatch; unavailable tracking blocks treatment."""
    if assignment is not None and assignment.get("measurement_scope") not in {
        WORKFLOW_EXECUTION_MEASUREMENT,
        WORKFLOW_CUSTOMER_MEASUREMENT,
    }:
        with get_session_factory()() as db:
            _enqueue_exposure(db, assignment)
            db.commit()


def record_observation(assignment, *, result, duration_ms, session=None):
    """Queue an actual attempt; an optional business session owns the atomic commit.

    Existing callers keep an independently committed observation. Transactional
    product writes pass their session so a successful result and its observation
    cannot be separated by a second commit. No prompts or user text are stored.
    """
    if assignment is None:
        return
    with get_session_factory()() if session is None else nullcontext(session) as db:
        enqueue_observation(db, assignment, result=result, duration_ms=duration_ms)
        if session is None:
            db.commit()


def enqueue_observation(db, assignment, *, result, duration_ms):
    """An execution terminal and its measurement share the caller's SQL transaction."""
    from modstore_server.eventing.db_outbox import enqueue
    from modstore_server.llm_failure_classifier import classify_failure_kind

    generation_only = assignment.get("measurement_scope") in {
        WORKFLOW_EXECUTION_MEASUREMENT,
        WORKFLOW_CUSTOMER_MEASUREMENT,
    } and not assignment.get("execution_id")
    event_name = "experiment.generation_observed" if generation_only else "experiment.observed"
    if not generation_only:
        _enqueue_exposure(db, assignment)
    enqueue(
        db,
        event_name,
        assignment["request_id"],
        {
            **assignment,
            "success": isinstance(result, dict) and result.get("ok") is True,
            "failure_kind": (
                classify_failure_kind(str(result.get("error") or ""), result.get("status"))
                if isinstance(result, dict) and result.get("ok") is not True
                else ""
            ),
            "duration_ms": duration_ms,
            "completed_at": datetime.now(UTC).isoformat(),
        },
        event_id=f"{event_name}:{assignment['observation_id']}",
    )
