# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.agent_butler_api")


def _butler_tools_for_user(
    user: _facade().User | None,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    if user is not None and bool(getattr(user, "is_admin", False)):
        return list(_facade().BUTLER_TOOLS) + list(_facade().ADMIN_READONLY_TOOLS)
    return list(_facade().BUTLER_TOOLS)


def _clip_tool_text(text: str, *, max_chars: int = 2800) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 20] + "\n…(已截断)"


def _execute_admin_readonly_tool(
    name: str,
    args: _facade().Optional[_facade().Dict[str, _facade().Any]],
    *,
    user: _facade().User,
    db: _facade().Session,
) -> str:
    """执行管理员会话只读工具；强制本人数据隔离。"""
    if not bool(getattr(user, "is_admin", False)):
        return "错误：仅管理员会话可用此工具"
    tool = (name or "").strip()
    if tool not in _facade().ADMIN_READONLY_TOOL_NAMES:
        return f"错误：未知只读工具 {tool}"
    args = args if isinstance(args, dict) else {}

    def _limit(default: int = 8, hard: int = 20) -> int:
        try:
            n = int(args.get("limit") or default)
        except (TypeError, ValueError):
            n = default
        return max(1, min(n, hard))

    try:
        if tool == "get_my_account_snapshot":
            from modstore_server.xiaoc_cs_ssot import (
                format_visitor_block,
                resolve_user_identity,
            )

            ident = resolve_user_identity(user, db=db, source="butler")
            lines = [
                "【本人账户快照】",
                format_visitor_block(ident),
                f"is_admin={bool(getattr(user, 'is_admin', False))}",
                f"is_enterprise={bool(getattr(user, 'is_enterprise', False))}",
            ]
            return _facade()._clip_tool_text("\n".join(lines))
        if tool == "get_my_wallet":
            from modstore_server.models import Transaction, Wallet

            lim = _limit(5, 20)
            wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
            balance = float(wallet.balance) if wallet else 0.0
            updated = wallet.updated_at.isoformat() if wallet and wallet.updated_at else ""
            rows = (
                db.query(Transaction)
                .filter(Transaction.user_id == user.id)
                .order_by(Transaction.created_at.desc())
                .limit(lim)
                .all()
            )
            lines = [
                "【本人钱包】",
                f"余额={balance}",
                f"updated_at={updated}",
                f"最近流水(最多{lim}条)：",
            ]
            for r in rows:
                lines.append(
                    f"- #{r.id} {r.txn_type or ''} {r.amount} {r.status or ''} {(r.description or '')[:60]} {(r.created_at.isoformat() if r.created_at else '')}"
                )
            if not rows:
                lines.append("- （暂无流水）")
            return _facade()._clip_tool_text("\n".join(lines))
        if tool == "get_my_orders":
            from modstore_server import payment_orders

            lim = _limit(8, 20)
            rows, total = payment_orders.list_orders(
                user_id=int(user.id), status=None, limit=lim, offset=0
            )
            lines = [f"【本人订单】共{total}条，展示最近{min(lim, len(rows))}条："]
            for o in rows:
                if not isinstance(o, dict):
                    continue
                ono = o.get("out_trade_no") or o.get("order_no") or o.get("id") or ""
                lines.append(
                    f"- {ono} status={o.get('status')} amount={o.get('total_amount') or o.get('amount')} subject={str(o.get('subject') or o.get('title') or '')[:40]}"
                )
            if not rows:
                lines.append("- （暂无订单）")
            return _facade()._clip_tool_text("\n".join(lines))
        if tool == "get_my_tickets":
            from modstore_server.customer_service_orchestrator import ticket_payload
            from modstore_server.models_cs import CustomerServiceTicket

            lim = _limit(8, 20)
            rows = (
                db.query(CustomerServiceTicket)
                .filter(CustomerServiceTicket.user_id == user.id)
                .order_by(
                    CustomerServiceTicket.updated_at.desc(),
                    CustomerServiceTicket.id.desc(),
                )
                .limit(lim)
                .all()
            )
            lines = [f"【本人工单】最近{len(rows)}条："]
            for t in rows:
                p = ticket_payload(t)
                lines.append(
                    f"- {p.get('ticket_no')} {p.get('title')} status={p.get('status')} intent={p.get('intent')} decision={p.get('decision_status')}"
                )
            if not rows:
                lines.append("- （暂无工单）")
            return _facade()._clip_tool_text("\n".join(lines))
        if tool == "get_ops_update_brief":
            lim = _limit(3, 5)
            digests = (
                db.query(_facade().DailyDigestRecord)
                .order_by(_facade().DailyDigestRecord.id.desc())
                .limit(lim)
                .all()
            )
            lines = ["【运维更新推送】"]
            if digests:
                lines.append(f"最近日更 {len(digests)} 条：")
                for row in digests:
                    d = _facade()._daily_digest_record_to_dict(row, include_body=False)
                    body = str(d.get("body_text") or "")[:180].replace("\n", " ")
                    lines.append(
                        f"- day={d.get('day')} subject={d.get('subject') or ''} delivered={d.get('delivered')} | {body}"
                    )
            else:
                lines.append("- （暂无日更记录）")
            try:
                from modstore_server.release_train import snapshot_public

                snap = snapshot_public() or {}
                lines.append(
                    f"release_train: current={snap.get('current')} product={snap.get('product_version')} day_index={snap.get('day_index')} next={snap.get('next_kind_hint')} marketing={snap.get('marketing_analog')}"
                )
            except RECOVERABLE_ERRORS as exc:
                lines.append(f"release_train: 暂不可用 ({type(exc).__name__})")
            return _facade()._clip_tool_text("\n".join(lines))
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("admin readonly tool %s failed: %s", tool, exc)
        return f"错误：执行 {tool} 失败（{type(exc).__name__}）"
    return f"错误：未处理工具 {tool}"


