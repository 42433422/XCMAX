# mypy: disable-error-code="arg-type, attr-defined, no-any-return, union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


async def _execute_employee_for_qq(employee_id: str, user_text: str) -> str:
    """把一条 QQ 用户文本喂给完整 employee 执行器，并抽出可发送的回复。

    QQ 群消息上限较小，这里截断到 ``_QQ_REPLY_MAX_LEN``。执行器自身处理
    risk gate / 计费 / metrics，与 web/工作台一致——QQ 只是一个新的输入渠道。
    """
    from modstore_server.services.employee import get_default_employee_client

    client = get_default_employee_client()
    bridge_uid = _facade()._bridge_user_id()

    def _run() -> _facade().Dict[str, _facade().Any]:
        return client.execute_task(
            employee_id=employee_id,
            task=user_text,
            input_data={"text": user_text, "channel": "qq"},
            user_id=int(bridge_uid),
        )

    loop = _facade().asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _run)
    if not isinstance(raw, dict):
        return ""
    text = ""
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    for out in outputs:
        if not isinstance(out, dict):
            continue
        if out.get("handler") in ("echo", "llm_md"):
            cand = str(out.get("output") or "").strip()
            if cand:
                text = cand
                break
    if not text:
        excerpt = str(raw.get("reasoning_excerpt") or "").strip()
        if excerpt:
            text = excerpt
    if not text:
        cog_help = str(raw.get("cognition_help") or "").strip()
        if cog_help:
            text = cog_help
    if not text:
        summary = str(result.get("summary") or "").strip()
        if summary and summary != f"executed {len(outputs)} handlers":
            text = summary
    if len(text) > _facade()._QQ_REPLY_MAX_LEN:
        text = text[: _facade()._QQ_REPLY_MAX_LEN - 1] + "…"
    return text
