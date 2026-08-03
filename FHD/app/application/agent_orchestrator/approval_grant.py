"""Short-lived, action-bound approval grants for Agent Run continuation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from typing import Any

import jwt

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep

logger = logging.getLogger(__name__)

_AUDIENCE = "xcagi-agent-approval"
_ISSUER = "xcagi-agent-runtime"
_ALGORITHM = "HS256"
_FALLBACK_SECRET = secrets.token_urlsafe(48)
_CONSUMED_JTIS: set[str] = set()
_CONSUMED_LOCK = threading.RLock()


class ApprovalGrantError(ValueError):
    pass


def _secret() -> str:
    secret = os.environ.get("SECRET_KEY", "").strip()
    if secret:
        return secret
    return _FALLBACK_SECRET


def _params_hash(step: AgentStep) -> str:
    canonical = json.dumps(step.params or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def waiting_step(run: AgentRun) -> AgentStep | None:
    return next((step for step in run.steps if step.status == "waiting_user"), None)


def issue_approval_grant(run: AgentRun, *, principal_id: str, ttl_seconds: int = 300) -> dict[str, Any] | None:
    step = waiting_step(run)
    if step is None:
        return None
    now = int(time.time())
    expires_at = now + max(30, min(int(ttl_seconds), 900))
    claims = {
        "aud": _AUDIENCE,
        "iss": _ISSUER,
        "typ": "agent_approval",
        "sub": str(principal_id),
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
        "tool_id": step.tool_id,
        "action": step.action,
        "params_sha256": _params_hash(step),
        "iat": now,
        "exp": expires_at,
        # Stable per principal/action revision: issuing the same approval screen twice
        # must not create two independently consumable grants for one side effect.
        "jti": hashlib.sha256(
            f"{principal_id}:{run.run_id}:{step.step_id}:{_params_hash(step)}".encode()
        ).hexdigest(),
    }
    return {
        "grant": jwt.encode(claims, _secret(), algorithm=_ALGORITHM),
        "run_id": run.run_id,
        "step_id": step.step_id,
        "tool_id": step.tool_id,
        "action": step.action,
        "expires_at": expires_at,
    }


def consume_approval_grant(token: str, *, run: AgentRun, principal_id: str) -> dict[str, Any]:
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
    expected = {
        "typ": "agent_approval",
        "sub": str(principal_id),
        "run_id": run.run_id,
        "step_id": step.step_id if step else "",
        "node_id": step.node_id if step else "",
        "tool_id": step.tool_id if step else "",
        "action": step.action if step else "",
        "params_sha256": _params_hash(step) if step else "",
    }
    if step is None or any(str(claims.get(key) or "") != value for key, value in expected.items()):
        raise ApprovalGrantError("approval_grant 与当前待审批步骤不匹配")

    jti = str(claims.get("jti") or "")
    with _CONSUMED_LOCK:
        if jti in _CONSUMED_JTIS:
            raise ApprovalGrantError("approval_grant 已使用")
        try:
            from app.utils.redis_cache import get_redis_cache

            cache = get_redis_cache()
            if getattr(cache, "is_available", False):
                ttl = max(1, int(claims.get("exp") or 0) - int(time.time()))
                if not cache.set(
                    f"agent_approval_used:{jti}",
                    "1",
                    ttl=ttl,
                    nx=True,
                    use_local=False,
                ):
                    raise ApprovalGrantError("approval_grant 已使用")
        except ApprovalGrantError:
            raise
        except Exception:  # noqa: BLE001 - Redis is optional; local replay guard remains
            logger.debug("approval grant Redis replay guard unavailable", exc_info=True)
        _CONSUMED_JTIS.add(jti)
    return claims


def clear_consumed_approval_grants_for_tests() -> None:
    with _CONSUMED_LOCK:
        _CONSUMED_JTIS.clear()


__all__ = [
    "ApprovalGrantError",
    "clear_consumed_approval_grants_for_tests",
    "consume_approval_grant",
    "issue_approval_grant",
]
