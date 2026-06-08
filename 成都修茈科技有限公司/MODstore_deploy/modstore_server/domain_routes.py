"""Domain-based route registry for modstore_server.

Groups the 46 ``*_api.py`` modules by NeuroDomain as defined in
``docs/ARCHITECTURE.md`` §4.  Each domain exposes its API routers so that
``app_factory`` can mount them in a single, well-organized block instead of
importing 40+ individual modules.

Physical files remain in ``modstore_server/`` for backward compatibility;
this module only provides a logical grouping layer.
"""

from __future__ import annotations

from fastapi import FastAPI

_DOMAIN_REGISTRY: dict[str, list[str]] = {
    "catalog": [
        "modstore_server.api.catalog_public_routes",
        "modstore_server.api.market_routes",
        "modstore_server.market_auth_api",
        "modstore_server.market_catalog_api",
        "modstore_server.mod_sync_catalog_api",
    ],
    "employee": [
        "modstore_server.employee_api",
        "modstore_server.employee_status_api",
        "modstore_server.employee_change_request_api",
        "modstore_server.ai_employee_account_api",
        "modstore_server.admin_employee_autonomy_api",
        "modstore_server.admin_employee_execution_api",
    ],
    "workflow": [
        "modstore_server.workflow_api",
        "modstore_server.workbench_api",
        "modstore_server.workbench_studio_assets_api",
        "modstore_server.script_workflow_api",
        "modstore_server.on_demand_orchestrate_api",
    ],
    "payment": [
        "modstore_server.api.payment_routes",
        "modstore_server.invoice_api",
        "modstore_server.refund_api",
    ],
    "llm": [
        "modstore_server.llm_api",
        "modstore_server.openai_llm_gateway_api",
    ],
    "knowledge": [
        "modstore_server.knowledge_v2_api",
        "modstore_server.knowledge_vector_api",
    ],
    "notification": [
        "modstore_server.notification_api",
        "modstore_server.email_admin_api",
    ],
    "safety": [
        "modstore_server.sandbox_api",
        "modstore_server.runtime_allowlist_api",
    ],
    "webhook": [
        "modstore_server.webhook_api",
        "modstore_server.webhook_subscription_api",
        "modstore_server.inbound_webhook_api",
    ],
    "ops": [
        "modstore_server.ops_api",
        "modstore_server.admin_ops_audit_api",
        "modstore_server.admin_duty_graph_api",
        "modstore_server.yuangon_onboard_admin_api",
        "modstore_server.analytics_api",
    ],
    "health": [
        "modstore_server.health_api",
        "modstore_server.health_check_api",
        "modstore_server.payment_health_api",
    ],
    "auth": [
        "modstore_server.account_api",
        "modstore_server.developer_api",
        "modstore_server.developer_key_export_api",
    ],
    "authoring": [
        "modstore_server.eskill_api",
        "modstore_server.templates_api",
        "modstore_server.openapi_connector_api",
    ],
    "butler": [
        "modstore_server.agent_butler_api",
        "modstore_server.customer_service_api",
    ],
    "xcmax": [
        "modstore_server.xcmax_admin_api",
    ],
}


def get_domain_registry() -> dict[str, list[str]]:
    return dict(_DOMAIN_REGISTRY)


def mount_domain_routes(app: FastAPI) -> None:
    """Import each domain's API module and mount its ``router`` (if any).

    This is a convenience helper; ``app_factory`` may continue to import
    modules directly for finer-grained control over ordering.
    """
    import importlib
    import logging

    logger = logging.getLogger(__name__)

    for domain, modules in _DOMAIN_REGISTRY.items():
        for module_path in modules:
            try:
                mod = importlib.import_module(module_path)
                router = getattr(mod, "router", None)
                if router is not None:
                    app.include_router(router)
                    logger.debug("Mounted %s router from %s", domain, module_path)
            except Exception as exc:
                logger.warning("Failed to mount %s (%s): %s", domain, module_path, exc)
