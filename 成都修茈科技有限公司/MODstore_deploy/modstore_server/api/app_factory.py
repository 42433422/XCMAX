# mypy: disable-error-code="assignment"
# isort: skip_file
# ruff: noqa: E402
"""FastAPI application factory.

Gateway note: payment proxy is wired in ``middleware_registry.register_all_middleware``
via ``_payment_backend_proxy_middleware`` wrapping ``payment_backend_proxy_middleware``.
"""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI

from modstore_server.env_loader import load_modstore_env

_deploy_root = Path(__file__).resolve().parents[2]
_preserved_db_path = (os.environ.get("MODSTORE_DB_PATH") or "").strip()
load_modstore_env(
    _deploy_root,
    preserve_existing=(
        "MODSTORE_JWT_SECRET",
        "ALIPAY_APP_ID",
        "ALIPAY_APP_PRIVATE_KEY",
        "ALIPAY_APP_PRIVATE_KEY_PATH",
        "ALIPAY_ALIPAY_PUBLIC_KEY",
        "ALIPAY_ALIPAY_PUBLIC_KEY_PATH",
        "ALIPAY_NOTIFY_URL",
        "ALIPAY_DEBUG",
        "PAYMENT_SECRET_KEY",
        "PAYMENT_BACKEND",
    ),
)
if _preserved_db_path:
    os.environ["MODSTORE_DB_PATH"] = _preserved_db_path
if os.environ.get("MODSTORE_PYTEST_USE_SQLITE") == "1":
    os.environ.pop("DATABASE_URL", None)

from modstore_server.constants import DEFAULT_API_PORT, DEFAULT_XCAGI_BACKEND_URL
from modstore_server.api.app_config import AppConfig, load_default_config
from modstore_server.api.app_diagnostics import (
    maybe_mount_vibe_subapp as _maybe_mount_vibe_subapp,
    register_neurobus_diagnostics as _register_neurobus_diagnostics,
)
from modstore_server.api.app_metadata import OPENAPI_TAGS as _OPENAPI_TAGS

logger = logging.getLogger(__name__)


from modstore_server.api.app_factory_part01 import (
    _include_optional as _include_optional,
    _iter_route_method_signatures as _iter_route_method_signatures,
    _include_router_without_method_conflicts as _include_router_without_method_conflicts,
    _init_database as _init_database,
    _init_event_subscribers as _init_event_subscribers,
    _init_background_jobs as _init_background_jobs,
    _register_core_routes as _register_core_routes,
)

_FULL_OPTIONAL_MODULES = (
    "modstore_server.public_visualization_api",
    "modstore_server.llm_api",
    "modstore_server.openai_llm_gateway_api",
    "modstore_server.agent_butler_api",
    "modstore_server.account_api",
    "modstore_server.butler_qq_bridge",
    "modstore_server.butler_qq_botpy",
    "modstore_server.notification_api",
    "modstore_server.knowledge_vector_api",
    "modstore_server.knowledge_v2_api",
    "modstore_server.realtime_ws",
    "modstore_server.workflow_api",
    "modstore_server.eskill_api",
    "modstore_server.script_workflow_api",
    "modstore_server.runtime_allowlist_api",
    "modstore_server.email_admin_api",
    "modstore_server.workbench_api",
    "modstore_server.asr_proxy_ws",
    "modstore_server.voice_s2s_ws",
    "modstore_server.voice_unified_ws",
    "modstore_server.workbench_studio_assets_api",
    "modstore_server.employee_api",
    "modstore_server.analytics_api",
    "modstore_server.refund_api",
    "modstore_server.update_installation_api",
    "modstore_server.standard_delivery_api",
    "modstore_server.admin_commerce_api",
    "modstore_server.admin_entitlement_fast_lane_api",
    "modstore_server.admin_diagnostic_terminal_api",
    "modstore_server.ops_api",
    "modstore_server.admin_ops_audit_api",
    "modstore_server.admin_employee_execution_api",
    "modstore_server.admin_employee_autonomy_api",
    "modstore_server.autonomy_decision_evidence_api",
    "modstore_server.customer_value_evidence_api",
    "modstore_server.admin_duty_graph_api",
    "modstore_server.production_line_api",
    "modstore_server.release_train_api",
    "modstore_server.action_items_api",
    "modstore_server.public_action_board_api",
    "modstore_server.public_company_hall_api",
    "modstore_server.redline_approval_api",
    "modstore_server.ai_employee_account_api",
    "modstore_server.employee_change_request_api",
    "modstore_server.yuangon_onboard_admin_api",
    "modstore_server.webhook_api",
    "modstore_server.health_api",
    "modstore_server.health_check_api",
    "modstore_server.payment_health_api",
    "modstore_server.openapi_connector_api",
    "modstore_server.customer_service_api",
    "modstore_server.developer_api",
    "modstore_server.developer_key_export_api",
    "modstore_server.webhook_subscription_api",
    "modstore_server.templates_api",
    "modstore_server.sandbox_api",
    "modstore_server.employee_status_api",
    "modstore_server.self_maintenance_loop_api",
    "modstore_server.on_demand_orchestrate_api",
    "modstore_server.inbound_webhook_api",
    "modstore_server.author_earnings",
    "modstore_server.store_lifecycle_api",
    "modstore_server.invoice_api",
    "modstore_server.reconciliation",
    "modstore_server.telemetry_internal_api",
    "modstore_server.subscription_renewer",
    "modstore_server.xcmax_admin_api",
    "modstore_server.strategic_layer_api",
    "modstore_server.api.host_config_routes",
)

_LLM_ONLY_OPTIONAL_MODULES = (
    "modstore_server.llm_api",
    "modstore_server.openai_llm_gateway_api",
    "modstore_server.health_api",
)


from modstore_server.api.app_factory_part02 import (
    _register_optional_routes as _register_optional_routes,
    _register_diagnostics as _register_diagnostics,
    create_app as create_app,
)

__all__ = ["AppConfig", "create_app", "load_default_config"]
