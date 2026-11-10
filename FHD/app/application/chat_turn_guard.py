"""Chat turn decisions: displayable model text, bulk-delete preview, and idempotent retry.

The desktop session probe and agent-run polls abort at 8s and must not be treated as
the model call. This module decides whether a turn may mutate, independent of that timer.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
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
_LEDGER: dict[tuple[str, str, str], TurnRecord] = {}
_LEDGER_LOCK = threading.RLock()


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
    request_text: str = ""
    customer_scope: str | None = None
    product_scope: str | None = None
    submitted_tools: set[str] = field(default_factory=set)


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


def scope_snapshot(ctx: dict[str, Any]) -> tuple[int | None, int | None, str | None, str | None]:
    """Capture tenant-scoped records, never caller-provided counts or IDs."""
    try:
        from app.application.agent_orchestrator.tool_permission import actor_tool_denial
        from app.db.models import Product
        from app.db.models.purchase_unit import PurchaseUnit
        from app.db.session import get_db
        from app.infrastructure.auth.agent_mod_scope import _bound_actor

        _bound_actor(ctx)
        tenant = int(ctx.get("tenant_id") or 0)
        if tenant <= 0:
            return None, None, None, None
        snapshots: list[tuple[int | None, str | None]] = []
        with get_db() as db:
            for tool, model in (("customers", PurchaseUnit), ("products", Product)):
                if actor_tool_denial(tool, "query", ctx) is not None:
                    snapshots.append((None, None))
                    continue
                digest, count = hashlib.sha256(), 0
                rows = (
                    db.query(*model.__table__.columns)
                    .filter(model.tenant_id == tenant)
                    .order_by(model.id)
                    .yield_per(1000)
                )
                for row in rows:
                    digest.update(
                        json.dumps(
                            tuple(row), ensure_ascii=False, default=str, separators=(",", ":")
                        ).encode()
                    )
                    digest.update(b"\n")
                    count += 1
                snapshots.append((count, digest.hexdigest()))
        return snapshots[0][0], snapshots[1][0], snapshots[0][1], snapshots[1][1]
    except SQLAlchemyError:
        return None, None, None, None
    except RECOVERABLE_ERRORS:
        return None, None, None, None


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


def _remember(record: TurnRecord, ctx: dict[str, Any]) -> dict[str, Any]:
    if record.key:
        with _LEDGER_LOCK:
            previous = _LEDGER.get(_scope_key(ctx))
            if record.effect == "preview" and previous and previous.effect != "preview":
                record = previous
            else:
                _LEDGER[_scope_key(ctx)] = record
    return {
        "success": record.effect in {"preview", "committed"},
        "response": record.summary,
        "text": record.summary,
        "message": record.summary,
        "execution": execution_payload(record),
    }


def _key(ctx: dict[str, Any]) -> str:
    return str(ctx.get("idempotency_key") or ctx.get("turn_id") or "").strip()


def _scope_key(ctx: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(ctx.get("tenant_id") or ""),
        str(ctx.get("user_id") or ctx.get("local_user_id") or ""),
        _key(ctx),
    )


def execution_for_context(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """The turn's intent-versus-commit record, when this request has one."""
    if not isinstance(ctx, dict):
        return None
    key = _key(ctx)
    record = _LEDGER.get(_scope_key(ctx)) if key else None
    return execution_payload(record) if record else None


