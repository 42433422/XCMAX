"""Evidence-scoped, read-only functional self model for management XiaoC.

The lifecycle ledger remains authoritative. Registry entries and LLM opinions
are not capability proofs; the independent identity check is deliberately narrow.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from modstore_server.xiaoc_life_policy import IDENTITY_ID, parse_time, utcnow


class IdentityProof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    capability: Literal["identity_readback"] = "identity_readback"
    scope: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["pass", "fail"]
    checked_at: str
    method: Literal["sql_identity_readback"] = "sql_identity_readback"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def release_identity() -> dict[str, str | None]:
    """Use the immutable release controller's actual identity, not a model label."""
    sha = os.environ.get("MODSTORE_GIT_SHA", "")
    expected = os.environ.get("MODSTORE_EXPECTED_GIT_SHA", "")
    artifact = os.environ.get("MODSTORE_RELEASE_ARTIFACT_SHA256", "")
    valid = bool(re.fullmatch(r"[0-9a-f]{40}", sha) and sha == expected)
    return {
        "git_sha": sha if valid else None,
        "artifact_sha256": artifact if valid and re.fullmatch(r"[0-9a-f]{64}", artifact) else None,
        "product_version": os.environ.get("XCMAX_PRODUCT_VERSION") or None,
    }


def execution_scope(
    state: dict[str, Any], *, now: datetime | None = None, owner_active: bool | None = None
) -> str | None:
    """Bind observations to a release, observed host and authorization revision.

    This is not an attestation of every dependency or of model/employee competence.
    Unknown release identity prevents promotion of any independent check.
    """
    release = release_identity()
    if not release["git_sha"] or not release["artifact_sha256"]:
        return None
    if state.get("identity_id") != IDENTITY_ID or type(state.get("revision")) is not int:
        return None
    if owner_active is None:
        owner_active = state.get("self_authority_active")
    if state.get("owner_user_id") is not None and type(owner_active) is not bool:
        return None
    policy = state.get("policy") or {}
    expiry = policy.get("authorization_expires_at")
    try:
        unexpired = bool(expiry and parse_time(expiry) > (now or utcnow()))
    except (ValueError, TypeError):
        return None
    return _digest(
        [
            release,
            platform.node(),
            platform.system(),
            platform.machine(),
            sys.version,
            os.environ.get("MODSTORE_DEPLOY_TIER", ""),
            state["identity_id"],
            state["revision"],
            state.get("owner_user_id"),
            bool(owner_active),
            state.get("level"),
            state.get("paused"),
            expiry,
            unexpired,
        ]
    )


