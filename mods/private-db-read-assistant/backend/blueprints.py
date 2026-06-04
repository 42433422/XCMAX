"""私人数据库读取助手 Mod — API 由宿主 compat 层提供，本 Mod 负责登记与发现。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_fastapi_routes(app, mod_id: str) -> None:
    """路由已在宿主 ``private_db_read_assistant_compat`` 注册，避免重复挂载。"""
    _ = (app, mod_id)


def mod_init() -> None:
    logger.info("private-db-read-assistant initialized (host compat routes)")
