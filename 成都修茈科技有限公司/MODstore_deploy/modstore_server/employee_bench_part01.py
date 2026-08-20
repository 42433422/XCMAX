# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_bench")


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = _facade().re.sub("^```(?:json)?\\s*", "", s, flags=_facade().re.I | _facade().re.S)
        s = _facade().re.sub("\\s*```\\s*$", "", s)
    return s.strip()


def _parse_task_list(
    content: str,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    raw = _facade()._strip_fence(content)
    try:
        data = _facade().json.loads(raw)
    except _facade().json.JSONDecodeError:
        i, j = (raw.find("["), raw.rfind("]"))
        if i < 0 or j <= i:
            return []
        try:
            data = _facade().json.loads(raw[i : j + 1])
        except _facade().json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        lv = int(item.get("level") or 0)
        if lv < 1 or lv > 5:
            continue
        tasks = [
            {
                "id": str(t.get("id") or f"{lv}-{i + 1}"),
                "task_desc": str(t.get("task_desc") or "").strip()[:120],
            }
            for (i, t) in enumerate((item.get("tasks") or [])[:3])
            if isinstance(t, dict) and str(t.get("task_desc") or "").strip()
        ]
        if tasks:
            out.append({"level": lv, "tasks": tasks})
    return out


def _fallback_tasks(brief: str) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """LLM 失败时生成最小占位任务集。"""
    short = (brief or "执行默认任务")[:40]
    return [
        {
            "level": lv,
            "tasks": [
                {"id": f"{lv}-{t}", "task_desc": f"[Lv{lv}] {short}（测试 {t}）"}
                for t in range(1, 4)
            ],
        }
        for lv in range(1, 6)
    ]


async def generate_bench_tasks(
    brief: str,
    panel_summary: str,
    *,
    db: _facade().Session,
    user_id: int,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    use_platform_dispatch: bool = False,
    strict: bool = False,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """调 LLM 一次生成 1-5 级共 15 条测试任务。

    use_platform_dispatch=True 时使用平台密钥（不读用户 BYOK）。
    strict=True 时 LLM 失败会抛出 RuntimeError，而不是静默退回到占位任务。
    """
    from modstore_server.services.llm import (
        chat_dispatch_via_platform_only,
        chat_dispatch_via_session,
    )

    if not provider or not model:
        msg = "generate_bench_tasks: 无 provider/model，无法生成测试任务"
        if strict:
            raise RuntimeError(msg)
        _facade().logger.warning("%s，使用占位任务", msg)
        return _facade()._fallback_tasks(brief)
    user_msg = f"员工功能描述（brief）：\n{(brief or '').strip()}\n\n功能摘要（panel_summary）：\n{(panel_summary or '（无）').strip()}"
    messages = [
        {"role": "system", "content": _facade()._TASK_GEN_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    try:
        _mt = 6000 if use_platform_dispatch else 2000
        if use_platform_dispatch:
            result = await chat_dispatch_via_platform_only(
                provider, model, messages, max_tokens=_mt
            )
        else:
            result = await chat_dispatch_via_session(
                db, user_id, provider, model, messages, max_tokens=_mt
            )
    except RECOVERABLE_ERRORS as exc:
        msg = f"generate_bench_tasks LLM call failed: {exc}"
        if strict:
            raise RuntimeError(msg) from exc
        _facade().logger.warning(msg)
        return _facade()._fallback_tasks(brief)
    if not result.get("ok"):
        msg = f"generate_bench_tasks LLM error: {result.get('error')}"
        if strict:
            raise RuntimeError(msg)
        _facade().logger.warning(msg)
        return _facade()._fallback_tasks(brief)
    tasks = _facade()._parse_task_list(str(result.get("content") or ""))
    if not tasks:
        msg = "generate_bench_tasks: LLM 响应解析失败，未获得有效任务列表"
        if strict:
            raise RuntimeError(msg)
        _facade().logger.warning("%s，使用占位任务", msg)
        return _facade()._fallback_tasks(brief)
    seen = {t["level"] for t in tasks}
    for lv in range(1, 6):
        if lv not in seen:
            tasks.append(
                {
                    "level": lv,
                    "tasks": [{"id": f"{lv}-1", "task_desc": f"[Lv{lv}] {brief[:40]}（补位）"}],
                }
            )
    tasks.sort(key=lambda x: x["level"])
    return tasks
