"""电子签适配器（法大大 / stub）。"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class EsignAdapter(ABC):
    provider: str = "stub"

    @abstractmethod
    def create_sign_task(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class StubEsignAdapter(EsignAdapter):
    provider = "stub"

    def create_sign_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.stub_esign_store import create_task

        uid = int(payload.get("market_user_id") or 0)
        party_a = str(payload.get("party_a") or "").strip()
        party_b = str(payload.get("party_b") or "").strip()
        subject = (
            f"{party_a}与{party_b}合同签署".strip("与") if (party_a or party_b) else "合同签署"
        )
        amount = payload.get("amount_cents")
        amount_cents = int(amount) if amount is not None else None
        task = create_task(
            market_user_id=uid,
            party_a=party_a,
            party_b=party_b,
            subject=subject,
            amount_cents=amount_cents,
        )
        return {
            "provider": self.provider,
            "task_id": task["task_id"],
            "sign_url": task["sign_url"],
            "status": "signing",
            "market_user_id": uid,
            "subject": task.get("subject"),
            "party_a": party_a,
            "party_b": party_b,
        }

    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "signed": bool(payload.get("signed") or payload.get("status") == "signed"),
            "market_user_id": payload.get("market_user_id"),
            "task_id": payload.get("task_id"),
        }


class FadadaEsignAdapter(EsignAdapter):
    provider = "fadada"

    def create_sign_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.fadada_fasc_client import FascConfig, FascOpenApiClient, fasc_configured

        uid = int(payload.get("market_user_id") or 0)
        party_a = str(payload.get("party_a") or "").strip()
        party_b = str(payload.get("party_b") or "").strip()
        subject = (
            f"{party_a}与{party_b}合同签署".strip("与") if (party_a or party_b) else "合同签署"
        )

        if not fasc_configured():
            logger.warning("法大大未配置完整 FADADA_*，返回占位签署任务")
            task_id = f"fdd-{uuid.uuid4().hex[:16]}"
            return {
                "provider": self.provider,
                "task_id": task_id,
                "sign_url": os.environ.get("FADADA_SIGN_PORTAL_URL", "").strip()
                or f"https://fadada.com/sign/{task_id}",
                "status": "signing",
                "market_user_id": uid,
                "placeholder": True,
            }

        cfg = FascConfig.from_env()
        assert cfg is not None
        client = FascOpenApiClient(cfg)
        trans_ref = str(uid) if uid > 0 else uuid.uuid4().hex[:12]
        # 法大大模板：企业发起（乙方修茈），个人签署方为甲方（客户）
        signer_name = party_a or party_b or "签署方"
        task_id = client.create_sign_task_with_template(
            subject=subject,
            party_b_name=signer_name,
            trans_reference_id=trans_ref,
        )
        sign_url = client.get_actor_sign_url(sign_task_id=task_id)
        return {
            "provider": self.provider,
            "task_id": task_id,
            "sign_url": sign_url,
            "status": "signing",
            "market_user_id": uid,
            "trans_reference_id": trans_ref,
        }

    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("_fadada_callback"):
            biz = payload.get("biz") if isinstance(payload.get("biz"), dict) else {}
            event = str(payload.get("event") or "")
            from app.services.fadada_fasc_client import fadada_event_is_signed

            signed = fadada_event_is_signed(event, biz)
            uid = 0
            try:
                uid = int(biz.get("transReferenceId") or payload.get("market_user_id") or 0)
            except (TypeError, ValueError):
                uid = 0
            return {
                "signed": signed,
                "market_user_id": uid,
                "task_id": biz.get("signTaskId") or payload.get("task_id"),
            }
        return {
            "signed": str(payload.get("contract_status") or payload.get("status") or "").lower()
            in ("signed", "complete"),
            "market_user_id": payload.get("market_user_id") or payload.get("customer_ref"),
            "task_id": payload.get("task_id") or payload.get("contract_id"),
        }


def get_esign_adapter() -> EsignAdapter:
    raw = (os.environ.get("ESIGN_PROVIDER") or "stub").strip().lower()
    if raw in ("fadada", "法大大"):
        return FadadaEsignAdapter()
    return StubEsignAdapter()


def esign_provider_name() -> str:
    raw = (os.environ.get("ESIGN_PROVIDER") or "stub").strip().lower()
    return "fadada" if raw in ("fadada", "法大大") else "stub"


def _fadada_env_configured() -> bool:
    required = (
        "FADADA_APP_ID",
        "FADADA_APP_SECRET",
        "FADADA_OPEN_CORP_ID",
        "FADADA_SIGN_TEMPLATE_ID",
    )
    return all((os.environ.get(k) or "").strip() for k in required)


def esign_channel_status() -> dict[str, Any]:
    """运维/财务页：当前电子签通道（自建 stub 为默认生产路径）。"""
    use_fadada = esign_provider_name() == "fadada"
    labels = {
        "stub": "XCAGI 自建电子签（签署页 + 状态机，无需法大大）",
        "fadada": "法大大 FASC OpenAPI（可选法定效力）",
    }
    provider = "fadada" if use_fadada else "stub"
    configured = _fadada_env_configured() if use_fadada else True
    callback = (os.environ.get("FADADA_CALLBACK_URL") or "").strip()
    return {
        "ok": True,
        "provider": provider,
        "label": labels.get(provider, provider),
        "self_hosted": not use_fadada,
        "fadada_selected": use_fadada,
        "fadada_configured": configured,
        "fadada_callback_url": callback or None,
        "webhook_path": "/api/contract-lifecycle/esign/webhook",
        "fadada_callback_path": "/api/contract-lifecycle/esign/webhook",
        "note": (
            "法大大已选但未配置 FADADA_APP_ID / APP_SECRET / OPEN_CORP_ID / SIGN_TEMPLATE_ID，签署为占位。"
            if use_fadada and not configured
            else (
                "法大大通道已就绪；请在法大大控制台配置回调至 FADADA_CALLBACK_URL。"
                if use_fadada and configured
                else (
                    "自建签署：发起后复制 sign_url 给客户，客户在签署页确认即自动生效；无需法大大。"
                )
            )
        ),
    }
