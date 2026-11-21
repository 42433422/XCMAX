"""Short-lived, action-bound approval grants for Agent Run continuation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from typing import Any

import jwt
from sqlalchemy.exc import SQLAlchemyError

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep

logger = logging.getLogger(__name__)

_AUDIENCE = "xcagi-agent-approval"
_ISSUER = "xcagi-agent-runtime"
_ALGORITHM = "HS256"
_FALLBACK_SECRET = secrets.token_urlsafe(48)
_EVIDENCE_KEY = "_tool_approval_grants"


class ApprovalGrantError(ValueError):
    pass


class ApprovalGrantStorageError(ApprovalGrantError):
    pass


def _consumption_repository():
    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )
    from app.db import HostSessionLocal

    return SQLAlchemyApprovalConsumptionRepository(HostSessionLocal)


def _secret() -> str:
    secret = os.environ.get("SECRET_KEY", "").strip()
    if secret:
        return secret
    return _FALLBACK_SECRET


def _approval_digest(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _params_hash(step: AgentStep) -> str:
    return _approval_digest(step.params or {})


def _scope_claims(run: AgentRun, step: AgentStep) -> dict[str, str]:
    context = dict(run.metadata.get("runtime_context") or {})
    if not isinstance(context.get("_actor_authorization"), dict):
        context["user_id"] = run.user_id
    return execution_scope_claims(context, step.tool_id, step.action)


def authorization_scope_hash(context: dict[str, Any]) -> str:
    from app.infrastructure.workspace import workspace_root

    scope = {
        key: context.get(key)
        for key in (
            "user_id",
            "actor_id",
            "tenant_id",
            "mod_id",
            "active_mod_id",
            "employee_id",
            "employee_tool_allowlist",
            "mutation_policy",
            "_bulk_preview_scope",
            "_bulk_preview_scopes",
            "workspace_root",
            "workspace_id",
            "workspace_path",
        )
    }
    # The executor always rebinds this field from server configuration. Bind the
    # same effective root, including for old runs with a stale serialized path.
    scope["workspace_root"] = str(workspace_root())
    preview, previews = scope["_bulk_preview_scope"], scope["_bulk_preview_scopes"]
    if (
        isinstance(preview, dict)
        and isinstance(previews, dict)
        and set(preview) == {"tool", "digest"}
        and preview.get("tool") in previews
        and preview.get("digest") == previews[preview["tool"]]
    ):
        # The executor derives this single-tool view from the approved batch
        # map before its transactional guard rechecks the same authorization.
        scope["_bulk_preview_scope"] = None
    # Session renewal is allowed only for the same identity. The live executor
    # still revalidates the renewed session and its proof before every attempt.
    for name, fields in {
        "_actor_authorization": (
            "user_id",
            "tenant_id",
            "execution_tenant_id",
            "role",
            "tier",
            "mod_id",
        ),
        "_mod_authorization": (
            "user_id",
            "mod_id",
            "account_tenant_id",
            "account_role",
        ),
    }.items():
        binding = context.get(name)
        scope[name] = (
            {key: binding.get(key) for key in fields} if isinstance(binding, dict) else binding
        )
    return _approval_digest(scope)


def execution_scope_claims(context: dict[str, Any], tool_id: str, action: str) -> dict[str, str]:
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    spec = get_tool_action_spec(tool_id, action)
    contract = (
        {
            key: getattr(spec, key)
            for key in (
                "version",
                "owner_mod_id",
                "permission",
                "risk",
                "read_only",
                "idempotent",
                "input_schema",
                "output_schema",
                "retry",
                "timeout_seconds",
                "required_params",
                "availability",
            )
        }
        if spec is not None
        else None
    )
    return {
        "authorization_scope_sha256": authorization_scope_hash(context),
        "tool_contract_sha256": _approval_digest(contract),
        "tool_version": spec.version if spec is not None else "",
    }


def approval_receipt_claims(
    run: AgentRun, step: AgentStep, *, claims: dict[str, Any] | None = None
) -> dict[str, str]:
    expected = {"params_sha256": _params_hash(step)}
    if step.tool_id != "catalog_products_v1":
        expected.update(_scope_claims(run, step))
    return expected if claims is None else {key: str(claims.get(key) or "") for key in expected}


def approval_scope_matches(run: AgentRun, step: AgentStep) -> bool:
    if step.tool_id == "catalog_products_v1":
        # The catalog validates its consumed original grant in its own transaction.
        return True
    receipt = run.metadata.get("approval_receipt")
    return isinstance(receipt, dict) and all(
        receipt.get(key) == value
        for key, value in {
            "step_id": step.step_id,
            "tool_id": step.tool_id,
            "action": step.action,
            **approval_receipt_claims(run, step),
        }.items()
    )


def _action_claims(run: AgentRun, step: AgentStep, principal_id: str) -> dict[str, str]:
    """Derive immutable approval identity; this is not live business admission.

    Catalog historical verification deliberately excludes the session row/expiry:
    an authentic grant consumed in time remains evidence after session retirement.
    Current execution and pending reconciliation separately revalidate their actor.
    """
    claims = {
        "typ": "agent_approval",
        "sub": str(principal_id),
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
        "tool_id": step.tool_id,
        "action": step.action,
        "params_sha256": _params_hash(step),
    }
    if step.tool_id != "catalog_products_v1":
        claims.update(_scope_claims(run, step))
        return claims
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    spec = get_tool_action_spec(step.tool_id, step.action)
    context = run.metadata.get("runtime_context") or {}
    actor = context.get("_actor_authorization") or {}
    binding = run.metadata.get("catalog_price_binding")
    digest = run.metadata.get("catalog_operation_digest")
    tenant, mod = str(context.get("tenant_id") or ""), str(context.get("mod_id") or "")
    if (
        step.action not in {"append_price", "correct_price"}
        or spec is None
        or not spec.version
        or not isinstance(binding, dict)
        or not binding
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or not tenant
        or not mod
        or run.user_id != str(principal_id)
        or actor.get("user_id") != str(principal_id)
        or actor.get("execution_tenant_id") != tenant
        or actor.get("mod_id") != mod
    ):
        raise ApprovalGrantError("目录审批原始操作身份不完整")

    claims.update(
        business_action_id=f"agent:{run.run_id}:{step.step_id}",
        tenant_id=tenant,
        mod_id=mod,
        owner_mod_id=spec.owner_mod_id,
        tool_version=spec.version,
        actor_scope_sha256=_approval_digest(
            {
                key: actor.get(key)
                for key in (
                    "user_id",
                    "tenant_id",
                    "execution_tenant_id",
                    "role",
                    "tier",
                    "mod_id",
                )
            }
        ),
        source_binding_sha256=_approval_digest(binding),
        operation_digest=digest,
    )
    return claims


def waiting_step(run: AgentRun) -> AgentStep | None:
    return next((step for step in run.steps if step.status == "waiting_user"), None)


def issue_approval_grant(
    run: AgentRun, *, principal_id: str, ttl_seconds: int = 300
) -> dict[str, Any] | None:
    step = waiting_step(run)
    if step is None:
        return None
    now = int(time.time())
    expires_at = now + max(30, min(int(ttl_seconds), 900))
    action_claims = _action_claims(run, step, principal_id)
    claims = {
        "aud": _AUDIENCE,
        "iss": _ISSUER,
        **action_claims,
        "iat": now,
        "exp": expires_at,
        # Stable per principal/action revision: issuing the same approval screen twice
        # must not create two independently consumable grants for one side effect.
        "jti": (
            hashlib.sha256(
                f"{principal_id}:{run.run_id}:{step.step_id}:{_params_hash(step)}".encode()
            ).hexdigest()
            if step.tool_id == "catalog_products_v1"
            else _approval_digest(action_claims)
        ),
    }
    return {
        "grant": jwt.encode(claims, _secret(), algorithm=_ALGORITHM),
        "run_id": run.run_id,
        "step_id": step.step_id,
        "tool_id": step.tool_id,
        "action": step.action,
        "expires_at": expires_at,
    }


def validate_approval_grant(token: str, *, run: AgentRun, principal_id: str) -> dict[str, Any]:
    if not str(token or "").strip():
        raise ApprovalGrantError("缺少 approval_grant")
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            options={"require": ["exp", "aud", "iss", "sub", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise ApprovalGrantError("approval_grant 无效或已过期") from exc

    step = waiting_step(run)
    expected = _action_claims(run, step, principal_id) if step else {}
    if step is None or any(str(claims.get(key) or "") != value for key, value in expected.items()):
        raise ApprovalGrantError("approval_grant 与当前待审批步骤不匹配")

    return claims


def consume_approval_grant(token: str, *, run: AgentRun, principal_id: str) -> dict[str, Any]:
    claims = validate_approval_grant(token, run=run, principal_id=principal_id)
    jti = str(claims.get("jti") or "")
    try:
        consumed = _consumption_repository().consume(
            jti=jti, run_id=run.run_id, step_id=str(claims["step_id"])
        )
    except (SQLAlchemyError, OSError) as exc:
        logger.exception("approval consumption storage unavailable")
        raise ApprovalGrantStorageError("审批存储暂时不可用，请稍后重试") from exc
    if not consumed:
        raise ApprovalGrantError("approval_grant 已使用")
    return claims


def clear_consumed_approval_grants_for_tests() -> None:
    """Compatibility no-op: durable consumption can only reset via an isolated test DB."""


__all__ = [
    "ApprovalGrantError",
    "ApprovalGrantStorageError",
    "clear_consumed_approval_grants_for_tests",
    "consume_approval_grant",
    "issue_approval_grant",
    "validate_approval_grant",
]
