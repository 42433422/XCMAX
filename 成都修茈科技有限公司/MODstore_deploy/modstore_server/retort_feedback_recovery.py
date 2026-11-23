"""Bind Retort compensation to the existing release recovery and identity readers."""

from __future__ import annotations

import importlib.util
import os
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import RetortEvolutionRun, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.self_maintenance_deploy_receipts import BuildIdentity


def _release_identity():
    from modstore_server.retort_delivery import runtime_identity
    from modstore_server.self_maintenance_loop_api import _release_manifest_payload

    manifest = _release_manifest_payload()
    release = BuildIdentity.from_payload(manifest).require_complete("release_manifest")
    version, release_id = manifest.get("product_version"), manifest.get("release_id")
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?", version)
        or release_id != f"xcagi-{version}-{release.git_sha}"
    ):
        raise ValueError("recovery_release_identity_unavailable")
    return runtime_identity(release, version, release_id)


def freeze_recovery_policy(spec):
    """Only an operator template can opt into restoring the verified prior release."""
    if not spec:
        return {}
    if spec != {"mode": "restore_previous_release"}:
        raise ValueError("invalid_feedback_recovery_policy")
    return {
        "mode": "restore_previous_release",
        "target": _release_identity(),
        "captured_at": datetime.now(UTC).isoformat(),
    }


def _save(request_id, result):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        effects = json_loads(row.effects_json, {})
        result = {**(effects.get("recovery") or {}), **result}
        effects["recovery"] = result
        row.effects_json = json_dumps(effects)
        db.commit()
    return result


@lru_cache(maxsize=1)
def _immutable_recovery():
    """Load the release script shipped with this server, never an operator-supplied module."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "immutable_release_recovery.py"
    spec = importlib.util.spec_from_file_location("_xcmax_immutable_release_recovery", path)
    if spec is None or spec.loader is None:
        raise ValueError("immutable_recovery_reader_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_recovery_receipt(payload):
    """Reuse the rollback writer's locked request/receipt/health verification contract."""
    base = os.environ.get("XCMAX_RELEASE_BASE") or "/opt/xcmax"
    return _immutable_recovery().readback(
        payload,
        env={
            "RELEASE_BASE": base,
            "RELEASES_DIR": f"{base.rstrip('/')}/releases",
            "CURRENT_LINK": os.environ.get("XCMAX_CURRENT_LINK") or f"{base}/current",
            "RUNTIME_DIR": os.environ.get("MODSTORE_RUNTIME_DIR") or f"{base}/runtime",
            "LOCK_FILE": os.environ.get("XCMAX_RELEASE_LOCK")
            or "/run/lock/xcmax-immutable-release.lock",
            "XCMAX_ALLOW_CUSTOM_RELEASE_BASE": os.environ.get(
                "XCMAX_ALLOW_CUSTOM_RELEASE_BASE", ""
            ),
            "HEALTH_URL": os.environ.get("MODSTORE_DEPLOY_HEALTH_URL")
            or "http://127.0.0.1:9999/api/health",
            "SCHEDULER_HEALTH_URL": os.environ.get("MODSTORE_SCHEDULER_HEALTH_URL")
            or "http://127.0.0.1:9990/api/health",
            "PUBLIC_HEALTH_URL": os.environ.get("MODSTORE_PUBLIC_HEALTH_URL")
            or "https://xiu-ci.com/api/health",
        },
    )


