"""人员 / 产品 / 客户侧 SQLite（原 taiyangniao-pro 私有库）统一路径。

多个 Mod 可挂载同一套 HTTP 路由；文件仍默认 ``taiyangniao_pro.db``，与历史数据兼容。
"""

from __future__ import annotations

import os
from pathlib import Path

from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path


def get_personnel_database_path() -> Path:
    name = (
        os.environ.get("XCAGI_PERSONNEL_DB_FILENAME") or "taiyangniao_pro.db"
    ).strip() or "taiyangniao_pro.db"
    return resolve_mod_private_sqlite_path(name)


__all__ = ["get_personnel_database_path"]
