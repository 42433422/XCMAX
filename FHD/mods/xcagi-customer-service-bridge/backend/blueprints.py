"""客服业务页桥接 Mod（里程碑 K）— 页面经 Mod 路由，数据 API 仍走宿主/其它 bridge。"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CUSTOMER_SERVICE_BRIDGE_MOD_ID = "xcagi-customer-service-bridge"


class DemandIntakeBody(BaseModel):
    brief: str = Field(..., min_length=1, max_length=4000, description="业务背景/客户画像")
    client_name: str = Field(default="", max_length=128)
    form_url: str = Field(default="", max_length=512)
    channel: str = Field(default="wechat", max_length=32)
    use_llm: bool = False
    market_user_id: Optional[int] = Field(default=None, description="关联企业客户 ID")


class DemandFormSyncBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    landing_contact_id: Optional[int] = None
    name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=256)
    message: str = Field(default="", max_length=8000)
    desktop_os: str = Field(default="", max_length=16)
    need_mobile: bool = Field(default=True)
    submitted_at: str = Field(default="", max_length=64)


class LandingFunnelSyncBody(BaseModel):
    market_user_id: Optional[int] = Field(default=None, description="无账户时仅写 CRM 线索")
    landing_contact_id: Optional[int] = None
    audit_code: str = Field(default="", max_length=32)
    name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=256)
    message: str = Field(default="", max_length=8000)
    desktop_os: str = Field(default="", max_length=16)
    need_mobile: bool = Field(default=True)
    submitted_at: str = Field(default="", max_length=64)
    intake_source: str = Field(default="", max_length=64)


class ChangeRequestCreateBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    change_type: str = Field(..., max_length=32)
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=8000)
    priority: str = Field(default="normal", max_length=16)
    source: str = Field(default="enterprise_portal", max_length=64)


class ChangeRequestStatusBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    status: str = Field(..., max_length=32)
    admin_note: str = Field(default="", max_length=2000)


class ChangeRequestNotifyBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    contact_name: str = Field(default="", max_length=256)


class DemandFormManualBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=256)
    message: str = Field(..., min_length=1, max_length=8000)
    desktop_os: str = Field(default="", max_length=16)
    need_mobile: bool = Field(default=True)


class DemandFormRedeemCodeBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    audit_code: str = Field(..., min_length=4, max_length=32)


class PipelineBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    stage: Optional[str] = Field(default=None, max_length=32)
    intake_sent: bool = False
    manual: bool = Field(
        default=True,
        description="手动改阶段时写入 timeline（source=manual）",
    )
    note: str = Field(default="", max_length=200)
    signoff_id: Optional[int] = Field(default=None, gt=0)
    force: bool = Field(default=False, description="忽略已发送标记（如重发安装包）")


class EnterpriseCredentialsIssueBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=128, description="留空则自动生成临时密码")


class AnalyzePipelineBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    has_binding: bool = False
    intake_sent: bool = False


class ContractFieldsBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    values: Dict[str, Any] = Field(default_factory=dict)


class ContractGenerateBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    values: Dict[str, Any] = Field(default_factory=dict)


class DeliveryPlanBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    expected_delivery_at: str = Field(default="", max_length=32)
    milestones: list[Dict[str, Any]] = Field(default_factory=list)
    start_delivery: bool = False
    stage: Optional[str] = Field(default=None, max_length=32)


class DeliveryPaymentBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    force_confirm: bool = False
    payment_reference: str = Field(default="", max_length=200)
    advance_stage: bool = True


class WechatSendBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    contact_name: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=8000)
    username: str = Field(default="", max_length=128)


class ConnectedWelcomeBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    contact_name: str = Field(default="", max_length=256)
    force: bool = False


class IntakeNoticeBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    contact_name: str = Field(default="", max_length=256)
    brief: str = Field(default="", max_length=4000)
    force: bool = False


class PassivePollBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    dry_run: bool = Field(default=True, description="True=只探测不发送")
    auto_reply: bool = Field(default=True)
    max_replies: int = Field(default=0, ge=0, le=5, description="0=按绑定群数每群 1 条")
    use_llm: bool = Field(default=True, description="True=用 LLM 生成回复，失败则回退模板")
    skip_sync: bool = Field(
        default=False,
        description="True=跳过服务端同步（由前端先调 refresh_messages，与数据来源按钮一致）",
    )
    refresh_count_new: int | None = Field(default=None, ge=0)
    refresh_latest_label: str = Field(default="", max_length=32)
    catch_up_latest: bool = Field(
        default=False,
        description="True=手动被动回复时可补答游标时刻的最新一条他人消息",
    )


class PassiveLoopConfigBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    poll_enabled: bool = False
    poll_interval_sec: int = Field(default=60, ge=10, le=600)


async def _run_user_cs_employee(payload: Dict[str, Any]) -> Dict[str, Any]:
    """调用 user-customer-service-officer 员工包（mods/_employees）。"""
    try:
        from app.infrastructure.mods import get_mod_registry  # type: ignore
        from app.mod_sdk.mods_bus import import_mod_backend_py  # type: ignore

        reg = get_mod_registry()
        meta = reg.get_mod_metadata("user-customer-service-officer")
        mod_path = getattr(meta, "mod_path", "") if meta else ""
        if not mod_path:
            here = os.path.dirname(os.path.abspath(__file__))
            guess = os.path.normpath(
                os.path.join(here, "..", "..", "..", "_employees", "user-customer-service-officer")
            )
            if os.path.isdir(guess):
                mod_path = guess
        if mod_path:
            mod = import_mod_backend_py(
                mod_path, "user-customer-service-officer", "employees/user_customer_service_officer"
            )
            if mod and hasattr(mod, "run"):
                out = mod.run(payload, {})
                if hasattr(out, "__await__"):
                    out = await out
                return {"success": True, "data": out}
    except Exception as exc:
        logger.exception("user-cs employee run failed")
        return {"success": False, "error": str(exc)[:500], "data": {"ok": False, "error": str(exc)[:500]}}

    return {
        "success": False,
        "error": "user-customer-service-officer 未安装",
        "data": {"ok": False, "error": "请确认 mods/_employees/user-customer-service-officer 已安装并在岗"},
    }


def register_fastapi_routes(app, mod_id: str) -> None:
    from fastapi import APIRouter

    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"customer-service-bridge-{mod_id}"])

    @router.get("/status")
    def status():
        from app.mod_sdk.customer_service_pages_compat import list_customer_service_pages_registry

        return {
            "success": True,
            "data": {
                "ok": True,
                "mod_id": mod_id,
                "registry": list_customer_service_pages_registry(),
                "user_cs_employee_id": "user-customer-service-officer",
            },
        }

    @router.get("/user-cs/status")
    async def user_cs_status():
        return await _run_user_cs_employee({"action": "status"})

    @router.post("/user-cs/demand-intake")
    async def user_cs_demand_intake(body: DemandIntakeBody):
        from app.services.user_cs_demand_form import build_intake_form_url

        signed_url = ""
        if body.market_user_id:
            signed_url = build_intake_form_url(
                int(body.market_user_id),
                brief=body.brief,
                client_name=body.client_name,
                base_url=body.form_url or "",
            )
        payload = {
            "action": "demand_intake",
            "brief": body.brief,
            "client_name": body.client_name,
            "form_url": signed_url or body.form_url,
            "channel": body.channel,
            "use_llm": body.use_llm,
        }
        result = await _run_user_cs_employee(payload)
        if result.get("success") and signed_url:
            data = result.get("data") or {}
            if isinstance(data, dict):
                items = list(data.get("items") or [])
                if items and isinstance(items[0], dict):
                    items[0] = {**items[0], "form_url": signed_url}
                    if isinstance(items[0].get("message_text"), str) and signed_url not in items[0]["message_text"]:
                        items[0]["message_text"] = items[0]["message_text"].replace(
                            body.form_url or "https://xiu-ci.com/contact.html",
                            signed_url,
                        )
                    data["items"] = items
                    data["form_url"] = signed_url
                    result["data"] = data
        if body.market_user_id and result.get("success"):
            try:
                from app.services.user_cs_pipeline import load_pipeline, save_pipeline

                doc = load_pipeline(int(body.market_user_id))
                doc["intake_sent"] = True
                doc["stage"] = "intake"
                now = datetime.now(timezone.utc).isoformat()
                tl = list(doc.get("timeline") or [])
                tl.append({"stage": "intake", "at": now, "source": "demand_intake"})
                doc["timeline"] = tl[-30:]
                save_pipeline(doc)
            except Exception:
                logger.exception("pipeline update after demand intake failed")
        return result

    @router.get("/user-cs/clients")
    async def user_cs_list_clients():
        """已有商机 pipeline 档案的市场用户（供内部客服列表与「添加客户」合并）。"""
        from app.services.user_cs_pipeline import list_pipeline_client_summaries

        return {"success": True, "data": {"clients": list_pipeline_client_summaries()}}

    @router.get("/user-cs/pipeline/funnel")
    async def user_cs_pipeline_funnel(max_clients_per_stage: int = 8):
        from app.services.user_cs_pipeline import PIPELINE_STAGES, build_pipeline_funnel_summary

        data = build_pipeline_funnel_summary(max_clients_per_stage=max_clients_per_stage)
        return {
            "success": True,
            "data": {**data, "stage_definitions": PIPELINE_STAGES},
        }

    @router.post("/user-cs/pipeline/repair-crm")
    async def user_cs_pipeline_repair_crm(body: PipelineBody):
        from app.services.user_cs_crm_store import CrmSyncError, get_crm_bundle_for_market_user
        from app.services.user_cs_pipeline import PipelineCrmGateError, repair_pipeline_crm

        try:
            doc = repair_pipeline_crm(int(body.market_user_id), username=body.username)
            uid = int(body.market_user_id)
            return {
                "success": True,
                "data": {"pipeline": doc, "crm": get_crm_bundle_for_market_user(uid)},
            }
        except (PipelineCrmGateError, CrmSyncError) as exc:
            return {"success": False, "error": str(exc), "crm_gate": True}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/pipeline/repair-all")
    async def user_cs_pipeline_repair_all(body: PipelineBody):
        from app.services.user_cs_pipeline import repair_all_pipelines

        summary = repair_all_pipelines(username=body.username)
        return {"success": True, "data": summary}

    @router.get("/user-cs/enterprise-credentials")
    async def user_cs_get_enterprise_credentials(
        market_user_id: int,
        username: str = "",
    ):
        from app.services.user_cs_enterprise_credentials import get_enterprise_credentials

        data = get_enterprise_credentials(int(market_user_id), username=username)
        return {"success": True, "data": data}

    @router.post("/user-cs/enterprise-credentials/issue")
    async def user_cs_issue_enterprise_credentials(body: EnterpriseCredentialsIssueBody):
        from app.services.user_cs_enterprise_credentials import issue_enterprise_credentials

        pwd = (body.password or "").strip() or None
        result = issue_enterprise_credentials(
            int(body.market_user_id),
            username=body.username,
            password=pwd,
        )
        if not result.get("ok"):
            return {"success": False, "error": result.get("error") or "issue_failed"}
        return {"success": True, "data": result}

    @router.get("/user-cs/pipeline")
    async def user_cs_get_pipeline(
        market_user_id: int,
        username: str = "",
        auto_advance: bool = False,
    ):
        from app.services.user_cs_pipeline import (
            PIPELINE_STAGES,
            auto_advance_pipeline_if_ready,
            load_pipeline,
        )

        uid = int(market_user_id)
        advanced = False
        if auto_advance:
            doc, advanced = auto_advance_pipeline_if_ready(uid, username=username)
        else:
            doc = load_pipeline(uid, username=username)
        from app.services.user_cs_crm_store import get_crm_bundle_for_market_user

        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "stages": PIPELINE_STAGES,
                "advanced": advanced,
                "crm": get_crm_bundle_for_market_user(uid),
            },
        }

    def _apply_pipeline_body(body: PipelineBody):
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline, set_pipeline_stage

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
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            except Exception as exc:
                from app.services.user_cs_pipeline import PipelineCrmGateError

                if isinstance(exc, PipelineCrmGateError):
                    return {"success": False, "error": str(exc), "code": "crm_gate"}
                from app.services.user_cs_crm_store import CrmSyncError

                if isinstance(exc, CrmSyncError):
                    return {
                        "success": False,
                        "error": str(exc),
                        "code": "crm_sync",
                        "details": getattr(exc, "details", ""),
                    }
                raise
        if body.intake_sent:
            doc["intake_sent"] = True
            doc = save_pipeline(doc)
        return {"success": True, "data": {"pipeline": doc}}

    @router.put("/user-cs/pipeline")
    async def user_cs_put_pipeline(body: PipelineBody):
        return _apply_pipeline_body(body)

    @router.post("/user-cs/pipeline/stage")
    async def user_cs_post_pipeline_stage(body: PipelineBody):
        return _apply_pipeline_body(body)

    @router.post("/user-cs/demand-form/sync")
    async def user_cs_demand_form_sync(body: DemandFormSyncBody, request: Request):
        from app.services.user_cs_demand_form import verify_webhook_secret
        from app.services.user_cs_landing_crm import apply_landing_submission_to_funnel

        if not verify_webhook_secret(request.headers.get("x-intake-webhook-secret")):
            return {"success": False, "error": "unauthorized"}
        doc = apply_landing_submission_to_funnel(body.model_dump(), notify_wechat=True)
        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "finalize": {
                    "erp_linked": bool(doc.get("erp_customer_id")),
                    "erp_customer_id": doc.get("erp_customer_id"),
                    "erp_customer_name": doc.get("erp_customer_name"),
                    "crm_funnel_synced_at": doc.get("crm_funnel_synced_at"),
                    "crm_opportunity_id": doc.get("crm_opportunity_id"),
                    "crm_quote_id": doc.get("crm_quote_id"),
                    "intake_done_notice_sent": doc.get("intake_done_notice_sent"),
                },
            },
        }

    @router.post("/user-cs/landing-funnel/sync")
    async def user_cs_landing_funnel_sync(body: LandingFunnelSyncBody, request: Request):
        from app.services.user_cs_demand_form import verify_webhook_secret
        from app.services.user_cs_landing_crm import apply_landing_submission_to_funnel

        if not verify_webhook_secret(request.headers.get("x-intake-webhook-secret")):
            return {"success": False, "error": "unauthorized"}
        payload = body.model_dump(exclude_none=True)
        doc = apply_landing_submission_to_funnel(payload, notify_wechat=bool(payload.get("market_user_id")))
        return {
            "success": True,
            "data": {
                "pipeline": doc if int(payload.get("market_user_id") or 0) > 0 else None,
                "crm_opportunity_id": doc.get("crm_opportunity_id"),
                "anonymous_lead": bool(doc.get("anonymous_lead")),
            },
        }

    @router.get("/user-cs/change-requests")
    def user_cs_change_requests_list(market_user_id: int, username: str = ""):
        from app.services.user_cs_change_request import list_change_requests
        from app.services.user_cs_pipeline import load_pipeline

        uid = int(market_user_id)
        return {
            "success": True,
            "data": {
                "requests": list_change_requests(uid, username=username),
                "pipeline_stage": str(load_pipeline(uid, username=username).get("stage") or "idle"),
            },
        }

    @router.post("/user-cs/change-requests")
    def user_cs_change_requests_create(body: ChangeRequestCreateBody):
        from app.services.user_cs_change_request import create_change_request

        try:
            row = create_change_request(
                int(body.market_user_id),
                change_type=body.change_type,
                title=body.title,
                description=body.description,
                priority=body.priority,
                username=body.username,
                source=body.source,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        return {"success": True, "data": {"request": row}}

    @router.put("/user-cs/change-requests/{ticket_id}/status")
    def user_cs_change_requests_status(ticket_id: str, body: ChangeRequestStatusBody):
        from app.services.user_cs_change_request import update_change_request_status

        try:
            row = update_change_request_status(
                int(body.market_user_id),
                ticket_id,
                status=body.status,
                admin_note=body.admin_note,
                username=body.username,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        return {"success": True, "data": {"request": row}}

    @router.post("/user-cs/change-requests/{ticket_id}/ops-dispatch")
    async def user_cs_change_requests_ops_dispatch(
        ticket_id: str,
        body: ChangeRequestNotifyBody,
        request: Request,
    ):
        from app.services.user_cs_change_request import (
            build_ops_dispatch_task_description,
            list_change_requests,
            mark_change_request_ops_dispatched,
        )
        from app.services.user_cs_pipeline import load_pipeline

        uid = int(body.market_user_id)
        rows = list_change_requests(uid, username=body.username)
        row = next((r for r in rows if str(r.get("id")) == str(ticket_id)), None)
        if not row:
            return {"success": False, "error": "未找到该变更工单"}
        if row.get("ops_dispatch_job_id"):
            return {
                "success": True,
                "data": {
                    "request": row,
                    "job_id": row.get("ops_dispatch_job_id"),
                    "already_dispatched": True,
                },
            }
        client = (body.contact_name or "").strip()
        if not client:
            doc = load_pipeline(uid, username=body.username)
            client = str(doc.get("erp_customer_name") or doc.get("username") or "").strip()
        task_description = build_ops_dispatch_task_description(
            row, market_user_id=uid, client_name=client
        )
        try:
            from app.fastapi_routes.market_account import _authorization_from_request, _proxy_json
        except Exception as exc:
            return {"success": False, "error": f"市场代理不可用: {exc}"}
        authorization = _authorization_from_request(request, {})
        if not authorization:
            return {
                "success": False,
                "error": "尚未绑定修茈服务器账号，无法派发运维任务",
            }
        payload = {
            "task_description": task_description,
            "use_task_router": True,
            "dispatch_source": "cs_change_request",
        }
        raw = await _proxy_json(
            "POST",
            "/api/ops/orchestrate/async",
            json_body=payload,
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(raw, dict) and raw.get("__proxy_error__"):
            err_msg = str(raw.get("payload") or "dispatch_failed")[:500]
            mark_change_request_ops_dispatched(uid, ticket_id, error=err_msg, username=body.username)
            return {"success": False, "error": err_msg}
        job_id = ""
        if isinstance(raw, dict):
            inner = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            job_id = str(
                inner.get("job_id") or inner.get("id") or raw.get("job_id") or ""
            ).strip()
        if not job_id:
            mark_change_request_ops_dispatched(
                uid, ticket_id, error="未返回 job_id", username=body.username
            )
            return {"success": False, "error": "运维派发未返回 job_id", "data": raw}
        updated = mark_change_request_ops_dispatched(
            uid, ticket_id, job_id=job_id, username=body.username
        )
        return {"success": True, "data": {"request": updated, "job_id": job_id, "dispatch": raw}}

    @router.post("/user-cs/change-requests/{ticket_id}/notify-wechat")
    def user_cs_change_requests_notify_wechat(ticket_id: str, body: ChangeRequestNotifyBody):
        from app.services.user_cs_change_request import (
            build_change_request_wechat_message,
            list_change_requests,
            mark_change_request_wechat_notified,
        )
        from app.services.user_cs_intake_notice import _primary_contact_name
        from app.services.user_cs_pipeline import load_pipeline
        from app.desktop_automation.service import get_desktop_automation_service

        uid = int(body.market_user_id)
        rows = list_change_requests(uid, username=body.username)
        row = next((r for r in rows if str(r.get("id")) == str(ticket_id)), None)
        if not row:
            return {"success": False, "error": "未找到该变更工单"}
        contact = (body.contact_name or "").strip() or _primary_contact_name(uid) or ""
        if not contact:
            return {"success": False, "error": "未绑定微信群联系人"}
        doc = load_pipeline(uid, username=body.username)
        client = str(doc.get("username") or body.username or "")
        text = build_change_request_wechat_message(row, client_name=client)
        try:
            send_result = get_desktop_automation_service().send_wechat_message(contact, text)
        except Exception as exc:
            return {"success": False, "error": str(exc)[:300]}
        ok = bool(send_result.get("success")) and bool(
            send_result.get("message_sent", send_result.get("success"))
        )
        if ok:
            mark_change_request_wechat_notified(uid, ticket_id, username=body.username)
        return {
            "success": ok,
            "data": {"message": text, "send_result": send_result},
            "error": "" if ok else str(send_result.get("error") or "发送失败"),
        }

    @router.get("/user-cs/demand-form/link")
    def user_cs_demand_form_link(
        market_user_id: int,
        client_name: str = "",
        brief: str = "",
    ):
        from app.services.user_cs_demand_form import build_intake_form_url

        url = build_intake_form_url(
            int(market_user_id),
            brief=brief,
            client_name=client_name,
        )
        return {"success": True, "data": {"form_url": url}}

    @router.get("/user-cs/demand-form/notice-message")
    def user_cs_demand_form_notice_message(
        market_user_id: int,
        client_name: str = "",
        brief: str = "",
    ):
        from app.services.user_cs_demand_form import build_intake_form_url
        from app.services.user_cs_intake_notice import build_intake_form_notice_message

        uid = int(market_user_id)
        url = build_intake_form_url(uid, brief=brief, client_name=client_name)
        text = build_intake_form_notice_message(
            form_url=url,
            client_name=client_name,
            brief=brief,
        )
        return {"success": True, "data": {"form_url": url, "message": text}}

    @router.post("/user-cs/demand-form/manual")
    async def user_cs_demand_form_manual(body: DemandFormManualBody):
        from datetime import datetime, timezone

        from app.services.user_cs_demand_form import apply_landing_submission_to_pipeline

        doc = apply_landing_submission_to_pipeline(
            int(body.market_user_id),
            {
                "name": body.name.strip(),
                "email": body.email.strip(),
                "phone": body.phone.strip(),
                "company": body.company.strip(),
                "message": body.message.strip(),
                "desktop_os": body.desktop_os.strip(),
                "need_mobile": body.need_mobile,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "intake_source": "manual_card",
            },
            username=body.username,
        )
        return {"success": True, "data": {"pipeline": doc}}

    @router.get("/user-cs/demand-form/by-audit-code")
    async def user_cs_demand_form_by_audit_code(
        audit_code: str,
        market_user_id: int | None = None,
    ):
        from app.services.user_cs_demand_form import fetch_submission_by_audit_code

        try:
            submission = await fetch_submission_by_audit_code(
                audit_code,
                market_user_id=int(market_user_id) if market_user_id else None,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception:
            logger.exception("fetch intake by audit code failed")
            return {"success": False, "error": "获取表单失败，请稍后重试"}
        return {"success": True, "data": {"submission": submission}}

    @router.post("/user-cs/demand-form/redeem-code")
    async def user_cs_demand_form_redeem_code(body: DemandFormRedeemCodeBody):
        from app.services.user_cs_demand_form import redeem_submission_by_audit_code

        try:
            doc = await redeem_submission_by_audit_code(
                int(body.market_user_id),
                body.audit_code,
                username=body.username,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception:
            logger.exception("redeem intake audit code failed")
            return {"success": False, "error": "校验审核码失败，请稍后重试"}
        return {"success": True, "data": {"pipeline": doc}}

    @router.get("/user-cs/demand-form/status")
    async def user_cs_demand_form_status(market_user_id: int, username: str = ""):
        from app.services.user_cs_demand_form import sync_intake_from_market_if_newer
        from app.services.user_cs_intake_finalize import finalize_intake_submission

        uid = int(market_user_id)
        doc = await sync_intake_from_market_if_newer(uid, username=username)
        if doc is None:
            from app.services.user_cs_pipeline import load_pipeline

            doc = load_pipeline(uid, username=username)
        elif doc.get("intake_submitted_at") and not doc.get("crm_funnel_synced_at"):
            doc, _ = finalize_intake_submission(uid, doc, username=username, notify_wechat=False)
        return {"success": True, "data": {"pipeline": doc}}

    @router.post("/user-cs/demand-form/finalize")
    async def user_cs_demand_form_finalize(body: PipelineBody):
        from app.services.user_cs_intake_finalize import finalize_intake_submission
        from app.services.user_cs_pipeline import load_pipeline

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if not doc.get("intake_submitted_at"):
            return {"success": False, "error": "尚未同步到需求提交记录，请先同步官网表单或校验审核码"}
        doc, meta = finalize_intake_submission(
            uid,
            doc,
            username=body.username,
            notify_wechat=True,
        )
        return {"success": True, "data": {"pipeline": doc, "finalize": meta}}

    @router.get("/user-cs/crm")
    def user_cs_crm_bundle(market_user_id: int):
        from app.services.user_cs_crm_store import get_crm_bundle_for_market_user

        return {"success": True, "data": get_crm_bundle_for_market_user(int(market_user_id))}

    @router.post("/user-cs/crm/sync")
    async def user_cs_crm_sync(body: PipelineBody):
        from app.services.user_cs_crm_store import get_crm_bundle_for_market_user, sync_crm_from_pipeline_doc
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        doc = sync_crm_from_pipeline_doc(doc)
        doc = save_pipeline(doc)
        return {
            "success": True,
            "data": {"pipeline": doc, "crm": get_crm_bundle_for_market_user(uid)},
        }

    @router.post("/user-cs/crm/push-external")
    async def user_cs_crm_push_external(body: PipelineBody):
        from app.services.user_cs_crm_store import CrmSyncError, push_external_crm_for_market_user

        try:
            out = push_external_crm_for_market_user(int(body.market_user_id), username=body.username)
            return {"success": True, "data": out}
        except CrmSyncError as exc:
            return {"success": False, "error": str(exc)}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/crm/pull-external")
    async def user_cs_crm_pull_external(body: PipelineBody):
        from app.services.user_cs_crm_store import CrmSyncError, pull_external_crm_for_market_user

        try:
            out = pull_external_crm_for_market_user(int(body.market_user_id), username=body.username)
            pull = out.get("pull") if isinstance(out, dict) else {}
            if isinstance(pull, dict) and not pull.get("ok") and not pull.get("skipped"):
                return {"success": False, "error": pull.get("error") or "pull_failed", "data": out}
            return {"success": True, "data": out}
        except CrmSyncError as exc:
            return {"success": False, "error": str(exc)}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.get("/user-cs/delivery")
    def user_cs_delivery_get(market_user_id: int, username: str = ""):
        from app.services.user_cs_delivery import ensure_delivery_on_doc
        from app.services.user_cs_pipeline import load_pipeline

        doc = ensure_delivery_on_doc(load_pipeline(int(market_user_id), username=username))
        return {
            "success": True,
            "data": {
                "delivery": doc.get("delivery"),
                "payment": doc.get("payment"),
                "invoice": doc.get("invoice"),
            },
        }

    @router.put("/user-cs/delivery/plan")
    def user_cs_delivery_save_plan(body: DeliveryPlanBody):
        from app.services.user_cs_delivery import ensure_delivery_on_doc, update_delivery_plan
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline, set_pipeline_stage

        uid = int(body.market_user_id)
        doc = ensure_delivery_on_doc(load_pipeline(uid, username=body.username))
        doc = update_delivery_plan(
            doc,
            expected_delivery_at=body.expected_delivery_at,
            milestones=body.milestones or None,
            start_delivery=body.start_delivery,
        )
        target_stage = (body.stage or "").strip()
        if body.start_delivery and not target_stage:
            target_stage = "delivering"
        if target_stage:
            try:
                doc = set_pipeline_stage(
                    uid,
                    target_stage,
                    username=body.username,
                    source="delivery_plan",
                    note="delivery_plan_saved",
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
        else:
            doc = save_pipeline(doc)
        return {"success": True, "data": {"pipeline": doc}}

    @router.post("/user-cs/delivery/signoff/request")
    def user_cs_delivery_signoff_request(body: PipelineBody):
        from app.services.user_cs_delivery_signoff import create_signoff_request

        try:
            out = create_signoff_request(
                int(body.market_user_id),
                username=body.username,
                signed_by=body.note or "",
                notes=body.note or "",
            )
            return {"success": True, "data": out}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/delivery/signoff/confirm")
    def user_cs_delivery_signoff_confirm(body: PipelineBody):
        from app.services.user_cs_delivery_signoff import confirm_signoff

        sid = int(getattr(body, "signoff_id", 0) or 0)
        if sid <= 0:
            return {"success": False, "error": "signoff_id required"}
        try:
            out = confirm_signoff(
                sid,
                market_user_id=int(body.market_user_id),
                username=body.username,
            )
            return {"success": True, "data": out}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/delivery/notify-progress")
    def user_cs_delivery_notify_progress(body: PipelineBody):
        from app.services.user_cs_delivery import build_delivery_progress_message, ensure_delivery_on_doc
        from app.services.user_cs_intake_notice import _primary_contact_name
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline
        from app.desktop_automation.service import get_desktop_automation_service

        uid = int(body.market_user_id)
        doc = ensure_delivery_on_doc(load_pipeline(uid, username=body.username))
        contact = _primary_contact_name(uid) or ""
        if not contact:
            return {"success": False, "error": "未绑定微信群联系人"}
        text = build_delivery_progress_message(
            doc,
            client_name=str(doc.get("username") or body.username or ""),
        )
        try:
            send_result = get_desktop_automation_service().send_wechat_message(contact, text)
        except Exception as exc:
            return {"success": False, "error": str(exc)[:300]}
        ok = bool(send_result.get("success")) and bool(
            send_result.get("message_sent", send_result.get("success"))
        )
        if ok:
            delivery = dict(doc.get("delivery") or {})
            delivery["last_progress_notice_at"] = datetime.now(timezone.utc).isoformat()
            doc["delivery"] = delivery
            doc = save_pipeline(doc)
        return {
            "success": ok,
            "data": {"message": text, "send_result": send_result},
            "error": "" if ok else str(send_result.get("error") or "发送失败"),
        }

    @router.post("/user-cs/delivery/notify-software")
    def user_cs_delivery_notify_software(body: PipelineBody):
        from app.services.user_cs_software_delivery import notify_software_delivery

        force = bool(getattr(body, "force", False))
        out = notify_software_delivery(
            int(body.market_user_id),
            username=body.username,
            force=force,
        )
        if not out.get("ok"):
            return {"success": False, "error": out.get("error") or "发送失败", "data": out}
        return {"success": True, "data": out}

    @router.post("/user-cs/delivery/check-payment")
    def user_cs_delivery_check_payment(body: DeliveryPaymentBody):
        from app.services.user_cs_delivery import ensure_delivery_on_doc, try_confirm_payment_and_invoice
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline
        from app.services.wechat_group_customer_bridge import build_starred_group_feed

        uid = int(body.market_user_id)
        doc = ensure_delivery_on_doc(load_pipeline(uid, username=body.username))
        feed = build_starred_group_feed(limit=40, market_user_id=uid)
        texts = [
            str(x.get("content") or x.get("message") or "")
            for x in feed
            if x.get("content") or x.get("message")
        ]
        outcome = try_confirm_payment_and_invoice(
            uid,
            doc,
            message_texts=texts,
            force=body.force_confirm,
            payment_reference=body.payment_reference,
        )
        doc["payment"] = outcome.get("payment") or doc.get("payment")
        if outcome.get("invoice"):
            doc["invoice"] = outcome.get("invoice")
            doc["crm_invoice_id"] = outcome.get("invoice", {}).get("id")
        doc = save_pipeline(doc)
        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "payment_detected": outcome.get("payment_detected"),
                "invoice_created": outcome.get("invoice_created"),
                "invoice": outcome.get("invoice"),
                "market_payment": outcome.get("market_payment"),
                "error": outcome.get("error") or "",
            },
        }

    @router.post("/user-cs/pipeline/auto-advance")
    async def user_cs_auto_advance_pipeline(body: PipelineBody):
        from app.services.user_cs_pipeline import auto_advance_pipeline_if_ready

        doc, advanced = auto_advance_pipeline_if_ready(
            int(body.market_user_id),
            username=body.username,
        )
        return {"success": True, "data": {"pipeline": doc, "advanced": advanced}}

    @router.post("/user-cs/analyze")
    async def user_cs_analyze(body: AnalyzePipelineBody):
        from app.services.user_cs_pipeline import PIPELINE_STAGES, analyze_customer_pipeline
        from app.services.wechat_group_customer_bridge import build_starred_group_feed, get_bindings_for_user

        uid = int(body.market_user_id)
        has_binding = body.has_binding or bool(get_bindings_for_user(uid))
        feed = build_starred_group_feed(limit=20, market_user_id=uid)
        texts = [str(x.get("content") or x.get("message") or "") for x in feed if x.get("content") or x.get("message")]
        preview = texts[0] if texts else ""
        doc = analyze_customer_pipeline(
            uid,
            username=body.username,
            message_texts=texts,
            has_binding=has_binding,
            intake_sent=body.intake_sent,
        )
        if preview:
            doc["last_message_preview"] = preview[:500]
            from app.services.user_cs_pipeline import save_pipeline

            doc = save_pipeline(doc)

        connected_welcome = None
        if str(doc.get("stage")) == "connected" and has_binding:
            from app.services.user_cs_connected_welcome import maybe_send_connected_welcome

            connected_welcome = maybe_send_connected_welcome(uid, username=body.username)
            if connected_welcome.get("sent"):
                from app.services.user_cs_pipeline import load_pipeline

                doc = load_pipeline(uid, username=body.username)

        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "stages": PIPELINE_STAGES,
                "message_count": len(texts),
                "connected_welcome": connected_welcome,
            },
        }

    @router.get("/user-cs/contract/schema")
    def user_cs_contract_schema():
        from app.services.service_contract_fill import list_field_schema

        return {"success": True, "data": list_field_schema()}

    @router.get("/user-cs/contract/fields")
    def user_cs_contract_fields(market_user_id: int, username: str = ""):
        from app.services.service_contract_fill import build_merged_fields, load_field_overrides

        uid = int(market_user_id)
        return {
            "success": True,
            "data": {
                "values": build_merged_fields(uid, username=username),
                "overrides": load_field_overrides(uid),
            },
        }

    @router.put("/user-cs/contract/fields")
    def user_cs_contract_save_fields(body: ContractFieldsBody):
        from app.services.service_contract_fill import build_merged_fields, save_field_overrides
        from app.services.user_cs_delivery import apply_contract_snapshot_to_doc
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline

        uid = int(body.market_user_id)
        save_field_overrides(uid, body.values, username=body.username)
        doc = apply_contract_snapshot_to_doc(load_pipeline(uid, username=body.username), body.values)
        save_pipeline(doc)
        return {
            "success": True,
            "data": build_merged_fields(uid, username=body.username),
        }

    @router.post("/user-cs/contract/generate")
    async def user_cs_contract_generate(body: ContractGenerateBody):
        from app.services.service_contract_fill import (
            build_contract_wechat_hint,
            generate_contract_docx,
        )
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline

        uid = int(body.market_user_id)
        result = generate_contract_docx(uid, username=body.username, field_values=body.values)
        hint = build_contract_wechat_hint(result.get("party_a_name") or body.username, result.get("filename") or "")
        if body.advance_stage:
            try:
                doc = load_pipeline(uid, username=body.username)
                doc["stage"] = "contract_pending"
                now = datetime.now(timezone.utc).isoformat()
                tl = list(doc.get("timeline") or [])
                tl.append({"stage": "contract_pending", "at": now, "source": "contract_generate"})
                doc["timeline"] = tl[-30:]
                doc["contract_filename"] = result.get("filename")
                save_pipeline(doc)
            except Exception:
                logger.exception("pipeline update after contract generate failed")
        return {
            "success": True,
            "data": {
                **result,
                "download_url": f"/api/mod/{mod_id}/user-cs/contract/download/{result.get('filename')}",
                "wechat_hint": hint,
            },
        }

    @router.get("/user-cs/contract/download/{filename}")
    def user_cs_contract_download(filename: str):
        from fastapi.responses import FileResponse

        from app.services.service_contract_fill import generated_contracts_dir

        safe = os.path.basename(filename)
        path = generated_contracts_dir() / safe
        if not path.is_file():
            return {"success": False, "error": "文件不存在"}
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=safe,
        )

    @router.get("/user-cs/contract/sample-pdf")
    def user_cs_contract_sample_pdf():
        from fastapi.responses import FileResponse

        from app.services.service_contract_fill import contract_assets_dir

        path = contract_assets_dir() / "sample_party_b_prefilled.pdf"
        if not path.is_file():
            return {"success": False, "error": "样例 PDF 不存在"}
        return FileResponse(path, media_type="application/pdf", filename="乙方预填样例.pdf")

    @router.post("/user-cs/wechat/send")
    async def user_cs_wechat_send(body: WechatSendBody):
        from app.desktop_automation.service import get_desktop_automation_service
        from app.services.wechat_group_customer_bridge import get_bindings_for_user

        uid = int(body.market_user_id)
        contact = body.contact_name.strip()
        bindings = get_bindings_for_user(uid)
        if not contact and bindings:
            first = bindings[0]
            contact = str(first.get("contact_name") or first.get("remark") or "").strip()
        if not contact:
            return {"success": False, "error": "请先保存群聊绑定，或确认群名称"}

        svc = get_desktop_automation_service()
        result = svc.send_wechat_message(contact, body.message.strip())
        sent = bool(result.get("success")) and bool(result.get("message_sent", result.get("success")))
        if sent:
            try:
                from app.services.user_cs_pipeline import load_pipeline, save_pipeline

                doc = load_pipeline(uid, username=body.username)
                if doc.get("stage") in ("idle", "connected"):
                    doc["stage"] = "connected"
                    save_pipeline(doc)
            except Exception:
                logger.exception("pipeline update after wechat send failed")
        return {"success": sent, "data": result}

    @router.post("/user-cs/wechat/send-connected-welcome")
    async def user_cs_send_connected_welcome(body: ConnectedWelcomeBody):
        from app.services.user_cs_connected_welcome import maybe_send_connected_welcome
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if str(doc.get("stage") or "idle") == "idle":
            doc["stage"] = "connected"
            save_pipeline(doc)

        out = maybe_send_connected_welcome(
            uid,
            username=body.username,
            contact_name=body.contact_name.strip(),
            force=body.force,
        )
        return {"success": bool(out.get("sent")), "data": out}

    @router.post("/user-cs/wechat/send-intake-notice")
    async def user_cs_send_intake_notice(body: IntakeNoticeBody):
        from app.services.user_cs_intake_notice import maybe_send_intake_form_notice
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        stage = str(doc.get("stage") or "idle")
        if stage in ("idle", "connected"):
            doc["stage"] = "intake"
            save_pipeline(doc)

        out = maybe_send_intake_form_notice(
            uid,
            username=body.username,
            contact_name=body.contact_name.strip(),
            brief=body.brief.strip(),
            force=body.force,
        )
        return {"success": bool(out.get("sent")), "data": out}

    @router.get("/user-cs/wechat/llm-status")
    def user_cs_wechat_llm_status(request: Request):
        from app.fastapi_routes.market_account import session_id_from_request
        from app.services.wechat_passive_group_monitor import probe_passive_llm_ready

        return {
            "success": True,
            "data": probe_passive_llm_ready(
                session_id=session_id_from_request(request),
                request=request,
            ),
        }

    @router.post("/user-cs/wechat/passive-poll")
    async def user_cs_passive_poll(request: Request, body: PassivePollBody):
        """被动探测：快照复制解密 → 读绑定群新消息 → 可选自动回复。"""
        from app.fastapi_routes.market_account import session_id_from_request
        from app.services.wechat_passive_group_monitor import passive_poll_once

        out = passive_poll_once(
            market_user_id=int(body.market_user_id),
            username=body.username,
            dry_run=body.dry_run,
            auto_reply=body.auto_reply,
            max_replies=body.max_replies,
            use_llm=body.use_llm,
            skip_sync=body.skip_sync,
            refresh_count_new=body.refresh_count_new,
            refresh_latest_label=body.refresh_latest_label,
            catch_up_latest=body.catch_up_latest,
            session_id=session_id_from_request(request),
            request=request,
        )
        return {"success": bool(out.get("success")), "data": out}

    @router.get("/user-cs/wechat/passive-loop")
    def user_cs_passive_loop_get(market_user_id: int, username: str = ""):
        from app.services.wechat_passive_group_monitor import get_passive_poll_config

        return {"success": True, "data": get_passive_poll_config(market_user_id, username=username)}

    def _user_cs_passive_loop_save(body: PassiveLoopConfigBody) -> dict:
        from app.services.wechat_passive_group_monitor import save_passive_poll_config

        data = save_passive_poll_config(
            int(body.market_user_id),
            username=body.username,
            poll_enabled=body.poll_enabled,
            poll_interval_sec=body.poll_interval_sec,
        )
        return {"success": True, "data": data}

    @router.post(
        "/user-cs/wechat/passive-loop",
        operation_id="mod_user_cs_passive_loop_post",
    )
    def user_cs_passive_loop_post(body: PassiveLoopConfigBody):
        return _user_cs_passive_loop_save(body)

    @router.put(
        "/user-cs/wechat/passive-loop",
        operation_id="mod_user_cs_passive_loop_put",
    )
    def user_cs_passive_loop_put(body: PassiveLoopConfigBody):
        return _user_cs_passive_loop_save(body)

    @router.post("/user-cs/wechat/passive-reset-watch")
    def user_cs_passive_reset_watch(body: PassiveLoopConfigBody):
        from app.services.wechat_passive_group_monitor import reset_passive_watch

        state = reset_passive_watch(int(body.market_user_id), username=body.username)
        return {"success": True, "data": state}

    app.include_router(router)
    logger.info("xcagi-customer-service-bridge registered: %s", mod_id)


def mod_init() -> None:
    logger.info("xcagi-customer-service-bridge mod_init (K)")
