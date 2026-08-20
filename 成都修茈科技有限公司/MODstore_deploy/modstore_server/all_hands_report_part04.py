# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.all_hands_report")


def _employee_answer_excerpt(
    row: _facade().Dict[str, _facade().Any], *, max_chars: int = 800
) -> str:
    md = str(row.get("report_markdown") or "").strip()
    if md:
        if row.get(
            "report_mode"
        ) == "standby_manifest_bench" or _facade()._is_standby_pipeline_json_noise(md):
            md = _facade()._coerce_standby_excerpt(md, row)
        return md[:max_chars]
    err = str(row.get("cognition_error") or "").strip()
    if err:
        return f"（员工执行失败：{err}）"
    warns = row.get("warnings") or []
    if isinstance(warns, list) and warns:
        filtered = [
            str(w)
            for w in warns
            if str(w).strip()
            and "输入不足" not in str(w)
            and ("research failed" not in str(w).lower())
        ]
        if filtered:
            return f"（员工无报告，警告：{'; '.join(filtered)[:max_chars]}）"
    return "（员工无报告）"


async def synthesize_all_hands_answer(
    *,
    user_question: str,
    employees: _facade().List[_facade().Dict[str, _facade().Any]],
    bench_provider: str,
    bench_model: str,
    user_id: int,
) -> _facade().Dict[str, _facade().Any]:
    """把多名员工的 Q&A 答复送给 bench LLM 合并成「数字管家综合答复」。

    返回 ``{ markdown, cited_employees: [pkg_id], model, error }``；
    bench LLM 不可用或失败时 ``markdown == ""`` 且 ``error`` 非空。
    """
    started_at = _facade().datetime.now(_facade().timezone.utc).isoformat()
    cited = [
        str(r.get("employee_id") or "").strip()
        for r in employees
        if str(r.get("employee_id") or "").strip()
    ]
    if not bench_provider or not bench_model:
        return {
            "question": user_question,
            "markdown": "",
            "cited_employees": cited,
            "generated_at": started_at,
            "model": "",
            "error": "平台 Bench LLM 未配置（MODSTORE_EMPLOYEE_BENCH_* 或平台 Key）",
        }
    parts: _facade().List[str] = []
    for row in employees:
        eid = str(row.get("employee_id") or "").strip()
        name = str(row.get("name") or eid).strip()
        area = str(row.get("area") or "").strip()
        if not eid:
            continue
        excerpt = _facade()._employee_answer_excerpt(row)
        parts.append(f"### [{eid}] {name}（区域：{area or '未知'}）\n\n{excerpt}")
    body = "\n\n".join(parts) if parts else "（没有可合并的员工答复）"
    user_content = f"管理员问题：\n{(user_question or '').strip()}\n\n以下是 {len(parts)} 名员工以自身岗位视角给出的答复：\n\n{body}"
    messages = [
        {"role": "system", "content": _facade()._SYNTHESIZE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = _facade().get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db,
                int(user_id or 0),
                bench_provider,
                bench_model,
                messages,
                max_tokens=2048,
            )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("synthesize_all_hands_answer dispatch failed")
        return {
            "question": user_question,
            "markdown": "",
            "cited_employees": cited,
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": f"调用 bench LLM 异常：{exc}",
        }
    if not isinstance(result, dict) or not result.get("ok"):
        err = ""
        if isinstance(result, dict):
            err = str(result.get("error") or "").strip()
        return {
            "question": user_question,
            "markdown": "",
            "cited_employees": cited,
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": err or "bench LLM 未返回有效内容",
        }
    md = str(result.get("content") or "").strip()
    if not md:
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                md = str(msg.get("content") or "").strip()
    return {
        "question": user_question,
        "markdown": md,
        "cited_employees": cited,
        "generated_at": started_at,
        "model": f"{bench_provider}/{bench_model}",
        "error": "" if md else "bench LLM 返回为空",
    }
