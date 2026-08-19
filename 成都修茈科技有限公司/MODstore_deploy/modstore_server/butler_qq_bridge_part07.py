# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


def _strip_at(text: str) -> str:
    """去掉 ``<@!12345>`` / ``@机器人`` 这种前导 mention。"""
    s = (text or "").strip()
    while s.startswith("<@") and ">" in s:
        s = s.split(">", 1)[1].lstrip()
    return s


def _extract_target_id(kind: _facade().MsgKind, payload: _facade().Dict[str, _facade().Any]) -> str:
    """根据事件类型从 payload 取回复目标。"""
    if kind == "group":
        return str(payload.get("group_openid") or "")
    if kind == "c2c":
        author = payload.get("author") or {}
        return str(author.get("user_openid") or author.get("id") or "")
    return str(payload.get("channel_id") or "")


async def dispatch_to_butler(event_type: str, payload: _facade().Dict[str, _facade().Any]) -> None:
    """兼容旧调用入口（数字管家默认上下文）。"""
    await _facade().dispatch_to_employee(event_type, payload, app_id=_facade()._qq_app_id())


async def dispatch_to_employee(
    event_type: str,
    payload: _facade().Dict[str, _facade().Any],
    *,
    app_id: str,
    employee_id_hint: str = "",
) -> None:
    """把一条 QQ 消息路由到对应 AI 员工，跑完整执行器并把回复送回 QQ。

    路由顺序：

    1) ``employee_id_hint`` 非空（按 employee_id 的通用 webhook 进来时）→ 直接定位；
    2) 否则按 ``app_id`` 在账号池里找；
    3) 都失败再降级到管家。

    回复来源（按可用性回退）：

    - 数字管家：仍走 ``_employee_chat``（轻量 LLM persona）保持原行为；
    - 其它员工：先跑 ``execute_employee_task`` 全链路（perception/cognition/actions），
      抽 ``reasoning_excerpt`` 或 ``echo`` 输出当作 QQ 回复；执行器异常或抽不出文本，
      再回退到 ``_employee_chat`` 保命，避免静默吞消息。
    """
    kind = _facade()._KIND_BY_EVENT.get(event_type)
    if not kind:
        _facade().logger.info("跳过未支持的 QQ 事件类型: %s", event_type)
        return
    text = _facade()._strip_at(str(payload.get("content") or ""))
    if not text:
        return
    target_id = _facade()._extract_target_id(kind, payload)
    if not target_id:
        _facade().logger.warning("QQ 事件缺少目标 id: %s payload=%s", event_type, payload)
        return
    msg_id = str(payload.get("id") or "")
    ctx: _facade().Optional[_facade()._BotContext] = None
    if employee_id_hint:
        ctx = await _facade()._get_bot_ctx_by_employee(employee_id_hint)
    if ctx is None and app_id:
        ctx = await _facade()._get_bot_ctx(app_id)
    if ctx is None:
        _facade().logger.warning(
            "找不到 employee/app_id=%s/%s 对应员工，降级到数字管家",
            employee_id_hint or "-",
            app_id or "-",
        )
        ctx = _facade()._BotContext(
            employee_id=_facade()._BUTLER_EMPLOYEE_ID,
            app_id=_facade()._qq_app_id(),
            app_secret=_facade()._qq_app_secret(),
            sandbox=_facade()._qq_sandbox(),
            bot_token=_facade()._qq_bot_token(),
        )
    reply = await _facade()._resolve_reply(ctx.employee_id, text)
    if not reply:
        reply = "（AI 员工未生成回复）"
    try:
        await ctx.send(kind, target_id, reply, msg_id=msg_id)
    except Exception:
        _facade().logger.exception(
            "QQ 出站失败 kind=%s target=%s employee=%s", kind, target_id, ctx.employee_id
        )


async def _resolve_reply(employee_id: str, user_text: str) -> str:
    """统一选择"用执行器"还是"用 persona LLM"产生回复文本。"""
    if employee_id == _facade()._BUTLER_EMPLOYEE_ID:
        try:
            return await _facade()._employee_chat(user_text, employee_id=employee_id)
        except Exception as exc:
            _facade().logger.exception("管家 chat 失败")
            return f"数字管家暂时不可用：{exc}"
    try:
        reply = await _facade()._execute_employee_for_qq(employee_id, user_text)
        if reply:
            return reply
        _facade().logger.info("执行器无文本输出 employee=%s，回退到 persona chat", employee_id)
    except Exception as exc:
        _facade().logger.exception(
            "执行器失败 employee=%s，回退到 persona chat: %s", employee_id, exc
        )
    try:
        return await _facade()._employee_chat(user_text, employee_id=employee_id)
    except Exception as exc:
        _facade().logger.exception("persona chat 也失败 employee=%s", employee_id)
        return f"AI 员工暂时不可用：{exc}"
