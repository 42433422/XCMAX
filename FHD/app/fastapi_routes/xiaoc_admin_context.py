"""Management XiaoC's existing bridge to its authenticated host account."""

from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import or_, select

from app.application.agent_task_context import scoped_personal_memory_id
from app.application.user_memory.retrieve import recall_authoritative_memories
from app.db import HostSessionLocal
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.domain.shared_services.user_memory_service import get_user_memory_service
from app.infrastructure.memory.mem0_backend import get_long_term_memory
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/internal/xiaoc-admin", include_in_schema=False)
_ADMIN_MEMORY_SURFACE = "xcmax-platform-admin-xiaoc"


class MemoryText(BaseModel):
    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)
    ]


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_user_id: int = Field(gt=0)
    operation: Literal[
        "recall",
        "list",
        "save",
        "correct",
        "delete",
        "capabilities",
        "enterprise_state",
        "execute_capability",
    ]
    query: str = Field(default="", max_length=800)
    memory_id: str = Field(default="", max_length=80)
    memory: MemoryText | None = None
    limit: int = Field(default=100, ge=1, le=500)
    tool_id: str = Field(default="", max_length=128)
    action: str = Field(default="", max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default="", max_length=200)


def _check_bridge_key(request: Request) -> None:
    expected = os.environ.get("XIAOC_ADMIN_CONTEXT_TOKEN", "").strip()
    got = request.headers.get("x-internal-api-key", "").strip()
    if not expected:
        raise HTTPException(503, "管理端小C上下文服务未配置")
    if not secrets.compare_digest(got.encode(), expected.encode()):
        raise HTTPException(403, "无权访问管理端小C上下文")


def _owner_record(market_user_id: int):
    from app.application.desktop_admin_gate import is_desktop_runtime

    if is_desktop_runtime():
        raise HTTPException(403, "桌面端不提供管理端小C上下文")
    now = utc_now_naive()
    conflicting_market_session = (
        select(UserSession.id)
        .where(
            UserSession.user_id == User.id,
            UserSession.market_user_id != market_user_id,
            UserSession.expires_at > now,
        )
        .correlate(User)
        .exists()
    )
    with HostSessionLocal() as db:
        matches = db.execute(
            select(User.id, User.tenant_id, User.market_user_id)
            .join(UserSession, UserSession.user_id == User.id)
            .where(
                UserSession.market_user_id == market_user_id,
                UserSession.market_is_admin.is_(True),
                UserSession.account_kind == "admin",
                UserSession.expires_at > now,
                UserSession.impersonating_market_user_id.is_(None),
                UserSession.tenant_id.is_not_distinct_from(User.tenant_id),
                or_(User.market_user_id.is_(None), User.market_user_id == market_user_id),
                User.is_active.is_(True),
                ~conflicting_market_session,
            )
            .distinct()
            .limit(2)
        ).all()
    if len(matches) != 1:
        raise HTTPException(403, "请使用同一管理员账号重新登录 XCAGI 管理端")
    return matches[0]


def _owner(market_user_id: int) -> tuple[str | None, str]:
    row = _owner_record(market_user_id)
    local_id = str(row.id)
    # Legacy session-only mappings may later belong to another market account.
    # Its scoped memories stay separate; a local Persona requires durable ownership.
    persona_user_id = local_id if row.market_user_id == market_user_id else None
    # Colon-separated scope is reserved; normal active Mod IDs cannot claim it.
    return persona_user_id, scoped_personal_memory_id(
        {
            "local_user_id": local_id,
            "tenant_id": row.tenant_id,
            "mod_id": f"{_ADMIN_MEMORY_SURFACE}:market:{market_user_id}",
        }
    )