def _partition_butler_tool_calls(
    tool_calls: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    user: _facade().User,
    db: _facade().Session,
) -> tuple[_facade().List[_facade().Dict[str, _facade().Any]], str]:
    """拆分页面工具 vs 只读工具；只读在服务端执行并返回摘要文本。"""
    page_calls: _facade().List[_facade().Dict[str, _facade().Any]] = []
    briefs: _facade().List[str] = []
    is_admin = bool(getattr(user, "is_admin", False))
    for tc in tool_calls or []:
        name = str((tc or {}).get("name") or "").strip()
        if is_admin and name in _facade().ADMIN_READONLY_TOOL_NAMES:
            args = (tc or {}).get("args")
            if not isinstance(args, dict):
                args = {}
            briefs.append(_facade()._execute_admin_readonly_tool(name, args, user=user, db=db))
        else:
            page_calls.append(tc)
    brief = ""
    if briefs:
        brief = "\n\n".join(briefs)
    return (page_calls, brief)


class ButlerMessageDTO(_facade().BaseModel):
    role: str
    content: _facade().Any


class ButlerChatDTO(_facade().BaseModel):
    messages: _facade().List[ButlerMessageDTO]
    conversation_id: _facade().Optional[int] = None
    page_context: _facade().Optional[str] = _facade().Field(None, max_length=4000)
    max_tokens: _facade().Optional[int] = _facade().Field(None, ge=1, le=8000)


class CorpChatDTO(_facade().BaseModel):
    messages: _facade().List[ButlerMessageDTO]
    page_id: _facade().Optional[str] = _facade().Field(None, max_length=64)
    page_context: _facade().Optional[str] = _facade().Field(None, max_length=3500)
    max_tokens: _facade().Optional[int] = _facade().Field(512, ge=1, le=2000)
    visitor_id: _facade().Optional[str] = _facade().Field(None, max_length=80)
    visitor_label: _facade().Optional[str] = _facade().Field(None, max_length=64)


class CorpTtsDTO(_facade().BaseModel):
    text: str = _facade().Field(..., min_length=1, max_length=2000)
    voice: _facade().Optional[str] = _facade().Field(None, max_length=64)


class CorpTranslateDTO(_facade().BaseModel):
    text: str = _facade().Field(..., min_length=1, max_length=500)
    target: str = _facade().Field("en", max_length=8)
