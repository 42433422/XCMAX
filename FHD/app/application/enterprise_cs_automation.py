"""Enterprise dedicated-CS AI routing with fail-closed human handoff.

The customer keeps using the existing ``enterprise-cs`` IM conversation.  This
module runs only on the server: safe questions receive an AI reply in that same
thread; explicit or risky requests are moved to the existing admin inbox.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.im import ImCustomerServiceAutomationState
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.services.kellai_copilot_llm import content_from_completion, parse_json_content
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_TRANSFER_PHRASES = (
    "转人工",
    "人工客服",
    "找人工",
    "真人客服",
    "人工服务",
    "人工处理",
)
_TRANSFER_NEGATIONS = ("不要转人工", "不用转人工", "无需人工")
_DISSATISFIED_PHRASES = (
    "没解决",
    "没有解决",
    "还是不行",
    "没用",
    "答非所问",
    "听不懂",
    "解决不了",
)
_HIGH_RISK_PHRASES = (
    "退款",
    "退费",
    "赔偿",
    "投诉",
    "合同",
    "报价",
    "付款",
    "支付",
    "发票",
    "法律",
    "隐私",
    "数据删除",
    "注销账号",
    "安全事故",
    "权益变更",
    "套餐变更",
    "永久套餐",
    "续费",
    "定制承诺",
)
_ALLOWED_MODES = {"ai", "human"}


def _enabled() -> bool:
    raw = os.environ.get("XCAGI_ENTERPRISE_CS_AI_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _audit(*, actor: int | str | None, action: str, payload: dict[str, Any]) -> None:
    try:
        from app.mod_sdk.audit import write_audit_event

        write_audit_event(actor=actor, action=action, payload=payload)
    except RECOVERABLE_ERRORS:
        logger.debug("enterprise CS audit unavailable", exc_info=True)


class EnterpriseCsAutomationService:
    def __init__(self, db: Session):
        self._db = db

    def _state(
        self, conversation_id: int, *, create: bool
    ) -> ImCustomerServiceAutomationState | None:
        row = self._db.get(ImCustomerServiceAutomationState, int(conversation_id))
        if row is not None or not create:
            return row
        row = ImCustomerServiceAutomationState(
            conversation_id=int(conversation_id),
            mode="ai",
            status="ai_active",
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def public_state(self, conversation_id: int) -> dict[str, Any]:
        row = self._state(conversation_id, create=False)
        return {
            "cs_mode": str(row.mode if row else "ai"),
            "cs_status": str(row.status if row else "ai_active"),
            "cs_transfer_reason": str(row.transfer_reason if row else ""),
            "cs_summary": str(row.summary if row else ""),
            "cs_last_operator_user_id": row.last_operator_user_id if row else None,
        }

    def is_enterprise_cs_conversation(self, conversation_id: int, customer_user_id: int) -> bool:
        from app.application.im_app_service import ImApplicationService

        svc = ImApplicationService(self._db)
        cs_id = svc.enterprise_cs_user_id()
        if cs_id is None or int(cs_id) == int(customer_user_id):
            return False
        member_ids = svc._member_user_ids(int(conversation_id))
        return int(cs_id) in member_ids and int(customer_user_id) in member_ids

    def set_mode(
        self,
        conversation_id: int,
        mode: str,
        *,
        operator_user_id: int,
        reason: str = "",
    ) -> dict[str, Any]:
        normalized = str(mode or "").strip().lower()
        if normalized not in _ALLOWED_MODES:
            raise ValueError("客服接待模式无效")
        row = self._state(conversation_id, create=True)
        if row is None:
            raise ValueError("客服会话不存在")
        row.mode = normalized
        row.status = "human_active" if normalized == "human" else "ai_active"
        row.transfer_reason = (reason or "")[:1000] if normalized == "human" else ""
        row.last_operator_user_id = int(operator_user_id)
        if normalized == "ai":
            row.consecutive_failures = 0
        self._db.commit()
        _audit(
            actor=operator_user_id,
            action=f"enterprise_cs.{normalized}_mode.enabled",
            payload={
                "conversation_id": int(conversation_id),
                "reason": row.transfer_reason,
            },
        )
        return self.public_state(conversation_id)

    def note_manual_reply(self, conversation_id: int, *, operator_user_id: int) -> None:
        self.set_mode(
            conversation_id,
            "human",
            operator_user_id=operator_user_id,
            reason="管理员已人工回复",
        )

    def _customer_context(self, customer_user_id: int) -> dict[str, Any]:
        user = self._db.get(User, int(customer_user_id))
        latest_session = (
            self._db.execute(
                select(UserSession)
                .where(UserSession.user_id == int(customer_user_id))
                .order_by(desc(UserSession.id))
                .limit(1)
            )
            .scalars()
            .first()
        )
        return {
            "customer_user_id": int(customer_user_id),
            "display_name": str(getattr(user, "display_name", "") or getattr(user, "username", "")),
            "account_tier": str(getattr(user, "account_tier", "") or ""),
            "industry_id": str(getattr(user, "industry_id", "") or ""),
            "account_kind": str(getattr(latest_session, "account_kind", "") or ""),
            "membership_tier": str(getattr(latest_session, "market_membership_tier", "") or ""),
            "company_brand": str(getattr(latest_session, "company_brand", "") or ""),
        }

    def _transcript(self, conversation_id: int, cs_id: int) -> list[dict[str, Any]]:
        from app.application.im_app_service import ImApplicationService

        messages = ImApplicationService(self._db).list_messages(
            int(conversation_id), int(cs_id), limit=24
        )
        return [
            {
                "id": int(item.get("id") or 0),
                "role": (
                    "service" if int(item.get("sender_user_id") or 0) == int(cs_id) else "customer"
                ),
                "origin": str(item.get("origin") or "user"),
                "body": str(item.get("body") or "")[:1200],
                "created_at": str(item.get("created_at") or ""),
            }
            for item in messages
            if str(item.get("body") or "").strip()
        ]

    def _transfer(
        self,
        conversation_id: int,
        *,
        reason: str,
        summary: str = "",
        notify_customer: bool = True,
    ) -> dict[str, Any]:
        from app.application.im_app_service import ImApplicationService

        row = self._state(conversation_id, create=True)
        if row is None:
            raise ValueError("客服会话不存在")
        already_human = row.mode == "human" and row.status in {
            "human_pending",
            "human_active",
        }
        row.mode = "human"
        row.status = "human_pending"
        row.transfer_reason = str(reason or "需要人工处理")[:1000]
        row.summary = str(summary or row.summary or "")[:2000]
        self._db.commit()
        if notify_customer and not already_human:
            ImApplicationService(self._db).cs_reply(
                int(conversation_id),
                "这个问题已为您转接人工客服，客服人员会在本会话继续回复，请稍候。",
                origin="system",
            )
        _audit(
            actor="enterprise-cs-ai",
            action="enterprise_cs.transferred_to_human",
            payload={
                "conversation_id": int(conversation_id),
                "reason": row.transfer_reason,
            },
        )
        return self.public_state(conversation_id)

    async def handle_customer_message(
        self,
        *,
        conversation_id: int,
        customer_user_id: int,
        message_id: int,
        body: str,
    ) -> dict[str, Any]:
        from app.application.im_app_service import ImApplicationService

        if not self.is_enterprise_cs_conversation(conversation_id, customer_user_id):
            return {"handled": False, "reason": "not_enterprise_cs"}
        row = self._state(conversation_id, create=True)
        if row is None:
            return {"handled": False, "reason": "state_unavailable"}
        if int(row.last_customer_message_id or 0) >= int(message_id):
            return {"handled": False, "reason": "duplicate"}
        row.last_customer_message_id = int(message_id)
        if row.mode == "human":
            self._db.commit()
            return {
                "handled": False,
                "reason": "human_mode",
                **self.public_state(conversation_id),
            }

        text = str(body or "").strip()
        if not _enabled():
            return {
                "handled": True,
                "action": "transfer",
                **self._transfer(conversation_id, reason="AI自动接待未启用"),
            }
        if any(phrase in text for phrase in _TRANSFER_PHRASES) and not any(
            phrase in text for phrase in _TRANSFER_NEGATIONS
        ):
            return {
                "handled": True,
                "action": "transfer",
                **self._transfer(conversation_id, reason="客户主动要求转人工"),
            }
        if any(phrase in text for phrase in _HIGH_RISK_PHRASES):
            return {
                "handled": True,
                "action": "transfer",
                **self._transfer(conversation_id, reason="涉及高风险或需人工确认事项"),
            }

        if any(phrase in text for phrase in _DISSATISFIED_PHRASES):
            row.consecutive_failures = int(row.consecutive_failures or 0) + 1
        else:
            row.consecutive_failures = 0
        if int(row.consecutive_failures or 0) >= 2:
            return {
                "handled": True,
                "action": "transfer",
                **self._transfer(conversation_id, reason="客户连续反馈AI未解决问题"),
            }
        row.status = "ai_processing"
        self._db.commit()

        svc = ImApplicationService(self._db)
        cs_id = svc.enterprise_cs_user_id()
        if cs_id is None:
            return {
                "handled": True,
                "action": "transfer",
                **self._transfer(conversation_id, reason="客服通道不可用", notify_customer=False),
            }
        system_prompt = """你是企业软件客户支持AI，只处理低风险咨询并进行多轮澄清。
