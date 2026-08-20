# mypy: disable-error-code="attr-defined, call-overload, no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _is_all_hands_cognition_context(inp: _facade().Any) -> bool:
    if not isinstance(inp, dict):
        return False
    if inp.get("all_hands_standby") is True:
        return True
    rc = inp.get("role_context")
    if isinstance(rc, dict):
        mode = str(rc.get("mode") or "").strip()
        if mode in _facade()._ALL_HANDS_ROLE_CONTEXT_MODES:
            return True
    return False


def _build_all_hands_cognition_user_message(
    task: str,
    normalized_input: _facade().Dict[str, _facade().Any],
    *,
    session_context_json: str = "",
) -> str:
    """与 ``all_hands_report._standby_manifest_report_via_bench`` 一致：任务模板 + JSON 上下文。"""
    payload_json = _facade().json.dumps(normalized_input, ensure_ascii=False)
    if len(payload_json) > 14000:
        payload_json = payload_json[:14000]
    task_part = str(task or "").strip()
    if task_part:
        user_input = f"{task_part}\n\n---\n\n以下为结构化输入（JSON），请据此撰写四段 Markdown 汇报：\n{payload_json}"
    else:
        user_input = payload_json
    if session_context_json:
        user_input = f"{user_input}\n\n[session_context]\n{session_context_json}"
    return user_input


def _metric_task_preview(task: object) -> str:
    """单行动略预览：``employee_execution_metrics.task`` 列为 VARCHAR(128)。"""
    t = str(task or "").replace("\r\n", "\n").replace("\r", "\n")
    t = " ".join(t.split())
    if len(t) <= _facade()._METRIC_TASK_MAX_LEN:
        return t
    return t[: _facade()._METRIC_TASK_MAX_LEN - 1] + "…"


def _flag_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_metric_user_id(session: _facade().Any, user_id: object) -> int:
    """定时任务 / 员工大会常传 ``user_id=0``；指标表 ``user_id`` 须指向真实 ``users.id``。"""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        uid = 0
    if uid > 0:
        row = session.query(_facade().User.id).filter(_facade().User.id == uid).first()
        if row is not None:
            return int(row[0])
    row = session.query(_facade().User.id).order_by(_facade().User.id.asc()).limit(1).first()
    if row is None:
        raise RuntimeError("employee_execution_metrics: 库中无 users 行，无法写入指标")
    return int(row[0])
