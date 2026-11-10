"""Chat turn decisions: displayable model text, bulk-delete preview, and idempotent retry.

The desktop session probe and agent-run polls abort at 8s and must not be treated as
the model call. This module decides whether a turn may mutate, independent of that timer.
"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.utils.operational_errors import RECOVERABLE_ERRORS

_POLICY: ContextVar[str] = ContextVar("xcagi_chat_mutation_policy", default="allow")

_BULK_ACTION = re.compile(r"(清理|删除|清空|清除).{0,16}(全部|所有|全量)")
_BULK_TARGET = re.compile(r"客户|产品|订单|资料|数据")
_MUTATION = re.compile(
    r"delete|clear|remove|drop|update|create|write|insert|upsert|清理|删除|清空|写入", re.IGNORECASE
)
_READ_ONLY = re.compile(r"(query|list|search|read|get|count|status|preview|schema)", re.IGNORECASE)
_LEDGER: dict[str, TurnRecord] = {}


@dataclass
class TurnRecord:
    key: str
    intent: str
    committed: bool
    effect: str
    summary: str
    tenant_id: str
    customer_count: int | None
    product_count: int | None


def reset_turn_ledger() -> None:
    _LEDGER.clear()
    release_mutation_policy()


def mutation_policy() -> str:
    return _POLICY.get()


def release_mutation_policy() -> None:
    _POLICY.set("allow")


def _use_policy(policy: str) -> None:
    _POLICY.set(policy)


def _piece(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "output_text"):
            child = value.get(key)
            if isinstance(child, str):
                return child
        return ""
    if isinstance(value, list):
        return "".join(_piece(item) for item in value)
    return ""


def displayable_text(value: Any) -> str:
    """Text a person can read. Reasoning traces and mock objects are not a body."""
    if value is None or isinstance(value, (str, list, dict, int, float, bool)):
        return _piece(value)
    return "".join(_piece(getattr(value, key, None)) for key in ("content", "text", "output_text"))


def chunk_display_text(choice: Any) -> str:
    """Prefer the streamed delta, then a final message body. Ignore reasoning-only frames."""
    if choice is None:
        return ""
    for source in (getattr(choice, "delta", None), getattr(choice, "message", None)):
        text = displayable_text(source)
        if text:
            return text
    return displayable_text(choice)


def joined_display_text(parts: list[str]) -> str | None:
    body = "".join(parts)
    if not body.strip():
        return None
    return body


def is_bulk_destructive(message: str) -> bool:
    text = str(message or "").strip()
    return bool(text and _BULK_ACTION.search(text) and _BULK_TARGET.search(text))


def _tenant(ctx: dict[str, Any]) -> str:
    return str(ctx.get("tenant_id") or "未确认")


def scope_counts(ctx: dict[str, Any]) -> tuple[int | None, int | None]:
    """Count the same tenant-scoped entities the batch-delete tools operate on."""
    try:
        from sqlalchemy import func

        from app.application.agent_orchestrator.tool_permission import actor_tool_denial
        from app.db.models import Product
        from app.db.models.purchase_unit import PurchaseUnit
        from app.db.session import get_db
        from app.infrastructure.auth.agent_mod_scope import _bound_actor

        _bound_actor(ctx)
        tenant = int(ctx.get("tenant_id") or 0)
        if tenant <= 0:
            return None, None
        with get_db() as db:
            counts: list[int | None] = []
            for tool, model in (("customers", PurchaseUnit), ("products", Product)):
                if actor_tool_denial(tool, "query", ctx) is not None:
                    counts.append(None)
                else:
                    counts.append(
                        int(
                            db.query(func.count(model.id))
                            .filter(model.tenant_id == tenant)
                            .scalar()
                            or 0
                        )
                    )
        return counts[0], counts[1]
    except SQLAlchemyError:
        return None, None
    except RECOVERABLE_ERRORS:
        return None, None


def _count_phrase(count: int | None) -> str:
    return f"{count} 条" if count is not None else "数量未能读取"


def preview_message(
    ctx: dict[str, Any], message: str, *, customers: int | None, products: int | None
) -> str:
    scopes = []
    if "客户" in message:
        scopes.append(f"客户 {_count_phrase(customers)}")
    if "产品" in message:
        scopes.append(f"产品 {_count_phrase(products)}")
    scope = "，".join(scopes) or "尚未确定，请明确客户或产品"
    tenant = _tenant(ctx) if customers is not None or products is not None else "未核验"
    return f"这是删除预览，尚未写入。\n租户：{tenant}。\n范围：{scope}。\n未确认前不会删除或写入。"


def execution_payload(record: TurnRecord) -> dict[str, Any]:
    return {
        "idempotency_key": record.key,
        "intent": record.intent,
        "committed": record.committed,
        "effect": record.effect,
        "tenant_id": record.tenant_id,
        "customer_count": record.customer_count,
        "product_count": record.product_count,
    }


def _remember(record: TurnRecord) -> dict[str, Any]:
    if record.key:
        _LEDGER[record.key] = record
    return {
        "success": record.effect != "none" or record.intent == "bulk_destructive",
        "response": record.summary,
        "text": record.summary,
        "message": record.summary,
        "execution": execution_payload(record),
    }


def _key(ctx: dict[str, Any]) -> str:
    return str(ctx.get("idempotency_key") or ctx.get("turn_id") or "").strip()


def execution_for_context(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """The turn's intent-versus-commit record, when this request has one."""
    if not isinstance(ctx, dict):
        return None
    key = _key(ctx)
    record = _LEDGER.get(key) if key else None
    return execution_payload(record) if record else None