def recover_release(request_id, state):
    """Called under Retort's cross-process run lock; unknown submissions are never replayed."""
    from modstore_server.integrations.repository_packages import load_repository_module
    from modstore_server.release_recovery_orchestrator import maybe_execute_recovery

    pending = {"status": "waiting_recovery", "request_id": request_id}
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        effects = json_loads(row.effects_json, {})
    policy = (effects.get("customer_feedback") or effects.get("training_candidate") or {}).get(
        "recovery"
    ) or {}
    if not policy:
        return _save(request_id, {**pending, "reason": "recovery_not_authorized"})
    contract = load_repository_module("retort_engine.evolution_contract")
    authorization, plan = effects.get("authorization") or {}, effects.get("plan") or {}
    if (
        authorization.get("approved") is not True
        or authorization.get("digest")
        != contract.digest(
            {
                "protocol": state["protocol"],
                "plan": plan,
                "optimization": effects.get("optimization"),
            }
        )
        or plan.get("feedback_policy", {}).get("recovery") != policy
        or state.get("impact", {}).get("status") != "customer_impact_rejected"
        or state.get("approval", {}).get("approved") is not True
        or state["approval"].get("digest") != contract.digest(state["verification"])
    ):
        return _save(request_id, {**pending, "reason": "recovery_approval_mismatch"})
    target, delivery = policy["target"], state["delivery"]
    expected = delivery.get("identity") or {}
    if (
        policy.get("mode") != "restore_previous_release"
        or delivery.get("status") != "deployment_verified"
        or expected.get("git_sha") != delivery.get("release_sha")
        or target.get("git_sha") == expected.get("git_sha")
    ):
        return _save(request_id, {**pending, "reason": "recovery_identity_mismatch"})
    try:
        BuildIdentity.from_payload(target).require_complete("recovery_target")
        BuildIdentity.from_payload(expected).require_complete("recovery_source")
        current = _release_identity()
    except (*RECOVERABLE_ERRORS, HTTPException):
        return _save(request_id, {**pending, "reason": "recovery_identity_unavailable"})
    identity_keys = ("git_sha", "artifact_sha256", "image_digest", "product_version", "release_id")
    same = lambda left, right: all(left.get(key, "") == right.get(key, "") for key in identity_keys)
    payload = {
        "request_id": f"retort:{request_id}:rollback",
        "expected_identity": expected,
        "target_identity": target,
        "reason": state["impact"].get("reason", "customer_impact_rejected"),
    }
    previous = effects.get("recovery") or {}
    if previous.get("recovery_request", payload) != payload:
        return _save(request_id, {**pending, "reason": "recovery_request_mismatch"})

    def confirm():
        # A switched current symlink/public process can coexist with a failed
        # scheduler or payment restart. Only the exact durable rollback receipt
        # plus fresh readback of every runtime surface can finish compensation.
        try:
            receipt = _read_recovery_receipt(payload)
        except (*RECOVERABLE_ERRORS, HTTPException) as exc:
            return _save(
                request_id,
                {
                    **pending,
                    "reason": "awaiting_recovery_readback",
                    "readback_error": str(exc)[:300],
                },
            )
        return _save(
            request_id,
            {
                "status": "rollback_verified",
                "request_id": request_id,
                "identity": receipt["identity"],
                "receipt": receipt,
                "reason": "",
                "readback_error": "",
                "verified_at": datetime.now(UTC).isoformat(),
            },
        )

    if same(current, target):
        return confirm()
    if not same(current, expected):
        return _save(request_id, {**pending, "reason": "active_release_changed"})
    if previous.get("submitted"):
        return _save(request_id, {**previous, **pending, "reason": "awaiting_recovery_readback"})
    if not os.environ.get("MODSTORE_AUTO_ROLLBACK_COMMAND", "").strip():
        return _save(request_id, {**pending, "reason": "recovery_command_not_configured"})
    claim = {
        **pending,
        "submitted": True,
        "submitted_at": datetime.now(UTC).isoformat(),
        "expected_identity": expected,
        "target_identity": target,
        "recovery_request": payload,
    }
    _save(request_id, claim)
    # The existing operator command receives a fixed CAS contract. It must compare
    # the deployed identity again on the target host before restoring the artifact.
    try:
        result = maybe_execute_recovery(
            event_id=int(row.event_id or 0),
            event_type="release.retort.feedback_rejected",
            payload={"priority": 100, **payload},
        )
        _save(request_id, {**claim, "execution": result})
        current = _release_identity()
        if same(current, target):
            return confirm()
    except (*RECOVERABLE_ERRORS, HTTPException) as exc:
        return _save(
            request_id,
            {**claim, "reason": "recovery_outcome_unknown", "error_type": type(exc).__name__},
        )
    return _save(request_id, {**claim, "reason": "awaiting_recovery_readback", "execution": result})
