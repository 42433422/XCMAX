"""Interfaces for each customer-service capability; no handler imports the Mod facade."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any, Protocol

from fastapi import Request

Payload = dict[str, Any]
Employee = Callable[[Payload], Awaitable[Payload]]


@dataclass(frozen=True, eq=False)
class Environment:
    now: Callable[[], str]
    logger: Callable[[], Logger]
    boundary_errors: Callable[[], tuple[type[Exception], ...]]


class MessageSender(Protocol):
    def send_wechat_message(self, contact: str, message: str) -> Payload: ...


class PipelineRepository(Protocol):
    def load_pipeline(self, market_user_id: int, username: str = "") -> Payload: ...
    def save_pipeline(self, doc: Payload, **kwargs: Any) -> Payload: ...


class PipelineServices(Protocol):
    CrmSyncError: type[Exception]
    PIPELINE_STAGES: Sequence[object]
    PipelineCrmGateError: type[Exception]

    def analyze_customer_pipeline(
        self,
        market_user_id: int,
        *,
        username: str = "",
        message_texts: list[str] | None = None,
        has_binding: bool = False,
        intake_sent: bool = False,
    ) -> dict[str, Any]: ...
    def auto_advance_pipeline_if_ready(
        self, market_user_id: int, *, username: str = ""
    ) -> tuple[dict[str, Any], bool]: ...
    def build_pipeline_funnel_summary(
        self, *, max_clients_per_stage: int = 8
    ) -> dict[str, Any]: ...
    def get_crm_bundle_for_market_user(self, market_user_id: int) -> dict[str, Any]: ...
    def get_enterprise_credentials(
        self, market_user_id: int, *, username: str = ""
    ) -> dict[str, Any]: ...
    def issue_enterprise_credentials(
        self, market_user_id: int, *, username: str = "", password: str | None = None
    ) -> dict[str, Any]: ...
    def list_pipeline_client_summaries(self) -> list[dict[str, Any]]: ...
    def maybe_send_connected_welcome(
        self,
        market_user_id: int,
        *,
        username: str = "",
        contact_name: str = "",
        force: bool = False,
    ) -> dict[str, Any]: ...
    def repair_all_pipelines(self) -> dict[str, Any]: ...
    def repair_pipeline_crm(self, market_user_id: int, *, username: str = "") -> dict[str, Any]: ...
    def set_pipeline_stage(
        self,
        market_user_id: int,
        stage: str,
        *,
        username: str = "",
        source: str = "manual",
        note: str = "",
    ) -> dict[str, Any]: ...


class IntakeServices(Protocol):
    def apply_landing_submission_to_funnel(
        self, payload: dict[str, Any], *, notify_wechat: bool = False
    ) -> dict[str, Any]: ...
    def apply_landing_submission_to_pipeline(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def build_intake_form_notice_message(
        self, *, contact_name: str, form_url: str, brief: str = ""
    ) -> str: ...
    def build_intake_form_url(
        self, market_user_id: int, *, brief: str = "", client_name: str = "", base_url: str = ""
    ) -> str: ...
    async def fetch_submission_by_audit_code(self, audit_code: str) -> dict[str, Any]: ...
    def finalize_intake_submission(
        self,
        market_user_id: int,
        doc: dict[str, Any],
        *,
        username: str = "",
        notify_wechat: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...
    def mark_demand_intake_sent(self, market_user_id: int) -> dict[str, Any]: ...
    def normalize_demand_intake_result(
        self, result: dict[str, Any], *, signed_url: str, fallback_url: str
    ) -> tuple[dict[str, Any], bool]: ...
    async def redeem_submission_by_audit_code(
        self, market_user_id: int, audit_code: str, *, username: str = ""
    ) -> dict[str, Any]: ...
    async def sync_intake_from_market_if_newer(
        self, market_user_id: int, *, username: str = ""
    ) -> dict[str, Any] | None: ...
    def verify_webhook_secret(self, header: str | None) -> bool: ...


class CrmServices(Protocol):
    CrmSyncError: type[Exception]

    def get_crm_bundle_for_market_user(self, market_user_id: int) -> dict[str, Any]: ...
    async def pull_external_crm_for_market_user(
        self, market_user_id: int, *, username: str = ""
    ) -> dict[str, Any]: ...
    async def push_external_crm_for_market_user(
        self, market_user_id: int, *, username: str = ""
    ) -> dict[str, Any]: ...
    def sync_crm_from_pipeline_doc(self, doc: dict[str, Any]) -> dict[str, Any]: ...


class ChangesServices(Protocol):
    def _authorization_from_request(self, request: Request, body: dict[str, Any]) -> str: ...
    def _primary_contact_name(self, market_user_id: int) -> str: ...
    async def _proxy_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        authorization: str = "",
        extra_headers: dict[str, str] | None = None,
        return_error_payload: bool = False,
        sensitive: bool = False,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> object: ...
    def build_change_request_wechat_message(
        self, row: dict[str, Any], *, client_name: str = ""
    ) -> str: ...
    def build_ops_dispatch_task_description(
        self, row: dict[str, Any], *, market_user_id: int, client_name: str = ""
    ) -> str: ...
    def create_change_request(
        self,
        market_user_id: int,
        *,
        change_type: str,
        title: str,
        description: str = "",
        priority: str = "normal",
        username: str = "",
        source: str = "enterprise_portal",
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...
    def get_desktop_automation_service(self) -> MessageSender: ...
    def list_change_requests(
        self, market_user_id: int, *, username: str = ""
    ) -> list[dict[str, Any]]: ...
    def mark_change_request_ops_dispatched(
        self,
        market_user_id: int,
        ticket_id: str,
        *,
        job_id: str = "",
        error: str = "",
        username: str = "",
    ) -> dict[str, Any]: ...
    def mark_change_request_wechat_notified(
        self, market_user_id: int, ticket_id: str, *, username: str = ""
    ) -> dict[str, Any]: ...
    def update_change_request_status(
        self,
        market_user_id: int,
        ticket_id: str,
        *,
        status: str,
        admin_note: str = "",
        username: str = "",
    ) -> dict[str, Any]: ...


class DeliveryServices(Protocol):
    def _primary_contact_name(self, market_user_id: int) -> str: ...
    def build_delivery_progress_message(
        self, doc: dict[str, Any], *, client_name: str = ""
    ) -> str: ...
    def confirm_signoff(
        self, signoff_id: int, *, market_user_id: int, username: str = ""
    ) -> dict[str, Any]: ...
    def create_signoff_request(
        self, market_user_id: int, *, username: str = "", signed_by: str = "", notes: str = ""
    ) -> dict[str, Any]: ...
    def ensure_delivery_on_doc(self, doc: dict[str, Any]) -> dict[str, Any]: ...
    def get_desktop_automation_service(self) -> MessageSender: ...
    def notify_software_delivery(
        self, market_user_id: int, *, username: str = "", force: bool = False
    ) -> dict[str, Any]: ...
    def set_pipeline_stage(
        self,
        market_user_id: int,
        stage: str,
        *,
        username: str = "",
        source: str = "manual",
        note: str = "",
    ) -> dict[str, Any]: ...
    def try_confirm_payment_and_invoice(
        self,
        market_user_id: int,
        doc: dict[str, Any],
        *,
        message_texts: list[str] | None = None,
        force: bool = False,
        payment_reference: str = "",
    ) -> dict[str, Any]: ...
    def update_delivery_plan(
        self,
        doc: dict[str, Any],
        *,
        expected_delivery_at: str = "",
        milestones: list[dict[str, Any]] | None = None,
        start_delivery: bool = False,
    ) -> dict[str, Any]: ...


class ContractsServices(Protocol):
    def apply_contract_snapshot_to_doc(
        self, doc: dict[str, Any], values: dict[str, Any]
    ) -> dict[str, Any]: ...
    def build_contract_wechat_hint(self, party_a_name: str, filename: str) -> str: ...
    def build_merged_fields(self, market_user_id: int, *, username: str = "") -> dict[str, str]: ...
    def contract_assets_dir(self) -> Path: ...
    def generate_contract_docx(
        self, market_user_id: int, *, username: str = "", field_values: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...
    def generated_contracts_dir(self) -> Path: ...
    def list_field_schema(self) -> list[dict[str, str]]: ...
    def load_field_overrides(self, market_user_id: int) -> dict[str, Any]: ...
    def save_field_overrides(
        self, market_user_id: int, values: dict[str, Any], *, username: str = ""
    ) -> dict[str, Any]: ...


class MessagingServices(Protocol):
    def get_desktop_automation_service(self) -> MessageSender: ...
    def maybe_send_connected_welcome(
        self,
        market_user_id: int,
        *,
        username: str = "",
        contact_name: str = "",
        force: bool = False,
    ) -> dict[str, Any]: ...
    def maybe_send_intake_form_notice(
        self,
        market_user_id: int,
        *,
        username: str = "",
        contact_name: str = "",
        brief: str = "",
        force: bool = False,
    ) -> dict[str, Any]: ...