def prepare_turn(message: str, ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Stamp mutation policy. Return a reply when the model must not be asked to write."""
    key = _key(ctx)
    retry = bool(str(ctx.get("retry_of") or "").strip())
    confirmed = ctx.get("destructive_confirmed") is True and bool(key)
    bulk = is_bulk_destructive(message)
    existing = _LEDGER.get(key) if key else None
    if retry:
        _use_policy("model_only")
        return None
    if existing and existing.committed:
        _use_policy("model_only")
        return _remember(existing)
    if bulk and not confirmed:
        customers, products = scope_counts(ctx)
        text = preview_message(ctx, message, customers=customers, products=products)
        record = TurnRecord(
            key, "bulk_destructive", False, "preview", text, _tenant(ctx), customers, products
        )
        _use_policy("block")
        return _remember(record)
    if bulk and confirmed:
        if existing and existing.effect == "opened":
            _use_policy("model_only")
            text = "上一轮没有提交写入。这次只会重新请求模型，不会执行删除。"
            return {
                "success": True,
                "response": text,
                "text": text,
                "message": text,
                "execution": execution_payload(
                    TurnRecord(
                        key,
                        "bulk_destructive",
                        False,
                        "none",
                        text,
                        existing.tenant_id,
                        existing.customer_count,
                        existing.product_count,
                    )
                ),
            }
        customers, products = scope_counts(ctx)
        record = TurnRecord(
            key, "bulk_destructive", False, "opened", "", _tenant(ctx), customers, products
        )
        if key:
            _LEDGER[key] = record
        _use_policy("allow_once")
        return None
    _use_policy("allow")
    return None


def _is_mutation(name: str, raw_args: str) -> bool:
    blob = f"{name} {raw_args}"
    if _MUTATION.search(blob):
        return True
    if _READ_ONLY.search(name) and not _MUTATION.search(name):
        return False
    try:
        parsed = json.loads(raw_args) if raw_args.strip() else {}
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict) and (
        parsed.get("all") is True or str(parsed.get("scope") or "") in {"all", "tenant"}
    ):
        return True
    return not bool(_READ_ONLY.search(name))


def mutation_block(name: str, raw_args: str, runtime_context: Any) -> dict[str, Any] | None:
    if not _is_mutation(name, raw_args):
        return None
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    policy = str(ctx.get("mutation_policy") or "") or _POLICY.get()
    key = _key(ctx)
    existing = _LEDGER.get(key) if key else None
    if existing and existing.committed:
        return {
            "success": False,
            "committed": True,
            "error": "already_committed",
            "message": "该操作已经提交过，不会再次执行。",
        }
    if policy in {"block", "model_only"}:
        return {
            "success": False,
            "committed": False,
            "error": "mutation_blocked",
            "message": "未授权或本轮只重试模型，未执行写入。",
        }
    return None


def note_tool_commit(runtime_context: Any, name: str) -> None:
    policy = (
        str(runtime_context.get("mutation_policy") or "")
        if isinstance(runtime_context, dict)
        else ""
    )
    if (policy or _POLICY.get()) != "allow_once":
        return
    key = _key(runtime_context)
    if not key:
        return
    current = _LEDGER.get(key)
    summary = f"已提交：{name}"
    if current and current.summary and name not in current.summary:
        summary = f"{current.summary}；{name}"
    _LEDGER[key] = TurnRecord(
        key,
        "bulk_destructive",
        True,
        "committed",
        summary,
        _tenant(runtime_context),
        current.customer_count if current else None,
        current.product_count if current else None,
    )