def prepare_turn(message: str, ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Stamp mutation policy. Return a reply when the model must not be asked to write."""
    key = _key(ctx)
    retry = bool(str(ctx.get("retry_of") or "").strip())
    confirmed = ctx.get("destructive_confirmed") is True and bool(key)
    bulk = is_bulk_destructive(message)
    existing = _LEDGER.get(_scope_key(ctx)) if key else None
    if retry:
        _use_policy("model_only")
        return None
    if existing and (existing.committed or existing.effect in {"unknown", "pending_approval"}):
        _use_policy("model_only")
        return _remember(existing, ctx)
    if bulk and not confirmed:
        customers, products, customer_scope, product_scope = scope_snapshot(ctx)
        text = preview_message(ctx, message, customers=customers, products=products)
        record = TurnRecord(
            key,
            "bulk_destructive",
            False,
            "preview",
            text,
            _tenant(ctx),
            customers,
            products,
            message.strip(),
            customer_scope,
            product_scope,
        )
        _use_policy("block")
        return _remember(record, ctx)
    if bulk and confirmed:
        customers, products, customer_scope, product_scope = scope_snapshot(ctx)
        with _LEDGER_LOCK:
            existing = _LEDGER.get(_scope_key(ctx))
            if existing and existing.effect in {"opened", "executing", "unknown"}:
                _use_policy("model_only")
                text = "上一轮写入状态未确认，请先核对原任务；本次不会执行删除。"
                return {
                    "success": False,
                    "response": text,
                    "text": text,
                    "message": text,
                    "execution": {**execution_payload(existing), "effect": "unknown"},
                }
            valid_scope = ("客户" in message or "产品" in message) and not any(
                label in message for label in ("订单", "资料", "数据")
            )
            if (
                not existing
                or existing.effect != "preview"
                or not valid_scope
                or existing.request_text != message.strip()
                or (
                    "客户" in message
                    and (
                        customers is None
                        or customer_scope is None
                        or customer_scope != existing.customer_scope
                    )
                )
                or (
                    "产品" in message
                    and (
                        products is None
                        or product_scope is None
                        or product_scope != existing.product_scope
                    )
                )
            ):
                _use_policy("block")
                text = "删除范围或权限未确认，请重新预览；本次未执行删除。"
                return {"success": False, "response": text, "text": text, "message": text}
            record = TurnRecord(
                key,
                "bulk_destructive",
                False,
                "opened",
                "",
                _tenant(ctx),
                customers,
                products,
                message.strip(),
                customer_scope,
                product_scope,
            )
            _LEDGER[_scope_key(ctx)] = record
            ctx["_bulk_preview_scopes"] = {
                tool: digest
                for tool, label, digest in (
                    ("customers", "客户", customer_scope),
                    ("products", "产品", product_scope),
                )
                if label in message and digest
            }
        _use_policy("allow_once")
        return None
    _use_policy("allow")
    return None


def admit_chat_turn(message: str, ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Derive mutation policy and preview scope only from the server-side turn."""
    ctx.pop("_bulk_preview_scope", None)
    ctx.pop("_bulk_preview_scopes", None)
    try:
        reply = prepare_turn(message, ctx)
        ctx["mutation_policy"] = mutation_policy()
        return reply
    finally:
        release_mutation_policy()


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


def _matches_previewed_batch(name: str, raw_args: str, ctx: dict[str, Any], message: str) -> bool:
    """Only the previewed tenant's complete ID set may reach the approval gate."""
    from app.db.models import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.session import get_db

    try:
        args = json.loads(raw_args)
        if name != "execute_erp_capability" or not isinstance(args, dict):
            return False
        tool, action, params = args.get("tool_id"), args.get("action"), args.get("params")
        labels = {"customers": "客户", "products": "产品"}
        if tool not in labels or labels[tool] not in message or action != "batch_delete":
            return False
        if not isinstance(params, dict) or set(params) != {"ids"}:
            return False
        ids = params["ids"]
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
            return False
        tenant = int(ctx.get("tenant_id") or 0)
        model = Product if tool == "products" else PurchaseUnit
        with get_db() as db:
            actual = {row[0] for row in db.query(model.id).filter(model.tenant_id == tenant)}
        return tenant > 0 and len(ids) == len(actual) and set(ids) == actual
    except (ValueError, TypeError, SQLAlchemyError):
        return False


def mutation_block(name: str, raw_args: str, runtime_context: Any) -> dict[str, Any] | None:
    if not _is_mutation(name, raw_args):
        return None
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    policy = str(ctx.get("mutation_policy") or "") or _POLICY.get()
    key = _key(ctx)
    current_scope = scope_snapshot(ctx) if policy == "allow_once" else None
    with _LEDGER_LOCK:
        existing = _LEDGER.get(_scope_key(ctx)) if key else None
        if existing and (existing.committed or existing.effect in {"executing", "unknown"}):
            return {
                "success": False,
                "committed": existing.committed,
                "error": "already_committed" if existing.committed else "outcome_unknown",
                "message": "原操作状态待核验，不会再次执行。",
            }
        if policy in {"block", "model_only"}:
            return {
                "success": False,
                "committed": False,
                "error": "mutation_blocked",
                "message": "未授权或本轮只重试模型，未执行写入。",
            }
        if policy == "allow_once":
            if not existing or existing.effect != "opened":
                return {
                    "success": False,
                    "error": "outcome_unknown",
                    "message": "原操作状态待核验。",
                }
            if current_scope is None or (
                (
                    "客户" in existing.request_text
                    and (current_scope[2] is None or current_scope[2] != existing.customer_scope)
                )
                or (
                    "产品" in existing.request_text
                    and (current_scope[3] is None or current_scope[3] != existing.product_scope)
                )
            ):
                existing.effect = "scope_changed"
                return {
                    "success": False,
                    "committed": False,
                    "error": "scope_changed",
                    "message": "范围或权限已变化，本次未执行。",
                }
            if not _matches_previewed_batch(name, raw_args, ctx, existing.request_text):
                return {
                    "success": False,
                    "error": "scope_mismatch",
                    "message": "工具操作与预览范围不一致，本次未执行。",
                }
            tool = json.loads(raw_args)["tool_id"]
            if tool in existing.submitted_tools:
                return {
                    "success": False,
                    "error": "already_submitted",
                    "message": "该范围已提交审批。",
                }
            ctx["_bulk_preview_scope"] = {
                "tool": tool,
                "digest": existing.customer_scope
                if tool == "customers"
                else existing.product_scope,
            }
            existing.effect = "executing"
    return None


def note_tool_result(
    runtime_context: Any, name: str, raw_args: str = "", *, pending: bool = False
) -> None:
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
    with _LEDGER_LOCK:
        current = _LEDGER.get(_scope_key(runtime_context))
        if pending and current and current.effect == "executing":
            try:
                tool = json.loads(raw_args)["tool_id"]
            except (ValueError, KeyError, TypeError):
                tool = ""
            if tool in {"customers", "products"}:
                current.submitted_tools.add(tool)
                required = {
                    key
                    for key, label in (("customers", "客户"), ("products", "产品"))
                    if label in current.request_text
                }
                current.effect = (
                    "pending_approval" if required <= current.submitted_tools else "opened"
                )
                current.summary = "删除申请已提交审批，尚未确认业务写入。"
                return
        summary = f"{name} 已返回，实际写入状态待核验，请勿重复操作。"
        _LEDGER[_scope_key(runtime_context)] = TurnRecord(
            key,
            "bulk_destructive",
            False,
            "unknown",
            summary,
            _tenant(runtime_context),
            current.customer_count if current else None,
            current.product_count if current else None,
        )
