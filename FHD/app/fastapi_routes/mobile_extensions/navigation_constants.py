"""Static registry data extracted from the public facade."""

from __future__ import annotations

_CORE_NAV_ITEMS: list[dict[str, str]] = [
    {"key": "chat", "name": "智能对话", "icon": "fa-comments-o", "path": "/chat"},
    {"key": "im", "name": "信息", "icon": "fa-envelope-o", "path": "/im"},
    {"key": "ai-ecosystem", "name": "智能生态", "icon": "fa-sitemap", "path": "/ai-ecosystem"},
    {
        "key": "employee-workflow",
        "name": "员工工作台",
        "icon": "fa-users",
        "path": "/employee-workflow",
    },
    {"key": "products", "name": "业务对象", "icon": "fa-cubes", "path": "/products"},
    {"key": "customers", "name": "组织管理", "icon": "fa-users", "path": "/customers"},
    {"key": "orders", "name": "业务单据", "icon": "fa-file-text-o", "path": "/orders"},
    {
        "key": "shipment-records",
        "name": "业务记录",
        "icon": "fa-industry",
        "path": "/shipment-records",
    },
    {"key": "materials", "name": "资源库", "icon": "fa-archive", "path": "/materials"},
    {"key": "data-sources", "name": "数据来源", "icon": "fa-database", "path": "/data-sources"},
    {"key": "print", "name": "模板与打印", "icon": "fa-print", "path": "/print"},
    {"key": "settings", "name": "系统设置", "icon": "fa-cog", "path": "/settings"},
]

_ADMIN_NAV_ITEM = {
    "key": "admin-entitlements",
    "name": "用户管理",
    "icon": "fa-shield",
    "path": "/admin-entitlements",
}

_ROLE_VISIBLE_KEYS: dict[str, set[str] | None] = {
    "admin": None,
    "enterprise": {
        "chat",
        "im",
        "ai-ecosystem",
        "employee-workflow",
        "products",
        "customers",
        "orders",
        "shipment-records",
        "materials",
        "data-sources",
        "print",
        "settings",
    },
    "personal": {"chat", "im", "ai-ecosystem", "settings"},
}
