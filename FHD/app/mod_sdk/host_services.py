"""Lazy compatibility contract for host capabilities consumed by bundled Mods.

Every name in this module is an explicit part of the Mod SDK surface.  Imports
remain lazy so loading a small Mod does not initialize unrelated databases,
routers, AI clients, or optional integrations.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "AccessRequestPayload": ("app.fastapi_routes.lan_routes", "AccessRequestPayload"),
    "AccessRequestReview": ("app.fastapi_routes.lan_admin_routes", "AccessRequestReview"),
    "ActivateRequest": ("app.fastapi_routes.lan_routes", "ActivateRequest"),
    "CrmSyncError": ("app.services.user_cs_crm_store", "CrmSyncError"),
    "EventPriority": ("app.neuro_bus.events.base", "EventPriority"),
    "ExcelSchemaUnderstandingService": (
        "app.infrastructure.excel.schema_service",
        "ExcelSchemaUnderstandingService",
    ),
    "IssueKeyRequest": ("app.fastapi_routes.lan_admin_routes", "IssueKeyRequest"),
    "LanSettingsUpdate": ("app.fastapi_routes.lan_settings_routes", "LanSettingsUpdate"),
    "NeuroEvent": ("app.neuro_bus.events.base", "NeuroEvent"),
    "PIPELINE_STAGES": ("app.services.user_cs_pipeline", "PIPELINE_STAGES"),
    "PipelineCrmGateError": ("app.services.user_cs_pipeline", "PipelineCrmGateError"),
    "Product": ("app.db.models.product", "Product"),
    "SQLAlchemyProductRepository": (
        "app.infrastructure.repositories.product_repository_impl",
        "SQLAlchemyProductRepository",
    ),
    "SQLAlchemyShipmentRepository": (
        "app.infrastructure.repositories.shipment_repository_impl",
        "SQLAlchemyShipmentRepository",
    ),
    "SessionLocal": ("app.db", "SessionLocal"),
    "_authorization_from_request": (
        "app.fastapi_routes.market_account",
        "_authorization_from_request",
    ),
    "_customer_row_matches_keyword": (
        "app.fastapi_routes.domains.db.queries",
        "_customer_row_matches_keyword",
    ),
    "_customers_schema_hint_if_empty": (
        "app.fastapi_routes.domains.db.queries",
        "_customers_schema_hint_if_empty",
    ),
    "_handle_import_excel_to_database": (
        "app.application.tools.workflow",
        "_handle_import_excel_to_database",
    ),
    "_load_customers_rows": (
        "app.fastapi_routes.domains.db.queries",
        "_load_customers_rows",
    ),
    "_load_products_list_impl_pg": (
        "app.fastapi_routes.domains.db.product_queries",
        "_load_products_list_impl_pg",
    ),
    "_parse_excel_header_row_1based": (
        "app.application.tools.workflow",
        "_parse_excel_header_row_1based",
    ),
    "_primary_contact_name": ("app.services.user_cs_intake_notice", "_primary_contact_name"),
    "_proxy_json": ("app.fastapi_routes.market_account", "_proxy_json"),
    "_read_excel_dataframe": ("app.application.tools.workflow", "_read_excel_dataframe"),
    "_shared_resolve_table_spec": (
        "app.application.office_plaintext_generate",
        "resolve_table_spec",
    ),
    "activate": ("app.fastapi_routes.lan_routes", "activate"),
    "alipay_trade_notify": ("app.fastapi_routes.model_payment", "alipay_trade_notify"),
    "analyze_customer_pipeline": (
        "app.services.user_cs_pipeline",
        "analyze_customer_pipeline",
    ),
    "apply_contract_snapshot_to_doc": (
        "app.services.user_cs_delivery",
        "apply_contract_snapshot_to_doc",
    ),
    "apply_landing_submission_to_funnel": (
        "app.services.user_cs_landing_crm",
        "apply_landing_submission_to_funnel",
    ),
    "apply_landing_submission_to_pipeline": (
        "app.services.user_cs_demand_form",
        "apply_landing_submission_to_pipeline",
    ),
    "approval_workspace_app_service": (
        "app.application.approval_workspace_app_service",
        "",
    ),
    "approve_access_request_endpoint": (
        "app.fastapi_routes.lan_admin_routes",
        "approve_access_request_endpoint",
    ),
    "auto_advance_pipeline_if_ready": (
        "app.services.user_cs_pipeline",
        "auto_advance_pipeline_if_ready",
    ),
    "build_change_request_wechat_message": (
        "app.services.user_cs_change_request",
        "build_change_request_wechat_message",
    ),
    "build_contract_wechat_hint": (
        "app.services.service_contract_fill",
        "build_contract_wechat_hint",
    ),
    "build_delivery_progress_message": (
        "app.services.user_cs_delivery",
        "build_delivery_progress_message",
    ),
    "build_intake_form_notice_message": (
        "app.services.user_cs_intake_notice",
        "build_intake_form_notice_message",
    ),
    "build_intake_form_url": ("app.services.user_cs_demand_form", "build_intake_form_url"),
    "build_merged_fields": ("app.services.service_contract_fill", "build_merged_fields"),
    "build_ops_dispatch_task_description": (
        "app.services.user_cs_change_request",
        "build_ops_dispatch_task_description",
    ),
    "build_pipeline_funnel_summary": (
        "app.services.user_cs_pipeline",
        "build_pipeline_funnel_summary",
    ),
    "build_starred_group_feed": (
        "app.services.wechat_group_customer_bridge",
        "build_starred_group_feed",
    ),
    "checkout": ("app.fastapi_routes.model_payment", "checkout"),
    "close_trade": ("app.fastapi_routes.model_payment", "close_trade"),
    "compat_purchase_units_by_name": (
        "app.fastapi_routes.ai_assistant",
        "compat_purchase_units_by_name",
    ),
    "confirm_signoff": ("app.services.user_cs_delivery_signoff", "confirm_signoff"),
    "contract_assets_dir": ("app.services.service_contract_fill", "contract_assets_dir"),
    "create_change_request": (
        "app.services.user_cs_change_request",
        "create_change_request",
    ),
    "create_signoff_request": (
        "app.services.user_cs_delivery_signoff",
        "create_signoff_request",
    ),
    "customers_create": ("app.fastapi_routes.domains.customer.routes", "customers_create"),
    "customers_delete": ("app.fastapi_routes.domains.customer.routes", "customers_delete"),
    "customers_get_one": ("app.fastapi_routes.domains.customer.routes", "customers_get_one"),
    "customers_update": ("app.fastapi_routes.domains.customer.routes", "customers_update"),
    "diagnostics": ("app.fastapi_routes.model_payment", "diagnostics"),
    "ensure_delivery_on_doc": ("app.services.user_cs_delivery", "ensure_delivery_on_doc"),
    "entitlements": ("app.fastapi_routes.model_payment", "entitlements"),
    "fetch_submission_by_audit_code": (
        "app.services.user_cs_demand_form",
        "fetch_submission_by_audit_code",
    ),
    "finalize_intake_submission": (
        "app.services.user_cs_intake_finalize",
        "finalize_intake_submission",
    ),
    "generate_contract_docx": (
        "app.services.service_contract_fill",
        "generate_contract_docx",
    ),
    "generate_office_file": ("app.services.kitten_ai_document.generate", "generate_office_file"),
    "generated_contracts_dir": (
        "app.services.service_contract_fill",
        "generated_contracts_dir",
    ),
    "get_bindings_for_user": (
        "app.services.wechat_group_customer_bridge",
        "get_bindings_for_user",
    ),
    "get_crm_bundle_for_market_user": (
        "app.services.user_cs_crm_store",
        "get_crm_bundle_for_market_user",
    ),
    "get_db": ("app.db.session", "get_db"),
    "get_desktop_automation_service": (
        "app.desktop_automation.service",
        "get_desktop_automation_service",
    ),
    "get_domain_registry": ("app.neuro_bus.domains.base", "get_domain_registry"),
    "get_enterprise_credentials": (
        "app.services.user_cs_enterprise_credentials",
        "get_enterprise_credentials",
    ),
    "get_excel_vector_ingest_app_service": (
        "app.application",
        "get_excel_vector_ingest_app_service",
    ),
    "get_llm_client": ("app.infrastructure.llm.client", "get_llm_client"),
    "get_mod_registry": ("app.infrastructure.mods", "get_mod_registry"),
    "get_neuro_bus": ("app.neuro_bus.bus", "get_neuro_bus"),
    "get_neuro_bus_manager": ("app.neuro_bus.bus_setup", "get_neuro_bus_manager"),
    "get_neurobus_health": (
        "app.neuro_bus.integrations.fastapi_integration",
        "get_neurobus_health",
    ),
    "get_passive_poll_config": (
        "app.services.wechat_passive_group_monitor",
        "get_passive_poll_config",
    ),
    "get_plans": ("app.fastapi_routes.model_payment", "get_plans"),
    "get_processor_coordinator": (
        "app.domain.neuro.processors.coordinator",
        "get_processor_coordinator",
    ),
    "get_settings_view": ("app.fastapi_routes.lan_settings_routes", "get_settings"),
    "get_settings": ("app.fastapi_routes.lan_settings_routes", "get_settings"),
    "get_shipment_application_service_core": (
        "app.bootstrap",
        "get_shipment_application_service_core",
    ),
    "handle_excel_analysis": ("app.application.tools.workflow", "handle_excel_analysis"),
    "host_info": ("app.fastapi_routes.lan_routes", "host_info"),
    "import_mod_backend_py": ("app.infrastructure.mods.mod_manager", "import_mod_backend_py"),
    "issue_enterprise_credentials": (
        "app.services.user_cs_enterprise_credentials",
        "issue_enterprise_credentials",
    ),
    "issue_key_endpoint": ("app.fastapi_routes.lan_admin_routes", "issue_key_endpoint"),
    "kick_session_endpoint": ("app.fastapi_routes.lan_admin_routes", "kick_session_endpoint"),
    "list_access_requests_endpoint": (
        "app.fastapi_routes.lan_admin_routes",
        "list_access_requests_endpoint",
    ),
    "list_allowlist_endpoint": (
        "app.fastapi_routes.lan_admin_routes",
        "list_allowlist_endpoint",
    ),
    "list_audit_endpoint": ("app.fastapi_routes.lan_admin_routes", "list_audit_endpoint"),
    "list_change_requests": ("app.services.user_cs_change_request", "list_change_requests"),
    "list_field_schema": ("app.services.service_contract_fill", "list_field_schema"),
    "list_keys_endpoint": ("app.fastapi_routes.lan_admin_routes", "list_keys_endpoint"),
    "list_lan_facade_registry": ("app.legacy.lan.lan_compat", "list_lan_facade_registry"),
    "list_pipeline_client_summaries": (
        "app.services.user_cs_pipeline",
        "list_pipeline_client_summaries",
    ),
    "list_sessions_endpoint": (
        "app.fastapi_routes.lan_admin_routes",
        "list_sessions_endpoint",
    ),
    "load_field_overrides": ("app.services.service_contract_fill", "load_field_overrides"),
    "load_pipeline": ("app.services.user_cs_pipeline", "load_pipeline"),
    "logout": ("app.fastapi_routes.lan_routes", "logout"),
    "mark_change_request_ops_dispatched": (
        "app.services.user_cs_change_request",
        "mark_change_request_ops_dispatched",
    ),
    "mark_change_request_wechat_notified": (
        "app.services.user_cs_change_request",
        "mark_change_request_wechat_notified",
    ),
    "mark_demand_intake_sent": (
        "app.application.user_cs_demand_intake_bridge",
        "mark_demand_intake_sent",
    ),
    "maybe_send_connected_welcome": (
        "app.services.user_cs_connected_welcome",
        "maybe_send_connected_welcome",
    ),
    "maybe_send_intake_form_notice": (
        "app.services.user_cs_intake_notice",
        "maybe_send_intake_form_notice",
    ),
    "my_access_request": ("app.fastapi_routes.lan_routes", "my_access_request"),
    "normalize_demand_intake_result": (
        "app.application.user_cs_demand_intake_bridge",
        "normalize_demand_intake_result",
    ),
    "notify_software_delivery": (
        "app.services.user_cs_software_delivery",
        "notify_software_delivery",
    ),
    "orders_next_number_under_api": (
        "app.fastapi_routes.shipment_orders",
        "orders_next_number_under_api",
    ),
    "passive_poll_once": (
        "app.services.wechat_passive_group_monitor",
        "passive_poll_once",
    ),
    "probe_passive_llm_ready": (
        "app.services.wechat_passive_group_monitor",
        "probe_passive_llm_ready",
    ),
    "products_add": ("app.legacy.routes.product.compat_routes", "products_add"),
    "products_batch": ("app.fastapi_routes.domains.product.routes", "products_batch"),
    "products_batch_delete": (
        "app.legacy.routes.product.compat_routes",
        "products_batch_delete",
    ),
    "products_delete": (
        "app.legacy.routes.product.compat_routes",
        "products_delete",
    ),
    "products_get_by_id": (
        "app.legacy.routes.product.compat_routes",
        "products_get_by_id",
    ),
    "products_product_names": (
        "app.fastapi_routes.domains.product.routes",
        "products_product_names",
    ),
    "products_product_names_search": (
        "app.fastapi_routes.domains.product.routes",
        "products_product_names_search",
    ),
    "products_update": (
        "app.legacy.routes.product.compat_routes",
        "products_update",
    ),
    "publish_neuro_event": (
        "app.neuro_bus.application_neuro_bridge",
        "publish_neuro_event",
    ),
    "pull_external_crm_for_market_user": (
        "app.services.user_cs_crm_store",
        "pull_external_crm_for_market_user",
    ),
    "purchase_units_list": (
        "app.legacy.routes.product.compat_routes",
        "purchase_units_list",
    ),
    "push_external_crm_for_market_user": (
        "app.services.user_cs_crm_store",
        "push_external_crm_for_market_user",
    ),
    "query_trade": ("app.fastapi_routes.model_payment", "query_trade"),
    "redeem_submission_by_audit_code": (
        "app.services.user_cs_demand_form",
        "redeem_submission_by_audit_code",
    ),
    "refund_query": ("app.fastapi_routes.model_payment", "refund_query"),
    "refund_trade": ("app.fastapi_routes.model_payment", "refund_trade"),
    "reject_access_request_endpoint": (
        "app.fastapi_routes.lan_admin_routes",
        "reject_access_request_endpoint",
    ),
    "repair_all_pipelines": ("app.services.user_cs_pipeline", "repair_all_pipelines"),
    "repair_pipeline_crm": ("app.services.user_cs_pipeline", "repair_pipeline_crm"),
    "request_access": ("app.fastapi_routes.lan_routes", "request_access"),
    "require_admin": ("app.fastapi_routes.lan_admin_routes", "require_admin"),
    "reset_passive_watch": (
        "app.services.wechat_passive_group_monitor",
        "reset_passive_watch",
    ),
    "resolve_chat_model": ("app.infrastructure.llm.client", "resolve_chat_model"),
    "resolve_pdf_document_spec": (
        "app.application.office_plaintext_generate",
        "resolve_pdf_document_spec",
    ),
    "resolve_presentation_spec": (
        "app.application.office_plaintext_generate",
        "resolve_presentation_spec",
    ),
    "resolve_safe_excel_path": (
        "app.application.tools.workflow",
        "resolve_safe_excel_path",
    ),
    "resolve_table_spec": ("app.application.office_plaintext_generate", "resolve_table_spec"),
    "resolve_word_document_spec": (
        "app.application.office_plaintext_generate",
        "resolve_word_document_spec",
    ),
    "revoke_allowlist_endpoint": (
        "app.fastapi_routes.lan_admin_routes",
        "revoke_allowlist_endpoint",
    ),
    "revoke_key_endpoint": ("app.fastapi_routes.lan_admin_routes", "revoke_key_endpoint"),
    "run_bulk_import": ("app.application.excel_imports", "run_bulk_import"),
    "run_user_cs_employee": (
        "app.services.user_cs_employee_runner",
        "run_user_cs_employee",
    ),
    "save_field_overrides": ("app.services.service_contract_fill", "save_field_overrides"),
    "save_passive_poll_config": (
        "app.services.wechat_passive_group_monitor",
        "save_passive_poll_config",
    ),
    "save_pipeline": ("app.services.user_cs_pipeline", "save_pipeline"),
    "session_id_from_request": (
        "app.fastapi_routes.market_account",
        "session_id_from_request",
    ),
    "set_pipeline_stage": ("app.services.user_cs_pipeline", "set_pipeline_stage"),
    "setup_neuro_bus": ("app.neuro_bus.bus_setup", "setup_neuro_bus"),
    "shipment_download": ("app.fastapi_routes.shipment_orders", "shipment_download"),
    "shipment_records_units": (
        "app.legacy.routes.product.compat_routes",
        "shipment_records_units",
    ),
    "status": ("app.fastapi_routes.lan_routes", "status"),
    "store_document_pickup": ("app.services.kitten_ai_document.pickup", "store_document_pickup"),
    "svc": ("app.application.approval_workspace_app_service", ""),
    "sync_crm_from_pipeline_doc": (
        "app.services.user_cs_crm_store",
        "sync_crm_from_pipeline_doc",
    ),
    "sync_intake_from_market_if_newer": (
        "app.services.user_cs_demand_form",
        "sync_intake_from_market_if_newer",
    ),
    "teardown_neuro_bus": ("app.neuro_bus.bus_setup", "teardown_neuro_bus"),
    "try_confirm_payment_and_invoice": (
        "app.services.user_cs_delivery",
        "try_confirm_payment_and_invoice",
    ),
    "update_change_request_status": (
        "app.services.user_cs_change_request",
        "update_change_request_status",
    ),
    "update_delivery_plan": ("app.services.user_cs_delivery", "update_delivery_plan"),
    "update_settings_view": ("app.fastapi_routes.lan_settings_routes", "update_settings"),
    "update_settings": ("app.fastapi_routes.lan_settings_routes", "update_settings"),
    "verify_db_read_token_header": (
        "app.infrastructure.auth.db_token",
        "verify_db_read_token_header",
    ),
    "verify_webhook_secret": (
        "app.services.user_cs_demand_form",
        "verify_webhook_secret",
    ),
    "whoami": ("app.fastapi_routes.lan_admin_routes", "whoami"),
    "workspace_root": ("app.infrastructure.workspace", "workspace_root"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    module = import_module(module_name)
    value = getattr(module, attribute) if attribute else module
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
