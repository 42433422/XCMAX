"""Mod 初始化入口。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def mod_init(app, manifest: dict) -> None:
    """Mod 加载时调用。当前仅记录日志；未来可在此注册真实驱动或注入主代码发送入口。"""
    logger.info("xcagi-wechat-automation mod loaded: %s", manifest.get("id"))
