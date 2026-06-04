#!/usr/bin/env python3
"""v10: 将 legacy_/xcagi_compat_* 路由体迁入 domains/，源文件保留 router 重导出 shim。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "app" / "fastapi_routes"

# filename -> dot module under app.fastapi_routes
TARGETS: dict[str, str] = {
    "legacy_static.py": "domains.static.routes",
    "legacy_excel.py": "domains.excel.routes",
    "legacy_products.py": "domains.product.routes",
    "legacy_wechat.py": "domains.wechat.routes",
    "legacy_conversation.py": "domains.conversation.routes",
    "legacy_system.py": "domains.system.routes",
    "legacy_auth.py": "domains.auth.routes",
    "legacy_workflow.py": "domains.shipment.routes",
    "legacy_helpers.py": "domains.misc.helpers",
    "legacy_inventory.py": "domains.inventory.routes",
    "xcagi_compat.py": "domains.workflow.routes",
    "xcagi_compat_chat.py": "domains.conversation.routes",
    "xcagi_compat_chat_helpers.py": "domains.conversation.helpers",
    "xcagi_compat_conversation.py": "domains.conversation.routes",
    "xcagi_compat_customer.py": "domains.customer.routes",
    "xcagi_compat_misc.py": "domains.misc.routes",
    "xcagi_compat_product.py": "domains.product.routes",
    "xcagi_compat_template.py": "domains.template.routes",
    "xcagi_compat_wechat.py": "domains.wechat.routes",
    "xcagi_compat_db_base.py": "domains.db.base",
    "xcagi_compat_db_queries.py": "domains.db.queries",
    "xcagi_compat_db_writes.py": "domains.db.writes",
    "xcagi_compat_db_product_queries.py": "domains.db.product_queries",
}


def _module_to_path(mod: str) -> Path:
    return ROUTES / Path(*mod.split(".")).with_suffix(".py")


def _is_placeholder(path: Path) -> bool:
    if not path.is_file():
        return True
    text = path.read_text(encoding="utf-8")
    if "当前为占位" in text:
        return True
    if "APIRouter" not in text and len(text.splitlines()) < 25:
        return True
    return False


def migrate(filename: str, target_mod: str) -> None:
    src = ROUTES / filename
    if not src.is_file():
        print(f"skip missing {filename}")
        return
    body = src.read_text(encoding="utf-8")
    if "router = APIRouter" not in body and filename not in ("legacy_helpers.py", "legacy_inventory.py"):
        print(f"skip no router {filename}")
        return
    dst = _module_to_path(target_mod)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _is_placeholder(dst):
        header = f'"""Migrated from {filename} (v10)."""\n'
        if not body.lstrip().startswith('"""'):
            body = header + body
        dst.write_text(body, encoding="utf-8")
        print(f"moved body -> {dst.relative_to(ROOT)}")
    else:
        print(f"keep existing {dst.relative_to(ROOT)}")
    shim = (
        f'"""v10 shim — implementation in ``{target_mod}``."""\n'
        f"from app.fastapi_routes.{target_mod} import router  # noqa: F401\n\n"
        f'__all__ = ["router"]\n'
    )
    if target_mod.endswith(".helpers"):
        shim = (
            f'"""v10 shim — implementation in ``{target_mod}``."""\n'
            f"from app.fastapi_routes.{target_mod} import *  # noqa: F403\n"
        )
    src.write_text(shim, encoding="utf-8")
    print(f"shim {filename}")


def main() -> int:
    for fn, mod in TARGETS.items():
        migrate(fn, mod)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
