"""外部 CRM（HubSpot / Salesforce）出站推送与阶段回拉。"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PIPELINE_TO_HUBSPOT_STAGE = {
    "idle": "appointmentscheduled",
    "connected": "qualifiedtobuy",
    "intake": "presentationscheduled",
    "intake_done": "decisionmakerboughtin",
    "quoted": "contractsent",
    "negotiating": "contractsent",
    "contract_pending": "contractsent",
    "signed": "closedwon",
    "delivering": "closedwon",
    "delivered": "closedwon",
}

HUBSPOT_TO_PIPELINE_STAGE = {
    "appointmentscheduled": "idle",
    "qualifiedtobuy": "connected",
    "presentationscheduled": "intake",
    "decisionmakerboughtin": "intake_done",
    "contractsent": "negotiating",
    "closedlost": "idle",
}


def pipeline_stage_from_hubspot(hs_stage: str, pipeline_doc: dict[str, Any]) -> str:
    """将 HubSpot dealstage 映射为 pipeline 阶段 id。"""
    hs = (hs_stage or "").strip().lower()
    if not hs:
        return ""
    if hs == "closedwon":
        delivery = pipeline_doc.get("delivery")
        if isinstance(delivery, dict):
            try:
                pct = int(delivery.get("progress_percent") or 0)
            except (TypeError, ValueError):
                pct = 0
            if pct >= 100 or str(pipeline_doc.get("stage") or "") == "delivered":
                return "delivered"
            if pct > 0 or str(pipeline_doc.get("stage") or "") == "delivering":
                return "delivering"
        return "signed"
    return HUBSPOT_TO_PIPELINE_STAGE.get(hs, "")


# 默认 Salesforce Opportunity StageName（可在各组织自定义，见环境变量覆盖）
PIPELINE_TO_SALESFORCE_STAGE = {
    "idle": "Prospecting",
    "connected": "Qualification",
    "intake": "Needs Analysis",
    "intake_done": "Proposal/Price Quote",
    "quoted": "Proposal/Price Quote",
    "negotiating": "Negotiation/Review",
    "contract_pending": "Negotiation/Review",
    "signed": "Closed Won",
    "delivering": "Closed Won",
    "delivered": "Closed Won",
}

SALESFORCE_TO_PIPELINE_STAGE = {
    "prospecting": "idle",
    "qualification": "connected",
    "needs analysis": "intake",
    "proposal/price quote": "quoted",
    "negotiation/review": "negotiating",
    "closed lost": "idle",
}


def _load_json_env_map(name: str) -> dict[str, str] | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        logger.warning("%s is not valid JSON", name)
    return None


def pipeline_to_salesforce_stage_map() -> dict[str, str]:
    custom = _load_json_env_map("SALESFORCE_PIPELINE_TO_STAGE_JSON")
    if custom:
        return {**PIPELINE_TO_SALESFORCE_STAGE, **custom}
    return dict(PIPELINE_TO_SALESFORCE_STAGE)


def pipeline_stage_from_salesforce(sf_stage: str, pipeline_doc: dict[str, Any]) -> str:
    """将 Salesforce StageName 映射为 pipeline 阶段 id。"""
    raw = (sf_stage or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower == "closed won":
        delivery = pipeline_doc.get("delivery")
        if isinstance(delivery, dict):
            try:
                pct = int(delivery.get("progress_percent") or 0)
            except (TypeError, ValueError):
                pct = 0
            if pct >= 100 or str(pipeline_doc.get("stage") or "") == "delivered":
                return "delivered"
            if pct > 0 or str(pipeline_doc.get("stage") or "") == "delivering":
                return "delivering"
        return "signed"
    custom_rev = _load_json_env_map("SALESFORCE_STAGE_TO_PIPELINE_JSON")
    if custom_rev:
        for key, val in custom_rev.items():
            if key.lower() == lower:
                return val
    return SALESFORCE_TO_PIPELINE_STAGE.get(lower, "")


def _hubspot_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _extract_hubspot_deal_id(data: Any) -> str:
    if isinstance(data, dict):
        raw = data.get("id")
        if raw is not None:
            return str(raw).strip()
    return ""


class ExternalCrmAdapter(ABC):
    @abstractmethod
    def upsert_deal(
        self, opportunity: dict[str, Any], pipeline_doc: dict[str, Any]
    ) -> dict[str, Any]: ...

    def pull_deal_stage(self, deal_id: str, pipeline_doc: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "skipped": True, "reason": "pull_not_supported"}


class HubSpotCrmAdapter(ExternalCrmAdapter):
    def _token(self) -> str:
        return (os.environ.get("HUBSPOT_ACCESS_TOKEN") or "").strip()

    def _deal_properties(
        self, opportunity: dict[str, Any], pipeline_doc: dict[str, Any]
    ) -> dict[str, str]:
        stage = str(pipeline_doc.get("stage") or opportunity.get("stage") or "idle")
        return {
            "dealname": str(opportunity.get("title") or f"XC-{opportunity.get('id')}"),
            "dealstage": PIPELINE_TO_HUBSPOT_STAGE.get(stage, "appointmentscheduled"),
            "amount": str((pipeline_doc.get("quote_draft") or {}).get("amount_cents") or ""),
        }

    def upsert_deal(
        self, opportunity: dict[str, Any], pipeline_doc: dict[str, Any]
    ) -> dict[str, Any]:
        token = self._token()
        if not token:
            return {"ok": False, "skipped": True, "reason": "HUBSPOT_ACCESS_TOKEN missing"}
        body = {"properties": self._deal_properties(opportunity, pipeline_doc)}
        deal_id = str(pipeline_doc.get("external_crm_deal_id") or "").strip()
        try:
            if deal_id:
                url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
                resp = httpx.patch(url, headers=_hubspot_headers(token), json=body, timeout=15.0)
            else:
                url = "https://api.hubapi.com/crm/v3/objects/deals"
                resp = httpx.post(url, headers=_hubspot_headers(token), json=body, timeout=15.0)
            data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            resolved_id = deal_id or _extract_hubspot_deal_id(data)
            return {
                "ok": resp.status_code < 400,
                "provider": "hubspot",
                "deal_id": resolved_id,
                "data": data,
            }
        except Exception as exc:
            logger.exception("hubspot upsert failed")
            return {"ok": False, "provider": "hubspot", "error": str(exc)}

    def pull_deal_stage(self, deal_id: str, pipeline_doc: dict[str, Any]) -> dict[str, Any]:
        token = self._token()
        if not token:
            return {"ok": False, "skipped": True, "reason": "HUBSPOT_ACCESS_TOKEN missing"}
        did = (deal_id or "").strip()
        if not did:
            return {"ok": False, "error": "deal_id required"}
        try:
            resp = httpx.get(
                f"https://api.hubapi.com/crm/v3/objects/deals/{did}",
                params={"properties": "dealstage,dealname"},
                headers=_hubspot_headers(token),
                timeout=15.0,
            )
            data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            if resp.status_code >= 400:
                return {
                    "ok": False,
                    "provider": "hubspot",
                    "error": str(data.get("message") or data.get("status") or resp.text)[:300],
                }
            props = data.get("properties") if isinstance(data, dict) else {}
            hs_stage = ""
            if isinstance(props, dict):
                hs_stage = str(props.get("dealstage") or "").strip()
            mapped = pipeline_stage_from_hubspot(hs_stage, pipeline_doc)
            if not mapped:
                return {
                    "ok": False,
                    "provider": "hubspot",
                    "hubspot_stage": hs_stage,
                    "error": f"未识别的 HubSpot 阶段: {hs_stage or '(空)'}",
                }
            return {
                "ok": True,
                "provider": "hubspot",
                "deal_id": did,
                "hubspot_stage": hs_stage,
                "pipeline_stage": mapped,
            }
        except Exception as exc:
            logger.exception("hubspot pull failed deal=%s", did)
            return {"ok": False, "provider": "hubspot", "error": str(exc)}


class SalesforceCrmAdapter(ExternalCrmAdapter):
    def _instance(self) -> str:
        return (os.environ.get("SALESFORCE_INSTANCE_URL") or "").strip().rstrip("/")

    def _token(self) -> str:
        return (os.environ.get("SALESFORCE_ACCESS_TOKEN") or "").strip()

    def _api_version(self) -> str:
        return (os.environ.get("SALESFORCE_API_VERSION") or "59.0").strip()

    def _api_root(self) -> str:
        return f"{self._instance()}/services/data/v{self._api_version()}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }

    def _opportunity_payload(
        self, opportunity: dict[str, Any], pipeline_doc: dict[str, Any]
    ) -> dict[str, Any]:
        stage = str(pipeline_doc.get("stage") or opportunity.get("stage") or "idle")
        stage_map = pipeline_to_salesforce_stage_map()
        payload: dict[str, Any] = {
            "Name": str(opportunity.get("title") or f"XC-{opportunity.get('id')}"),
            "StageName": stage_map.get(stage, "Prospecting"),
            "CloseDate": (date.today() + timedelta(days=30)).isoformat(),
        }
        amount_cents = (pipeline_doc.get("quote_draft") or {}).get("amount_cents")
        if amount_cents is not None:
            try:
                payload["Amount"] = round(int(amount_cents) / 100.0, 2)
            except (TypeError, ValueError):
                pass
        account_id = (os.environ.get("SALESFORCE_DEFAULT_ACCOUNT_ID") or "").strip()
        if account_id:
            payload["AccountId"] = account_id
        return payload

    def upsert_deal(
        self, opportunity: dict[str, Any], pipeline_doc: dict[str, Any]
    ) -> dict[str, Any]:
        instance = self._instance()
        token = self._token()
        if not instance or not token:
            return {"ok": False, "skipped": True, "reason": "Salesforce env missing"}
        body = self._opportunity_payload(opportunity, pipeline_doc)
        opp_id = str(pipeline_doc.get("external_crm_deal_id") or "").strip()
        try:
            if opp_id:
                url = f"{self._api_root()}/sobjects/Opportunity/{opp_id}"
                resp = httpx.patch(url, headers=self._headers(), json=body, timeout=20.0)
                resolved_id = opp_id
            else:
                url = f"{self._api_root()}/sobjects/Opportunity"
                resp = httpx.post(url, headers=self._headers(), json=body, timeout=20.0)
                data = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                resolved_id = str(data.get("id") or "").strip() if isinstance(data, dict) else ""
            if resp.status_code >= 400:
                err_body = resp.text[:500]
                try:
                    err_json = resp.json()
                    if isinstance(err_json, list) and err_json:
                        err_body = str(err_json[0].get("message") or err_body)
                    elif isinstance(err_json, dict):
                        err_body = str(err_json.get("message") or err_json)[:500]
                except Exception:
                    pass
                return {
                    "ok": False,
                    "provider": "salesforce",
                    "error": err_body,
                    "status_code": resp.status_code,
                }
            return {
                "ok": True,
                "provider": "salesforce",
                "deal_id": resolved_id,
                "stage_name": body.get("StageName"),
            }
        except Exception as exc:
            logger.exception("salesforce upsert failed")
            return {"ok": False, "provider": "salesforce", "error": str(exc)}

    def pull_deal_stage(self, deal_id: str, pipeline_doc: dict[str, Any]) -> dict[str, Any]:
        instance = self._instance()
        token = self._token()
        if not instance or not token:
            return {"ok": False, "skipped": True, "reason": "Salesforce env missing"}
        oid = (deal_id or "").strip()
        if not oid:
            return {"ok": False, "error": "deal_id required"}
        try:
            resp = httpx.get(
                f"{self._api_root()}/sobjects/Opportunity/{oid}",
                params={"fields": "StageName,Name,Amount"},
                headers=self._headers(),
                timeout=20.0,
            )
            data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            if resp.status_code >= 400:
                msg = ""
                if isinstance(data, list) and data:
                    msg = str(data[0].get("message") or "")
                elif isinstance(data, dict):
                    msg = str(data.get("message") or data)
                return {
                    "ok": False,
                    "provider": "salesforce",
                    "error": (msg or resp.text)[:300],
                    "status_code": resp.status_code,
                }
            sf_stage = ""
            if isinstance(data, dict):
                sf_stage = str(data.get("StageName") or "").strip()
            mapped = pipeline_stage_from_salesforce(sf_stage, pipeline_doc)
            if not mapped:
                return {
                    "ok": False,
                    "provider": "salesforce",
                    "salesforce_stage": sf_stage,
                    "error": f"未识别的 Salesforce 阶段: {sf_stage or '(空)'}",
                }
            return {
                "ok": True,
                "provider": "salesforce",
                "deal_id": oid,
                "salesforce_stage": sf_stage,
                "pipeline_stage": mapped,
            }
        except Exception as exc:
            logger.exception("salesforce pull failed opp=%s", oid)
            return {"ok": False, "provider": "salesforce", "error": str(exc)}


def external_crm_status() -> dict[str, Any]:
    """运营线/全景页用：区分「代码已实现」与「环境已配置」。"""
    provider = (os.environ.get("EXTERNAL_CRM_PROVIDER") or "").strip().lower()
    sf_ready = bool(
        (os.environ.get("SALESFORCE_INSTANCE_URL") or "").strip()
        and (os.environ.get("SALESFORCE_ACCESS_TOKEN") or "").strip()
    )
    hs_ready = bool((os.environ.get("HUBSPOT_ACCESS_TOKEN") or "").strip())
    configured = (provider == "hubspot" and hs_ready) or (provider == "salesforce" and sf_ready)
    return {
        "hubspot_implemented": True,
        "salesforce_implemented": True,
        "provider": provider or None,
        "configured": configured,
        "hubspot_ready": hs_ready,
        "salesforce_ready": sf_ready,
        "note": (
            "Salesforce/HubSpot 适配器非 stub；未配置时 push/pull 会 skipped。"
            if not configured
            else (
                f"当前外部 CRM：{provider}；支持 push + 手动 pull 回写阶段（无 webhook 自动入站）"
            )
        ),
        "pull_implemented": True,
        "webhook_inbound": False,
    }


def get_external_crm_adapter() -> ExternalCrmAdapter | None:
    raw = (os.environ.get("EXTERNAL_CRM_PROVIDER") or "").strip().lower()
    if raw == "hubspot":
        return HubSpotCrmAdapter()
    if raw == "salesforce":
        return SalesforceCrmAdapter()
    return None


def push_opportunity_to_external_crm(
    opportunity: dict[str, Any], pipeline_doc: dict[str, Any]
) -> dict[str, Any]:
    adapter = get_external_crm_adapter()
    if not adapter:
        return {"ok": True, "skipped": True}
    return adapter.upsert_deal(opportunity, pipeline_doc)


def pull_stage_from_external_deal(deal_id: str, pipeline_doc: dict[str, Any]) -> dict[str, Any]:
    adapter = get_external_crm_adapter()
    if not adapter:
        return {"ok": True, "skipped": True, "reason": "EXTERNAL_CRM_PROVIDER not set"}
    return adapter.pull_deal_stage(deal_id, pipeline_doc)


def resolve_external_deal_id(pipeline_doc: dict[str, Any]) -> str:
    did = str(pipeline_doc.get("external_crm_deal_id") or "").strip()
    if did:
        return did
    last = pipeline_doc.get("external_crm_last_result")
    if isinstance(last, dict):
        return str(last.get("deal_id") or "").strip()
    return ""


def sync_crm_from_pipeline_with_external(doc: dict[str, Any]) -> dict[str, Any]:
    from app.services.user_cs_crm_store import (
        get_opportunity_by_market_user,
        sync_crm_from_pipeline_doc,
    )

    doc = sync_crm_from_pipeline_doc(doc)
    opp = get_opportunity_by_market_user(int(doc.get("market_user_id") or 0))
    if opp:
        push_opportunity_to_external_crm(opp, doc)
    return doc