def _execution_context(market_user_id: int) -> dict[str, Any]:
    """Resolve a live host session; the bridge never treats a user ID as a grant."""
    from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope

    owner = _owner_record(market_user_id)
    with HostSessionLocal() as db:
        session_id = db.execute(
            select(UserSession.session_id)
            .where(
                UserSession.user_id == owner.id,
                UserSession.market_user_id == market_user_id,
                UserSession.market_is_admin.is_(True),
                UserSession.account_kind == "admin",
                UserSession.expires_at > utc_now_naive(),
                UserSession.impersonating_market_user_id.is_(None),
                UserSession.tenant_id.is_not_distinct_from(owner.tenant_id),
            )
            .order_by(UserSession.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    if not session_id:
        raise HTTPException(403, "管理员登录会话已失效")
    try:
        binding = bind_agent_actor_scope(session_id=session_id, user_id=str(owner.id))
    except ValueError as exc:
        raise HTTPException(403, "管理员登录会话已失效") from exc
    return {
        "user_id": str(owner.id),
        "actor_id": str(owner.id),
        "local_user_id": str(owner.id),
        "tenant_id": str(owner.tenant_id or ""),
        "_actor_authorization": binding,
        "source": _ADMIN_MEMORY_SURFACE,
    }


def _capability_request(body: ContextRequest) -> dict:
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.capability_catalog import discover_capabilities
    from app.application.tools.registered_capabilities import execute_registered_capability
    from app.infrastructure.tenant_scope import owned_tenant_scope, tenant_scope

    context = _execution_context(body.market_user_id)
    if body.operation == "capabilities":
        return discover_capabilities(context, query=body.query, limit=body.limit)
    spec = get_tool_action_spec(body.tool_id, body.action)
    if spec is None:
        raise HTTPException(422, "请先查询当前账号可用的能力与参数")
    if body.operation == "enterprise_state" and not spec.read_only:
        raise HTTPException(422, "企业状态查询只允许已登记的只读能力")
    if body.operation == "execute_capability" and not body.request_id.strip():
        raise HTTPException(422, "执行能力需要原始请求标识")
    if body.request_id.strip():
        context["idempotency_key"] = body.request_id.strip()
    scope = (
        owned_tenant_scope(int(context["tenant_id"]))
        if context["tenant_id"]
        else tenant_scope(None)
    )
    with scope:
        result = execute_registered_capability(
            {"tool_id": body.tool_id, "action": body.action, "params": body.params},
            runtime_context=context,
        )
    receipt = json.loads(result)
    if not isinstance(receipt, dict):
        raise HTTPException(502, "能力执行回执格式无效")
    return receipt


def _view(record: dict) -> dict:
    value = record.get("value") or {}
    return {
        "memory_id": record["memory_id"],
        "key": record["key"],
        "statement": value.get("statement", "") if isinstance(value, dict) else str(value),
        "source": record.get("source"),
        "updated_at": record.get("updated_at"),
        "revision": record.get("revision"),
    }


def _recall(persona_user_id: str | None, owner: str, query: str) -> dict:
    from app.application.persona_style_inject import persona_style_for_user

    style = persona_style_for_user(int(persona_user_id)) if persona_user_id else ""
    hits = []
    if query.strip():
        try:
            index = get_long_term_memory()
            if index.enabled:
                hits = get_user_memory_service().filter_recalled_memories(
                    owner, index.recall(user_id=owner, query=query, limit=3)
                )
        except RECOVERABLE_ERRORS:
            logger.warning("admin XiaoC memory index unavailable", exc_info=True)
        if not hits:
            hits = recall_authoritative_memories(owner, query, limit=3)
    return {"style": style, "statements": [hit["content"][:600] for hit in hits[:3]]}


@router.post("/context")
def admin_context(body: ContextRequest, request: Request) -> dict:
    _check_bridge_key(request)
    if body.operation in {"capabilities", "enterprise_state", "execute_capability"}:
        return _capability_request(body)
    persona_user_id, owner = _owner(body.market_user_id)
    if body.operation == "recall":
        return _recall(persona_user_id, owner, body.query)
    service = get_user_memory_service()
    if body.operation == "list":
        return {
            "success": True,
            "memories": [_view(record) for record in service.list_memories(owner, status="active")],
        }
    if body.operation == "delete":
        result = service.delete_memory(owner, body.memory_id, reason="admin_xiaoc_user_request")
        if not result.get("success"):
            raise HTTPException(404, "记忆不存在")
        return {"success": True}
    if body.memory is None:
        raise HTTPException(422, "请填写标题和记忆内容")
    value = {"statement": body.memory.statement}
    if body.operation == "correct":
        result = service.correct_memory(
            owner,
            body.memory_id,
            key=body.memory.key,
            value=value,
            reason="admin_xiaoc_user_request",
        )
    else:
        proposed = service.propose_memory_candidate(
            owner,
            "episodic",
            body.memory.key,
            value,
            source="settings_ui",
            confidence=1.0,
            evidence=[{"source": "admin_xiaoc", "kind": "explicit_settings_entry"}],
        )
        if not proposed.get("success"):
            raise HTTPException(409, "无法保存这条记忆")
        result = service.confirm_memory_candidate(owner, proposed["candidate"]["memory_id"])
    if not result.get("success"):
        raise HTTPException(404, "记忆不存在或无法再编辑")
    return {"success": True, "memory": _view(result["memory"])}
