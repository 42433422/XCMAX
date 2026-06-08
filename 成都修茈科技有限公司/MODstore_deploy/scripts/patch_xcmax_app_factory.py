#!/usr/bin/env python3
"""Idempotent patch: add xcmax OpenAPI tag + optional router to app_factory.py."""
from __future__ import annotations

from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "modstore_server" / "api" / "app_factory.py"

OLD_TAGS = """    {"name": "catalog-mod-sync", "description": "公网机器令牌：库与 XCAGI/mods 推送/拉回（/v1/mod-sync）"},
]"""

NEW_TAGS = """    {"name": "catalog-mod-sync", "description": "公网机器令牌：库与 XCAGI/mods 推送/拉回（/v1/mod-sync）"},
    {
        "name": "xcmax-admin",
        "description": "XCmax 服务器后台与双向同步（/api/xcmax/admin、/api/xcmax/sync）",
    },
]"""

OLD_OPT = """        "modstore_server.subscription_renewer",
    )"""

NEW_OPT = """        "modstore_server.subscription_renewer",
        # XCmax 服务器后台 / 双向同步（与本地节点 app/fastapi_routes/xcmax_admin.py 对称）
        "modstore_server.xcmax_admin_api",
    )"""


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "modstore_server.xcmax_admin_api" in text and "xcmax-admin" in text:
        print("already patched")
        return
    if OLD_TAGS not in text:
        raise SystemExit(f"openapi anchor not found in {TARGET}")
    if OLD_OPT not in text:
        raise SystemExit(f"optional anchor not found in {TARGET}")
    text = text.replace(OLD_TAGS, NEW_TAGS, 1).replace(OLD_OPT, NEW_OPT, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("patched ok")


if __name__ == "__main__":
    main()
