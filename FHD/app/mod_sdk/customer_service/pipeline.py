"""Customer pipeline, credentials and employee status."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import (
    AnalyzePipelineBody,
    EnterpriseCredentialsIssueBody,
    PipelineBody,
)
from .ports import Employee, Environment, Payload, PipelineRepository, PipelineServices


@dataclass(frozen=True, eq=False)
class PipelineHandlers:
    services: PipelineServices
    records: PipelineRepository
    environment: Environment
    employee: Employee
    mod_id: str
    registry: Callable[[], Payload]

    def status(self) -> Payload:
        list_customer_service_pages_registry = self.registry
        return {
            "success": True,
            "data": {
                "ok": True,
                "mod_id": self.mod_id,
                "registry": list_customer_service_pages_registry(),
                "user_cs_employee_id": "user-customer-service-officer",
            },
        }

    async def user_cs_status(self) -> Payload:
        return await self.employee({"action": "status"})

    async def user_cs_list_clients(self) -> Payload:
        """已有商机 pipeline 档案的市场用户（供内部客服列表与「添加客户」合并）。"""
        list_pipeline_client_summaries = self.services.list_pipeline_client_summaries
        return {"success": True, "data": {"clients": list_pipeline_client_summaries()}}

    async def user_cs_pipeline_funnel(self, max_clients_per_stage: int = 8) -> Payload:
        PIPELINE_STAGES = self.services.PIPELINE_STAGES
        build_pipeline_funnel_summary = self.services.build_pipeline_funnel_summary
        data = build_pipeline_funnel_summary(max_clients_per_stage=max_clients_per_stage)
        return {"success": True, "data": {**data, "stage_definitions": PIPELINE_STAGES}}

    async def user_cs_pipeline_repair_crm(self, body: PipelineBody) -> Payload:
        CrmSyncError = self.services.CrmSyncError
        PipelineCrmGateError = self.services.PipelineCrmGateError
        get_crm_bundle_for_market_user = self.services.get_crm_bundle_for_market_user
        repair_pipeline_crm = self.services.repair_pipeline_crm
        try:
            doc = repair_pipeline_crm(int(body.market_user_id), username=body.username)
            uid = int(body.market_user_id)
            return {
                "success": True,
                "data": {"pipeline": doc, "crm": get_crm_bundle_for_market_user(uid)},
            }
        except (PipelineCrmGateError, CrmSyncError):
            return {"success": False, "error": "CRM 服务暂时不可用", "crm_gate": True}
        except ValueError:
            return {"success": False, "error": "请求参数无效"}

    async def user_cs_pipeline_repair_all(self, body: PipelineBody) -> Payload:
        repair_all_pipelines = self.services.repair_all_pipelines
        summary = repair_all_pipelines()
        return {"success": True, "data": summary}

    async def user_cs_get_enterprise_credentials(
        self, market_user_id: int, username: str = ""
    ) -> Payload:
        get_enterprise_credentials = self.services.get_enterprise_credentials
        data = get_enterprise_credentials(int(market_user_id), username=username)
        return {"success": True, "data": data}

    async def user_cs_issue_enterprise_credentials(
        self, body: EnterpriseCredentialsIssueBody
    ) -> Payload:
        issue_enterprise_credentials = self.services.issue_enterprise_credentials
        pwd = (body.password or "").strip() or None
        result = issue_enterprise_credentials(
            int(body.market_user_id), username=body.username, password=pwd
        )
        if not result.get("ok"):
            return {"success": False, "error": result.get("error") or "issue_failed"}
        return {"success": True, "data": result}

    async def user_cs_get_pipeline(
        self, market_user_id: int, username: str = "", auto_advance: bool = False
    ) -> Payload:
        PIPELINE_STAGES = self.services.PIPELINE_STAGES
        auto_advance_pipeline_if_ready = self.services.auto_advance_pipeline_if_ready
        load_pipeline = self.records.load_pipeline
        uid = int(market_user_id)
        advanced = False
        if auto_advance:
            doc, advanced = auto_advance_pipeline_if_ready(uid, username=username)
        else:
            doc = load_pipeline(uid, username=username)
        get_crm_bundle_for_market_user = self.services.get_crm_bundle_for_market_user
        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "stages": PIPELINE_STAGES,
                "advanced": advanced,
                "crm": get_crm_bundle_for_market_user(uid),
            },
        }

    def _apply_pipeline_body(self, body: PipelineBody) -> Payload:
        load_pipeline = self.records.load_pipeline
        save_pipeline = self.records.save_pipeline
        set_pipeline_stage = self.services.set_pipeline_stage
        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if body.stage:
            try:
                doc = set_pipeline_stage(
                    uid,
                    body.stage,
                    username=body.username,
                    source="manual" if body.manual else "api",
                    note=body.note,
                )
            except ValueError:
                return {"success": False, "error": "请求参数无效"}
            except self.environment.boundary_errors() as exc:
                PipelineCrmGateError = self.services.PipelineCrmGateError
                if isinstance(exc, PipelineCrmGateError):
                    return {"success": False, "error": "CRM 服务暂时不可用", "code": "crm_gate"}
                CrmSyncError = self.services.CrmSyncError
                if isinstance(exc, CrmSyncError):
                    return {
                        "success": False,
                        "error": "CRM 同步服务暂时不可用",
                        "code": "crm_sync",
                        "details": getattr(exc, "details", ""),
                    }
                raise
        if body.intake_sent:
            doc["intake_sent"] = True
            doc = save_pipeline(doc)
        return {"success": True, "data": {"pipeline": doc}}

    async def user_cs_put_pipeline(self, body: PipelineBody) -> Payload:
        return self._apply_pipeline_body(body)

    async def user_cs_post_pipeline_stage(self, body: PipelineBody) -> Payload:
        return self._apply_pipeline_body(body)

    async def user_cs_auto_advance_pipeline(self, body: PipelineBody) -> Payload:
        auto_advance_pipeline_if_ready = self.services.auto_advance_pipeline_if_ready
        doc, advanced = auto_advance_pipeline_if_ready(
            int(body.market_user_id), username=body.username
        )
        return {"success": True, "data": {"pipeline": doc, "advanced": advanced}}

    async def user_cs_analyze(self, body: AnalyzePipelineBody) -> Payload:
        PIPELINE_STAGES = self.services.PIPELINE_STAGES
        analyze_customer_pipeline = self.services.analyze_customer_pipeline
        uid = int(body.market_user_id)
        doc = analyze_customer_pipeline(
            uid,
            username=body.username,
            message_texts=[],
            has_binding=body.has_binding,
            intake_sent=body.intake_sent,
        )
        connected_welcome = None
        if str(doc.get("stage")) == "connected" and body.has_binding:
            maybe_send_connected_welcome = self.services.maybe_send_connected_welcome
            connected_welcome = maybe_send_connected_welcome(uid, username=body.username)
            if connected_welcome.get("sent"):
                load_pipeline = self.records.load_pipeline
                doc = load_pipeline(uid, username=body.username)
        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "stages": PIPELINE_STAGES,
                "message_count": 0,
                "connected_welcome": connected_welcome,
            },
        }
