# -*- coding: utf-8 -*-
"""平台员工执行路径的 Persona 风格注入。

按 ai_workforce SSOT:小C助理 + 平台员工 共享 Persona 引擎;超级员工独立人格、不纳入。
- 小C/主对话流:已在 conversation 层应用 Persona。
- 平台员工:走 employee_runtime,在此按 user_id 取用户人格的「风格段」(四轴)附加到
  员工 system_prompt——员工保留自身岗位身份,只继承「对该用户怎么说话」。
- 超级员工:走 super_employee_service,不经此路径,天然排除。

全程 fail-safe:无 user_id / 无画像 / 处于异步事件循环 / 任何异常 → 返回空串,绝不打断执行。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def persona_style_for_user(user_id: int) -> str:
    """返回某用户的 Persona 风格段文本;不可用时返回空串(fail-safe)。"""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return ""
    if uid <= 0:
        return ""
    try:
        import asyncio

        from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl
        from app.services.persona.prompt_builder import persona_style_section

        repo = PersonaRepositoryImpl()
        try:
            profile = asyncio.run(repo.find_by_user_id(str(uid)))
        except RuntimeError:
            # 已有运行中的事件循环(异步上下文)→ 跳过同步读取,避免崩溃
            return ""
        if profile is None:
            return ""
        return persona_style_section(profile)
    except Exception as exc:  # noqa: BLE001 - 注入必须 fail-safe,绝不打断员工执行
        logger.debug("persona style inject skipped: %s", exc)
        return ""


__all__ = ["persona_style_for_user"]