def current_identity_evidence(
    scope: str | None, events: list[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, Any]:
    """Use the newest bound SQL check; conflicting proofs fail closed."""
    now = now or utcnow()
    latest: tuple[datetime, str, str] | None = None
    seen: dict[str, tuple[datetime, str]] = {}
    conflicting = False
    for event in events:
        event_id = event.get("id")
        if (
            event.get("kind") != "self_identity_check"
            or not isinstance(event_id, str)
            or not event_id.startswith("self-check:")
        ):
            continue
        try:
            proof = IdentityProof.model_validate(event["details"]["identity_proof"])
            checked = parse_time(proof.checked_at)
        except (KeyError, TypeError, ValueError, ValidationError):
            continue
        if (
            not scope
            or proof.scope != scope
            or not timedelta(0) <= now - checked <= timedelta(hours=24)
            or event.get("status") != proof.verdict
        ):
            continue
        candidate = (checked, proof.verdict)
        previous = seen.setdefault(event_id, candidate)
        if previous != candidate:
            conflicting = True
            continue
        if latest is None or checked > latest[0]:
            latest = (checked, proof.verdict, event_id)
        elif checked == latest[0] and latest[1] != proof.verdict:
            conflicting = True
    if conflicting:
        return {"status": "unverified", "reason": "conflicting_identity_proofs"}
    if latest is not None:
        checked, verdict, evidence_ref = latest
        return {
            "status": "verified" if verdict == "pass" else "unavailable",
            "reason": "independent_sql_identity_readback",
            "scope": "persistent_identity_only",
            "evidence_ref": evidence_ref,
            "checked_at": checked.isoformat(),
        }
    return {"status": "unverified", "reason": "no_current_independent_identity_check"}


def performance(scope: str | None, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Only exact-scope original cycle receipts; no business-success inference."""
    counts: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    tokens = 0
    unknown_tokens = 0
    historical = 0
    models: Counter[str] = Counter()
    from modstore_server.xiaoc_self_metrics import consistent_cycle_receipts

    consistent, conflicting = consistent_cycle_receipts(events)
    for row in consistent:
        details = row.get("details") or {}
        if not scope or details.get("execution_scope") != scope:
            historical += 1
            continue
        status = str(row.get("status") or "unknown")
        counts[status] += 1
        if status in {"failed", "blocked", "interrupted"}:
            # Do not copy raw exceptions or private text into shared cognition.
            reason = str(details.get("reason") or "unspecified")
            failures[reason if re.fullmatch(r"[A-Za-z0-9_]{1,80}", reason) else "other"] += 1
        actual = row.get("actual_tokens")
        if type(actual) is int and actual >= 0:
            tokens += actual
        else:
            unknown_tokens += 1
        if isinstance(row.get("model"), str) and row["model"]:
            models[row["model"]] += 1
    measured = counts["completed"] + counts["failed"]
    return {
        "sample": "recent_original_cycle_receipts_not_business_or_capability_success",
        "current_scope_count": sum(counts.values()),
        "historical_or_unbound_count": historical,
        "conflicting_cycle_receipts": conflicting,
        "statuses": dict(counts),
        "failure_types": dict(failures),
        "model_sample_counts": dict(models),
        "cycle_completion_rate": counts["completed"] / measured if measured else None,
        "known_tokens": tokens,
        "unknown_token_receipts": unknown_tokens,
        "cost_cents": None,
        "cost_status": "not_aggregated_without_disjoint_cost_receipts",
    }


def project(state: dict[str, Any]) -> dict[str, Any]:
    scope = execution_scope(state)
    from modstore_server.xiaoc_self_metrics import completion_review

    events = state.get("self_cycle_receipts", state.get("events", []))
    proof_events = state.get("self_identity_checks", state.get("events", []))
    budget = state.get("budget") or {}
    policy = state.get("policy") or {}
    return {
        "schema": "xcmax.functional-self/v1",
        "identity": {
            "id": state.get("identity_id"),
            "role": "enterprise_management_assistant",
            "responsibility": state.get("mission"),
            "policy_revision": state.get("revision"),
            "level": state.get("level"),
            "paused": state.get("paused"),
            "release": release_identity(),
        },
        "execution_scope": scope,
        "identity_readback": current_identity_evidence(scope, proof_events),
        "self_assessment": {"status": "hypothesis_not_capability_proof"},
        "historical_evaluations": historical_evaluations(state.get("self_promptfoo_checks", [])),
        "performance": performance(scope, events),
        "performance_review": completion_review(scope, events),
        "performance_source": state.get("self_metrics_source", "recent_lifecycle_events"),
        "resources": {
            "daily_token_limit": policy.get("daily_token_limit"),
            "used_tokens": budget.get("used_tokens"),
            "reserved_tokens": budget.get("reserved_tokens"),
            "unknown_usage": state.get("unknown_usage"),
            "authorization_expires_at": policy.get("authorization_expires_at"),
        },
        "limits": [
            "registry_is_not_independent_test",
            "historical_domain_audit_is_not_current_capability",
            "no_subjective_consciousness_claim",
        ],
    }


def cognition_projection(state: dict[str, Any]) -> dict[str, Any]:
    snapshot = project(state)
    return {
        "identity": snapshot["identity"]["id"],
        "version": snapshot["identity"]["release"]["git_sha"],
        "identity_check": snapshot["identity_readback"]["status"],
        "current_receipts": snapshot["performance"]["current_scope_count"],
        "historical_receipts": snapshot["performance"]["historical_or_unbound_count"],
        "completion_review": snapshot["performance_review"]["status"],
        "rule": "registry and history do not prove current mastery",
    }


def employee_preflight(employee_id: str, owner: int) -> dict[str, str]:
    """Inspect the existing local employee resolver without executing the employee."""
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.employee_runtime import (
        employee_pack_runtime_issues,
        load_employee_pack_resolved,
    )

    if not employee_id or type(owner) is not int or owner <= 0:
        return {"status": "unavailable", "reason": "employee_or_owner_missing"}
    try:
        with get_session_factory()() as session:
            pack = load_employee_pack_resolved(session, employee_id, user_id=owner, execute=True)
            if employee_pack_runtime_issues(pack):
                return {"status": "unavailable", "reason": "employee_runtime_preflight_failed"}
    except PermissionError:
        return {"status": "unavailable", "reason": "employee_access_denied"}
    except ValueError:
        return {"status": "unavailable", "reason": "employee_pack_missing_or_invalid"}
    except (SQLAlchemyError, OSError):
        return {"status": "unknown", "reason": "employee_source_unavailable"}
    return {"status": "registered_unverified", "reason": "registry_and_runtime_preflight_only"}


def _bounded(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "observed_registry_not_capability_proof",
        "items": items[:200],
        "truncated": len(items) > 200,
    }


def registry_inventory(state: dict[str, Any], admin: Any) -> dict[str, Any]:
    """Read existing admin-visible registries, never run tools, skills or employees."""
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.employee_api_support import (
        _employee_id_from_list_row,
        _list_duty_employee_rows,
    )
    from modstore_server.employee_executor import list_employees
    from modstore_server.models import ESkill
    from modstore_server.xiaoc_life_chat import butler_tools_for_user

    tools = sorted({tool["function"]["name"] for tool in butler_tools_for_user(admin)})
    result: dict[str, Any] = {
        "tools": _bounded([{"id": name, "status": "registered_unverified"} for name in tools])
    }
    try:
        rows = [*list_employees(), *_list_duty_employee_rows()]
        employees = {
            _employee_id_from_list_row(row): {
                "id": _employee_id_from_list_row(row),
                "version": str(row.get("version") or ""),
                "status": (
                    "planned_unverified"
                    if row.get("manifest_registered") is False
                    else "registered_unverified"
                ),
            }
            for row in rows
            if _employee_id_from_list_row(row)
        }
        result["employees"] = _bounded([employees[key] for key in sorted(employees)])
    except (SQLAlchemyError, OSError, ValueError):
        result["employees"] = {"status": "unknown", "reason": "employee_registry_unavailable"}
    try:
        with get_session_factory()() as session:
            skills = session.execute(
                select(ESkill.id, ESkill.active_version)
                .where(ESkill.domain == "butler")
                .order_by(ESkill.id)
                .limit(201)
            ).all()
        result["skills"] = _bounded(
            [
                {"id": f"eskill_{key}", "version": str(version), "status": "registered_unverified"}
                for key, version in skills
            ]
        )
    except SQLAlchemyError:
        result["skills"] = {"status": "unknown", "reason": "skill_registry_unavailable"}
    selected = (state.get("policy") or {}).get("employee_id")
    owner = state.get("owner_user_id")
    if selected and type(owner) is int:
        result["configured_employee"] = employee_preflight(selected, owner)
    return result


async def model_inventory() -> dict[str, Any]:
    from fastapi import HTTPException

    from modstore_server.llm_runtime_route import platform_model_catalog

    try:
        catalog = await asyncio.wait_for(platform_model_catalog(refresh=False), timeout=10)
    except (SQLAlchemyError, OSError, HTTPException, TimeoutError):
        return {"status": "unknown", "reason": "model_catalog_unavailable"}
    if not catalog.get("ok"):
        return {"status": "unknown", "reason": "model_catalog_unavailable"}
    items = [
        {
            "provider": row["provider"],
            "id": model,
            "status": "registered_unverified",
        }
        for row in catalog.get("providers", [])
        if row.get("configured") and not row.get("error")
        for model in row.get("runtime_models", [])
    ]
    result = _bounded(items)
    result["partial"] = any(
        row.get("configured") and row.get("error") for row in catalog.get("providers", [])
    )
    return result


def record_identity_check(*, only_if_due: bool = False) -> dict[str, Any]:
    """Independent SQL check; never accepts a verdict or scope from the model."""
    from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
    from modstore_server.xiaoc_life_store import _active_principal, _event, _event_dict, _mutate

    def check(data: dict[str, Any], session: Any) -> dict[str, Any]:
        now = utcnow()
        scope = execution_scope(
            data, now=now, owner_active=_active_principal(session, data.get("owner_user_id"))
        )
        if not scope:
            return {"status": "unverified", "reason": "immutable_release_identity_missing"}
        if only_if_due:
            previous = [
                _event_dict(row)
                for row in session.scalars(
                    select(XiaoCLifeEvent)
                    .where(
                        XiaoCLifeEvent.identity_id == IDENTITY_ID,
                        XiaoCLifeEvent.kind == "self_identity_check",
                    )
                    .order_by(XiaoCLifeEvent.created_at.desc(), XiaoCLifeEvent.id.desc())
                    .limit(20)
                )
            ]
            evidence = current_identity_evidence(scope, previous, now=now)
            if evidence["status"] != "unverified":
                return {"status": "not_due", "evidence_ref": evidence["evidence_ref"]}
        actual = session.execute(
            select(XiaoCLifeState.identity_id, XiaoCLifeState.state_json).where(
                XiaoCLifeState.identity_id == IDENTITY_ID
            )
        ).one()
        stored = json.loads(actual.state_json)
        passed = (
            actual.identity_id == IDENTITY_ID
            and stored.get("identity_id") == IDENTITY_ID
            and stored.get("revision") == data.get("revision")
            and stored.get("owner_user_id") == data.get("owner_user_id")
        )
        proof = IdentityProof(
            scope=scope,
            verdict="pass" if passed else "fail",
            checked_at=now.isoformat(),
        )
        event_id = "self-check:" + uuid.uuid4().hex
        _event(
            session,
            event_id,
            kind="self_identity_check",
            status=proof.verdict,
            summary="独立 SQL 身份回读，仅证明当前持久身份合同。",
            evidence_refs=["identity:" + IDENTITY_ID],
            details={"identity_proof": proof.model_dump()},
        )
        return {"status": proof.verdict, "evidence_ref": event_id}

    return _mutate(check)


def historical_evaluations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Offline training outputs have no immutable deployment identity in the
    # existing bundle schema. They remain historical even if imported today.
    return [
        {
            "status": "historical_measurement_not_current_capability",
            "evidence_ref": row["id"],
            **{
                k: row["details"][k]
                for k in ("engine", "baseline", "candidate", "bundle_sha256", "results_sha256")
            },
        }
        for row in events
        if row.get("kind") == "self_promptfoo_check"
        and row.get("status") == "historical_measurement"
        and isinstance(row.get("details"), dict)
        and all(
            k in row["details"]
            for k in ("engine", "baseline", "candidate", "bundle_sha256", "results_sha256")
        )
    ][:20]


def record_promptfoo_measurement(bundle_path: Path, result_path: Path) -> dict[str, Any]:
    """Operator-only import of a sealed offline employee prompt comparison.

    Never promote a candidate, run a task or label it a current capability.
    Structured/business replay is intentionally excluded from this read-only import.
    """
    from modstore_server.capability_trainer import seal_evaluation
    from modstore_server.db.xiaoc_life import XiaoCLifeEvent
    from modstore_server.xiaoc_life_store import _event, _mutate

    bundle = json.loads(bundle_path.read_bytes())
    if bundle.get("surface", "employee_prompt") != "employee_prompt":
        raise ValueError("self_model_requires_offline_employee_prompt_comparison")
    sealed = seal_evaluation(bundle_path, result_path)
    metrics = {}
    for arm in ("baseline", "candidate"):
        row = sealed.get(arm)
        if (
            not isinstance(row, dict)
            or type(row.get("pass")) is not int
            or type(row.get("total")) is not int
            or not 0 <= row["pass"] <= row["total"]
            or row["total"] <= 0
        ):
            raise ValueError("self_model_promptfoo_measurement_incomplete")
        metrics[arm] = {"pass": row["pass"], "total": row["total"]}
    if metrics["baseline"]["total"] != metrics["candidate"]["total"]:
        raise ValueError("self_model_promptfoo_measurement_unpaired")
    details = {
        **metrics,
        **{k: sealed[k] for k in ("engine", "bundle_sha256", "results_sha256")},
        "evaluation_release_status": "unbound_historical_only",
    }
    event_id = "self-promptfoo:" + _digest(details)

    def record(_data: dict[str, Any], session: Any) -> dict[str, Any]:
        if session.get(XiaoCLifeEvent, event_id) is None:
            _event(
                session,
                event_id,
                kind="self_promptfoo_check",
                status="historical_measurement",
                summary="离线成对回归测量，不能证明当前版本能力或授权上线。",
                evidence_refs=[
                    "sha256:" + details["bundle_sha256"],
                    "sha256:" + details["results_sha256"],
                ],
                details=details,
            )
        return {"status": "historical_measurement", "evidence_ref": event_id}

    return _mutate(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--promptfoo", nargs=2, type=Path, metavar=("BUNDLE", "RESULT"))
    group.add_argument("--audit-fixture", nargs=2, type=Path, metavar=("REPORT", "SSOT"))
    args = parser.parse_args()
    if args.promptfoo:
        result = record_promptfoo_measurement(*args.promptfoo)
    elif args.audit_fixture:
        from modstore_server.xiaoc_self_evidence import record_fixture_report

        result = record_fixture_report(*args.audit_fixture)
    else:
        result = record_identity_check()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