只根据给定客户资料和真实会话回答，禁止编造价格、权益、付款、合同、交期、已执行动作或公司承诺。
若问题涉及退款、支付、合同、报价、投诉、法律、隐私、安全、数据删除、账号或权益变更、定制承诺，必须 transfer。
信息不足时可以只问一个最关键的澄清问题。若无法可靠回答、客户明确不满或需要后台执行，也必须 transfer。
本轮风险判断和回复必须只针对 latest_customer_message；conversation 仅用于理解上下文。
历史中已经结束或已转人工的高风险话题，不得单独导致本轮普通问题转人工；只有本轮消息继续、追问或依赖该高风险事项时才 transfer。
输出严格JSON：
{"action":"reply|transfer","reply":"给客户的中文回复，transfer时留空","summary":"不超过120字的问题摘要","confidence":0到1,"risk_level":"low|medium|high|critical","transfer_reason":"转人工原因"}
不得输出JSON以外内容。"""
        user_prompt = json.dumps(
            {
                "customer": self._customer_context(customer_user_id),
                "latest_customer_message": {
                    "id": int(message_id),
                    "body": text,
                },
                "conversation": self._transcript(conversation_id, cs_id),
            },
            ensure_ascii=False,
        )
        try:
            from app.infrastructure.llm.invoke import chat_completion_openai_format

            completion = await chat_completion_openai_format(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=700,
                profile="customer_copilot",
                reasoning_enabled=False,
            )
            parsed = parse_json_content(content_from_completion(completion))
        except RECOVERABLE_ERRORS:
            logger.exception("enterprise CS AI completion failed")
            return {
                "handled": True,
                "action": "transfer",
                **self._transfer(conversation_id, reason="AI服务暂时不可用"),
            }

        self._db.refresh(row)
        if int(row.last_customer_message_id or 0) != int(message_id) or row.mode != "ai":
            return {
                "handled": False,
                "reason": "superseded",
                **self.public_state(conversation_id),
            }

        action = str(parsed.get("action") or "transfer").strip().lower()
        reply = str(parsed.get("reply") or "").strip()[:4000]
        summary = str(parsed.get("summary") or "").strip()[:2000]
        risk = str(parsed.get("risk_level") or "high").strip().lower()
        try:
            confidence = float(parsed.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if action != "reply" or not reply or confidence < 0.72 or risk in {"high", "critical"}:
            reason = str(parsed.get("transfer_reason") or "AI置信度不足或风险较高")[:1000]
            return {
                "handled": True,
                "action": "transfer",
                **self._transfer(conversation_id, reason=reason, summary=summary),
            }

        sent = svc.cs_reply(conversation_id, reply, origin="ai")
        row.status = "ai_active"
        row.summary = summary
        row.transfer_reason = ""
        row.last_ai_message_id = int((sent.get("message") or {}).get("id") or 0)
        try:
            svc.mark_read(
                conversation_id,
                int(cs_id),
                int(message_id),
                record_sync=False,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("AI handled message mark-read failed", exc_info=True)
        self._db.commit()
        _audit(
            actor="enterprise-cs-ai",
            action="enterprise_cs.ai_replied",
            payload={
                "conversation_id": int(conversation_id),
                "customer_message_id": int(message_id),
                "ai_message_id": int(row.last_ai_message_id or 0),
                "confidence": confidence,
                "risk_level": risk,
            },
        )
        return {
            "handled": True,
            "action": "reply",
            "message": sent.get("message"),
            **self.public_state(conversation_id),
        }


async def process_enterprise_cs_customer_message(
    conversation_id: int,
    customer_user_id: int,
    message_id: int,
    body: str,
) -> dict[str, Any]:
    """Background-task entrypoint that owns and closes its database session."""

    from app.db import HostSessionLocal

    db = HostSessionLocal()
    try:
        return await EnterpriseCsAutomationService(db).handle_customer_message(
            conversation_id=int(conversation_id),
            customer_user_id=int(customer_user_id),
            message_id=int(message_id),
            body=str(body or ""),
        )
    finally:
        db.close()
