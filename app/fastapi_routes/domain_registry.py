"""
domain_registry.py — legacy_/xcagi_compat_ 路由的 14+ 业务域映射

这是 P0 ③ 架构债清理的「第一步」：
- 不立即重写每个 legacy_*.py（保持向后兼容）
- 提供一个 SSOT 映射表，标记每个文件的目标业务域
- CI 校验：新增 legacy 路由必须登记入域
- 后续按域迁移时，按本表顺序逐步拆

业务域（14+）：
  1.  auth            认证/授权
  2.  conversation    对话/聊天（含 AI chat）
  3.  customer        客户/CRM
  4.  excel           Excel 解析/导出
  5.  inventory       库存
  6.  misc            杂项（兜底域）
  7.  product         产品/商品
  8.  shipment        发货/物流
  9.  static          静态资源
  10. system          系统/管理
  11. template        模板
  12. wechat          微信域
  13. workflow        工作流/审批
  14. db              数据库查询/写入
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 14+ 业务域枚举（顺序敏感，CI 中会校验完整性）
BUSINESS_DOMAINS: tuple[str, ...] = (
    "auth",
    "conversation",
    "customer",
    "excel",
    "inventory",
    "misc",
    "product",
    "shipment",
    "static",
    "system",
    "template",
    "wechat",
    "workflow",
    "db",
)

DOMAIN_TO_DIR: dict[str, str] = {
    "auth": "app/fastapi_routes/domains/auth/",
    "conversation": "app/fastapi_routes/domains/conversation/",
    "customer": "app/fastapi_routes/domains/customer/",
    "excel": "app/fastapi_routes/domains/excel/",
    "inventory": "app/fastapi_routes/domains/inventory/",
    "misc": "app/fastapi_routes/domains/misc/",
    "product": "app/fastapi_routes/domains/product/",
    "shipment": "app/fastapi_routes/domains/shipment/",
    "static": "app/fastapi_routes/domains/static/",
    "system": "app/fastapi_routes/domains/system/",
    "template": "app/fastapi_routes/domains/template/",
    "wechat": "app/fastapi_routes/domains/wechat/",
    "workflow": "app/fastapi_routes/domains/workflow/",
    "db": "app/fastapi_routes/domains/db/",
}


@dataclass(frozen=True)
class LegacyRoute:
    """单条 legacy_/compat_ 路由文件 → 目标域映射"""
    filename: str  # 例 "legacy_auth.py"
    target_domain: str  # 例 "auth"
    target_module: str  # 例 "app.fastapi_routes.domains.auth.routes"
    route_count: int = 0  # 该文件中定义的 router 端点数（用于迁移优先级排序）
    note: str = ""  # 备注（如 "v10.0 计划" / "stub"）


# 完整映射（按域分组，便于审阅）
LEGACY_ROUTE_REGISTRY: tuple[LegacyRoute, ...] = (
    # === auth（认证）===
    LegacyRoute(
        filename="legacy_auth.py",
        target_domain="auth",
        target_module="app.fastapi_routes.domains.auth.routes",
        route_count=0,  # 启动时自动统计
        note="FastAPI Depends 迁移已完成；本文件保留兼容入口",
    ),
    # === conversation（对话）===
    LegacyRoute(
        filename="legacy_conversation.py",
        target_domain="conversation",
        target_module="app.fastapi_routes.domains.conversation.routes",
        route_count=0,
        note="对话上下文与历史记录",
    ),
    LegacyRoute(
        filename="xcagi_compat_chat.py",
        target_domain="conversation",
        target_module="app.fastapi_routes.domains.conversation.routes",
        route_count=0,
    ),
    LegacyRoute(
        filename="xcagi_compat_chat_helpers.py",
        target_domain="conversation",
        target_module="app.fastapi_routes.domains.conversation.helpers",
        route_count=0,
        note="helpers 子模块（按 v10.0 计划独立成包）",
    ),
    LegacyRoute(
        filename="xcagi_compat_conversation.py",
        target_domain="conversation",
        target_module="app.fastapi_routes.domains.conversation.routes",
        route_count=0,
    ),
    # === customer（客户）===
    LegacyRoute(
        filename="xcagi_compat_customer.py",
        target_domain="customer",
        target_module="app.fastapi_routes.domains.customer.routes",
        route_count=0,
    ),
    # === excel ===
    LegacyRoute(
        filename="legacy_excel.py",
        target_domain="excel",
        target_module="app.fastapi_routes.domains.excel.routes",
        route_count=0,
    ),
    # === inventory ===
    LegacyRoute(
        filename="legacy_inventory.py",
        target_domain="inventory",
        target_module="app.fastapi_routes.domains.inventory.routes",
        route_count=0,
    ),
    # === misc ===
    LegacyRoute(
        filename="legacy_helpers.py",
        target_domain="misc",
        target_module="app.fastapi_routes.domains.misc.helpers",
        route_count=0,
        note="通用 helpers（跨域依赖，不属于任何业务域）",
    ),
    LegacyRoute(
        filename="xcagi_compat_misc.py",
        target_domain="misc",
        target_module="app.fastapi_routes.domains.misc.routes",
        route_count=0,
    ),
    # === product（产品）===
    LegacyRoute(
        filename="legacy_products.py",
        target_domain="product",
        target_module="app.fastapi_routes.domains.product.routes",
        route_count=0,
    ),
    LegacyRoute(
        filename="xcagi_compat_product.py",
        target_domain="product",
        target_module="app.fastapi_routes.domains.product.routes",
        route_count=0,
    ),
    # === shipment ===
    LegacyRoute(
        filename="legacy_workflow.py",
        target_domain="shipment",
        target_module="app.fastapi_routes.domains.shipment.routes",
        route_count=0,
        note="与 shipment_workflow 强耦合，归入 shipment 域",
    ),
    # === static ===
    LegacyRoute(
        filename="legacy_static.py",
        target_domain="static",
        target_module="app.fastapi_routes.domains.static.routes",
        route_count=0,
        note="静态资源 / 静态页面",
    ),
    # === system ===
    LegacyRoute(
        filename="legacy_system.py",
        target_domain="system",
        target_module="app.fastapi_routes.domains.system.routes",
        route_count=0,
    ),
    LegacyRoute(
        filename="legacy_host_routers.py",
        target_domain="system",
        target_module="app.fastapi_routes.domains.system.host_routers",
        route_count=0,
    ),
    # === template ===
    LegacyRoute(
        filename="xcagi_compat_template.py",
        target_domain="template",
        target_module="app.fastapi_routes.domains.template.routes",
        route_count=0,
    ),
    # === wechat（微信）===
    LegacyRoute(
        filename="legacy_wechat.py",
        target_domain="wechat",
        target_module="app.fastapi_routes.domains.wechat.routes",
        route_count=0,
    ),
    LegacyRoute(
        filename="xcagi_compat_wechat.py",
        target_domain="wechat",
        target_module="app.fastapi_routes.domains.wechat.routes",
        route_count=0,
    ),
    # === workflow（工作流/审批）===
    LegacyRoute(
        filename="xcagi_compat.py",
        target_domain="misc",
        target_module="app.fastapi_routes.xcagi_compat",
        route_count=0,
        note="v10.0.2: compat 聚合入口；domains.workflow.routes 为 registry 兼容 re-export",
    ),
    # === db（数据库查询/写入）===
    LegacyRoute(
        filename="xcagi_compat_db_base.py",
        target_domain="db",
        target_module="app.fastapi_routes.domains.db.base",
        route_count=0,
    ),
    LegacyRoute(
        filename="xcagi_compat_db_queries.py",
        target_domain="db",
        target_module="app.fastapi_routes.domains.db.queries",
        route_count=0,
    ),
    LegacyRoute(
        filename="xcagi_compat_db_writes.py",
        target_domain="db",
        target_module="app.fastapi_routes.domains.db.writes",
        route_count=0,
    ),
    LegacyRoute(
        filename="xcagi_compat_db_product_queries.py",
        target_domain="db",
        target_module="app.fastapi_routes.domains.db.product_queries",
        route_count=0,
    ),
)


def get_routes_by_domain(domain: str) -> list[LegacyRoute]:
    """获取指定业务域下的所有 legacy 路由"""
    return [r for r in LEGACY_ROUTE_REGISTRY if r.target_domain == domain]


def get_pending_domains() -> list[str]:
    """返回尚未迁移到 domains/ 目录的域（target_module 路径不存在的）"""
    project_root = Path(__file__).resolve().parent.parent.parent
    pending = []
    for domain in BUSINESS_DOMAINS:
        target_dir = project_root / DOMAIN_TO_DIR[domain].replace("app/", "app/")
        if not target_dir.exists():
            pending.append(domain)
    return pending


def verify_registry_integrity() -> list[str]:
    """校验注册表完整性，返回错误列表（空 = 全部通过）"""
    errors: list[str] = []

    # 1. 业务域枚举不能为空
    if not BUSINESS_DOMAINS:
        errors.append("BUSINESS_DOMAINS 为空")

    # 2. 每个域必须有目录映射
    for d in BUSINESS_DOMAINS:
        if d not in DOMAIN_TO_DIR:
            errors.append(f"业务域 {d} 缺少 DOMAIN_TO_DIR 映射")

    # 3. 每个 legacy 文件必须登记
    project_root = Path(__file__).resolve().parent.parent.parent
    legacy_dir = project_root / "app" / "fastapi_routes"
    actual_legacy_files: set[str] = set()
    for p in legacy_dir.iterdir():
        if p.name.startswith("__") or p.suffix != ".py":
            continue
        if p.name.startswith("legacy_") or p.name.startswith("xcagi_compat"):
            actual_legacy_files.add(p.name)
    registered = {r.filename for r in LEGACY_ROUTE_REGISTRY}
    missing = actual_legacy_files - registered
    if missing:
        errors.append(f"未登记的 legacy_/compat_ 文件: {sorted(missing)}")
    # v10.0.3：shim 已删，注册表保留历史 filename → domains 映射，不再要求磁盘文件存在。

    # 4. 每个 target_domain 必须在 BUSINESS_DOMAINS 中
    for r in LEGACY_ROUTE_REGISTRY:
        if r.target_domain not in BUSINESS_DOMAINS:
            errors.append(
                f"{r.filename} → 未知业务域: {r.target_domain}"
            )

    return errors


if __name__ == "__main__":  # pragma: no cover
    # CLI: 打印迁移状态
    errs = verify_registry_integrity()
    if errs:
        print("❌ 域注册表错误：")
        for e in errs:
            print(f"  - {e}")
        raise SystemExit(1)

    pending = get_pending_domains()
    print(f"✅ 域注册表完整 · 14+ 业务域 · {len(LEGACY_ROUTE_REGISTRY)} 个 legacy 文件")
    print(f"📋 待迁移业务域（{len(pending)}/{len(BUSINESS_DOMAINS)}）:")
    for d in pending:
        files = get_routes_by_domain(d)
        print(f"  - {d:14}  ({len(files)} 个文件)")
