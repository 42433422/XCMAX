"""CRM view synchronization and awaited external bridge calls."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    PipelineBody,
)
from .customer_service_ports import CrmServices, Payload, PipelineRepository


@dataclass(frozen=True, eq=False)
class CrmHandlers:
    services: CrmServices
    records: PipelineRepository

    def user_cs_crm_bundle(self, market_user_id: int) -> Payload:
        get_crm_bundle_for_market_user = self.services.get_crm_bundle_for_market_user
        return {"success": True, "data": get_crm_bundle_for_market_user(int(market_user_id))}

    async def user_cs_crm_sync(self, body: PipelineBody) -> Payload:
        get_crm_bundle_for_market_user = self.services.get_crm_bundle_for_market_user
        load_pipeline = self.records.load_pipeline
        save_pipeline = self.records.save_pipeline
        sync_crm_from_pipeline_doc = self.services.sync_crm_from_pipeline_doc
        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        doc = sync_crm_from_pipeline_doc(doc)
        doc = save_pipeline(doc)
        return {
            "success": True,
            "data": {"pipeline": doc, "crm": get_crm_bundle_for_market_user(uid)},
        }

    async def user_cs_crm_push_external(self, body: PipelineBody) -> Payload:
        CrmSyncError = self.services.CrmSyncError
        push_external_crm_for_market_user = self.services.push_external_crm_for_market_user
        try:
            out = await push_external_crm_for_market_user(
                int(body.market_user_id), username=body.username
            )
            return {"success": True, "data": out}
        except CrmSyncError:
            return {"success": False, "error": "CRM 同步服务暂时不可用"}
        except ValueError:
            return {"success": False, "error": "请求参数无效"}

    async def user_cs_crm_pull_external(self, body: PipelineBody) -> Payload:
        CrmSyncError = self.services.CrmSyncError
        pull_external_crm_for_market_user = self.services.pull_external_crm_for_market_user
        try:
            out = await pull_external_crm_for_market_user(
                int(body.market_user_id), username=body.username
            )
            pull = out.get("pull") if isinstance(out, dict) else {}
            if isinstance(pull, dict) and (not pull.get("ok")) and (not pull.get("skipped")):
                return {"success": False, "error": pull.get("error") or "pull_failed", "data": out}
            return {"success": True, "data": out}
        except CrmSyncError:
            return {"success": False, "error": "CRM 同步服务暂时不可用"}
        except ValueError:
            return {"success": False, "error": "请求参数无效"}
