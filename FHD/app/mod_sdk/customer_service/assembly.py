"""Bind the stable host SDK to explicit per-domain interfaces and register public routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter

from app.mod_sdk import host_services

from .changes import ChangesHandlers
from .contracts import ContractsHandlers
from .crm import CrmHandlers
from .delivery import DeliveryHandlers
from .intake import IntakeHandlers
from .messaging import MessagingHandlers
from .pipeline import PipelineHandlers
from .customer_service_ports import (
    ChangesServices,
    ContractsServices,
    CrmServices,
    DeliveryServices,
    Employee,
    Environment,
    IntakeServices,
    MessagingServices,
    Payload,
    PipelineRepository,
    PipelineServices,
)


def _page_registry() -> Payload:
    from app.mod_sdk.customer_service_pages_compat import list_customer_service_pages_registry

    return list_customer_service_pages_registry()


def register_routes(
    router: APIRouter, mod_id: str, employee: Employee, environment: Environment
) -> None:
    # The SDK lazily resolves canonical host implementations. Narrow interfaces keep
    # those late patch points while preventing handlers from reading arbitrary Mod state.
    records = cast(PipelineRepository, host_services)
    pipeline = PipelineHandlers(
        cast(PipelineServices, host_services),
        records,
        environment,
        employee,
        mod_id,
        _page_registry,
    )
    intake = IntakeHandlers(cast(IntakeServices, host_services), records, environment, employee)
    crm = CrmHandlers(cast(CrmServices, host_services), records)
    changes = ChangesHandlers(cast(ChangesServices, host_services), records, environment)
    delivery = DeliveryHandlers(cast(DeliveryServices, host_services), records, environment)
    contracts = ContractsHandlers(
        cast(ContractsServices, host_services), records, environment, mod_id
    )
    messaging = MessagingHandlers(cast(MessagingServices, host_services), records, environment)
    routes: tuple[tuple[str, str, Callable[..., object]], ...] = (
        ("GET", "/status", pipeline.status),
        ("GET", "/user-cs/status", pipeline.user_cs_status),
        ("POST", "/user-cs/demand-intake", intake.user_cs_demand_intake),
        ("GET", "/user-cs/clients", pipeline.user_cs_list_clients),
        ("GET", "/user-cs/pipeline/funnel", pipeline.user_cs_pipeline_funnel),
        ("POST", "/user-cs/pipeline/repair-crm", pipeline.user_cs_pipeline_repair_crm),
        ("POST", "/user-cs/pipeline/repair-all", pipeline.user_cs_pipeline_repair_all),
        ("GET", "/user-cs/enterprise-credentials", pipeline.user_cs_get_enterprise_credentials),
        (
            "POST",
            "/user-cs/enterprise-credentials/issue",
            pipeline.user_cs_issue_enterprise_credentials,
        ),
        ("GET", "/user-cs/pipeline", pipeline.user_cs_get_pipeline),
        ("PUT", "/user-cs/pipeline", pipeline.user_cs_put_pipeline),
        ("POST", "/user-cs/pipeline/stage", pipeline.user_cs_post_pipeline_stage),
        ("POST", "/user-cs/demand-form/sync", intake.user_cs_demand_form_sync),
        ("POST", "/user-cs/landing-funnel/sync", intake.user_cs_landing_funnel_sync),
        ("GET", "/user-cs/change-requests", changes.user_cs_change_requests_list),
        ("POST", "/user-cs/change-requests", changes.user_cs_change_requests_create),
        (
            "PUT",
            "/user-cs/change-requests/{ticket_id}/status",
            changes.user_cs_change_requests_status,
        ),
        (
            "POST",
            "/user-cs/change-requests/{ticket_id}/ops-dispatch",
            changes.user_cs_change_requests_ops_dispatch,
        ),
        (
            "POST",
            "/user-cs/change-requests/{ticket_id}/notify-wechat",
            changes.user_cs_change_requests_notify_wechat,
        ),
        ("GET", "/user-cs/demand-form/link", intake.user_cs_demand_form_link),
        ("GET", "/user-cs/demand-form/notice-message", intake.user_cs_demand_form_notice_message),
        ("POST", "/user-cs/demand-form/manual", intake.user_cs_demand_form_manual),
        ("GET", "/user-cs/demand-form/by-audit-code", intake.user_cs_demand_form_by_audit_code),
        ("POST", "/user-cs/demand-form/redeem-code", intake.user_cs_demand_form_redeem_code),
        ("GET", "/user-cs/demand-form/status", intake.user_cs_demand_form_status),
        ("POST", "/user-cs/demand-form/finalize", intake.user_cs_demand_form_finalize),
        ("GET", "/user-cs/crm", crm.user_cs_crm_bundle),
        ("POST", "/user-cs/crm/sync", crm.user_cs_crm_sync),
        ("POST", "/user-cs/crm/push-external", crm.user_cs_crm_push_external),
        ("POST", "/user-cs/crm/pull-external", crm.user_cs_crm_pull_external),
        ("GET", "/user-cs/delivery", delivery.user_cs_delivery_get),
        ("PUT", "/user-cs/delivery/plan", delivery.user_cs_delivery_save_plan),
        ("POST", "/user-cs/delivery/signoff/request", delivery.user_cs_delivery_signoff_request),
        ("POST", "/user-cs/delivery/signoff/confirm", delivery.user_cs_delivery_signoff_confirm),
        ("POST", "/user-cs/delivery/notify-progress", delivery.user_cs_delivery_notify_progress),
        ("POST", "/user-cs/delivery/notify-software", delivery.user_cs_delivery_notify_software),
        ("POST", "/user-cs/delivery/check-payment", delivery.user_cs_delivery_check_payment),
        ("POST", "/user-cs/pipeline/auto-advance", pipeline.user_cs_auto_advance_pipeline),
        ("POST", "/user-cs/analyze", pipeline.user_cs_analyze),
        ("GET", "/user-cs/contract/schema", contracts.user_cs_contract_schema),
        ("GET", "/user-cs/contract/fields", contracts.user_cs_contract_fields),
        ("PUT", "/user-cs/contract/fields", contracts.user_cs_contract_save_fields),
        ("POST", "/user-cs/contract/generate", contracts.user_cs_contract_generate),
        ("GET", "/user-cs/contract/download/{filename}", contracts.user_cs_contract_download),
        ("GET", "/user-cs/contract/sample-pdf", contracts.user_cs_contract_sample_pdf),
        ("POST", "/user-cs/wechat/send", messaging.user_cs_wechat_send),
        (
            "POST",
            "/user-cs/wechat/send-connected-welcome",
            messaging.user_cs_send_connected_welcome,
        ),
        ("POST", "/user-cs/wechat/send-intake-notice", messaging.user_cs_send_intake_notice),
    )
    for method, path, endpoint in routes:
        router.add_api_route(path, endpoint, methods=[method], response_model=None)
