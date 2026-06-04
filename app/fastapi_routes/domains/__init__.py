"""
domains/ — 按业务域组织的路由包（替代散落的 legacy_/xcagi_compat_）

14+ 业务域目录已在 ``domains/<domain>/`` 落点；运行时路由仍由 legacy_/xcagi_compat_* 承载，迁移见 ``domain_registry.py``。
"""

from __future__ import annotations

from app.fastapi_routes.domains import auth as auth

__all__ = [
    "auth",
]
