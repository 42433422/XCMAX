"""Schema versions and compatibility defaults for host profiles."""

PROFILE_SCHEMA_VERSION = 1
INDUSTRY_PRESETS_SCHEMA_VERSION = 1
WORKFLOW_CATALOG_SCHEMA_VERSION = 1

LEGACY_BRIDGE_MOD_HOST_APIS: dict[str, list[str]] = {
    "xcagi-approval-bridge": ["/api/mod/xcagi-approval-bridge/requests", "/api/approval"],
    "xcagi-lan-license-bridge": ["/api/mod/xcagi-lan-license-bridge/lan", "/api/lan"],
    "xcagi-model-payment-bridge": [
        "/api/mod/xcagi-model-payment-bridge/model-payment",
        "/api/model-payment",
    ],
    "xcagi-planner-bridge": [
        "/api/mod/xcagi-planner-bridge/chat",
        "/mod/xcagi-planner-bridge/ai-ecosystem",
        "/mod/xcagi-planner-bridge/brain",
        "/api/ai/chat",
        "/api/ai/intent",
    ],
    "xcagi-neuro-bus-bridge": [
        "/api/mod/xcagi-neuro-bus-bridge/neurobus",
        "/api/mod/xcagi-neuro-bus-bridge/handlers",
        "/api/neurobus",
        "/api/neuro",
    ],
    "xcagi-erp-domain-bridge": [
        "/api/mod/xcagi-erp-domain-bridge/products",
        "/api/mod/xcagi-erp-domain-bridge/customers",
        "/api/mod/xcagi-erp-domain-bridge/shipment",
    ],
    "xcagi-office-employee-pack-bridge": [
        "/api/mod/xcagi-office-employee-pack-bridge/catalog",
        "/api/mods/",
    ],
    "xcagi-customer-service-bridge": [
        "/api/mod/xcagi-customer-service-bridge/status",
        "/mod/xcagi-customer-service-bridge/enterprise-customer-service",
        "/mod/xcagi-customer-service-bridge/internal-customer-service",
    ],
}

LEGACY_MINIMAL_HOST_MOD_IDS: tuple[str, ...] = (
    "xcagi-planner-bridge",
    "xcagi-neuro-bus-bridge",
    "xcagi-office-employee-pack-bridge",
)
LEGACY_GENERIC_HOST_MOD_IDS: tuple[str, ...] = (
    "xcagi-planner-bridge",
    "xcagi-erp-domain-bridge",
    "xcagi-workflow-visualization-bridge",
    "xcagi-approval-bridge",
    "xcagi-lan-license-bridge",
    "xcagi-model-payment-bridge",
    "xcagi-neuro-bus-bridge",
    "xcagi-office-employee-pack-bridge",
    "xcagi-customer-service-bridge",
)
LEGACY_PROTECTED: tuple[str, ...] = (
    "attendance-industry",
    "coating-industry",
    "taiyangniao-pro",
    "sz-qsm-pro",
)
LEGACY_CORE_WORKFLOW = "xcagi-workflow-visualization-bridge"
LEGACY_PLATFORM_PREFIXES: list[str] = [
    "/api/print",
    "/api/shipment",
    "/api/mods",
    "/api/mod-store",
    "/api/wechat",
    "/api/products",
    "/api/customers",
    "/api/orders",
    "/api/inventory",
    "/api/ocr",
    "/api/auth",
    "/api/system",
]
LEGACY_SKU_BUNDLED: dict[str, tuple[str, ...]] = {
    "personal": LEGACY_MINIMAL_HOST_MOD_IDS,
    "enterprise": LEGACY_GENERIC_HOST_MOD_IDS
    + ("xcagi-planner-excel-tools",),
}
LEGACY_STAGE: dict[str, tuple[str, ...]] = {
    "personal": LEGACY_MINIMAL_HOST_MOD_IDS,
    "enterprise": (
        "xcagi-planner-bridge",
        "xcagi-erp-domain-bridge",
        "xcagi-workflow-visualization-bridge",
        "xcagi-core-workflow-employees",
        "xcagi-approval-bridge",
        "xcagi-lan-license-bridge",
        "xcagi-model-payment-bridge",
        "xcagi-neuro-bus-bridge",
        "xcagi-office-employee-pack-bridge",
        "xcagi-customer-service-bridge",
        "xcagi-planner-excel-tools",
    ),
}
