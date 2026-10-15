"""Resolve ``{{node_id.path}}`` step references before an agent step runs (#2288).

The planner sometimes writes parameters that point at an earlier step's output,
e.g. ``{{query_product.data_preview[0].id}}``. They are resolved against the
outputs of completed steps only when the reference names exactly one value; a
list with several rows is ambiguous and is never silently narrowed to its first
row. Anything left unresolved is reported so the step is refused before any
tool (and therefore any business write) is called.
"""

from __future__ import annotations

import re
from typing import Any

_FULL = re.compile(r"^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$")
_EMBEDDED = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_TOKEN = re.compile(r"\[(\d+)\]|\.?([A-Za-z_\u4e00-\u9fff][\w\-\u4e00-\u9fff]*)")
_ALIASES = {"data_preview": "data", "rows": "data", "items": "data", "result": "data"}
_PREFIXES = ("node_outputs", "outputs", "steps", "nodes")


class UnresolvedReference(ValueError):
    pass


def _tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    pos = 0
    while pos < len(path):
        match = _TOKEN.match(path, pos)
        if match is None or match.end() == pos:
            raise UnresolvedReference(f"无法识别的引用 {{{{{path}}}}}")
        tokens.append(int(match.group(1)) if match.group(1) is not None else match.group(2))
        pos = match.end()
    while len(tokens) > 1 and tokens[0] in _PREFIXES:
        tokens.pop(0)
    return tokens


def _single(rows: list[Any], path: str) -> Any:
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise UnresolvedReference(f"{{{{{path}}}}} 引用的前序结果为空")
    raise UnresolvedReference(f"{{{{{path}}}}} 引用的前序结果有 {len(rows)} 条，无法确定是哪一条")


def _lookup(outputs: dict[str, Any], path: str) -> Any:
    tokens = _tokens(path.strip())
    head = tokens[0] if tokens else ""
    if not isinstance(head, str) or head not in outputs:
        raise UnresolvedReference(f"{{{{{path}}}}} 引用的步骤 {head or '?'} 尚未完成")
    current: Any = outputs[head]
    for token in tokens[1:]:
        if isinstance(token, int):
            if not isinstance(current, list) or token != 0:
                raise UnresolvedReference(f"{{{{{path}}}}} 的下标无法唯一确定")
            current = _single(current, path)
            continue
        for _ in range(3):
            if isinstance(current, list):
                current = _single(current, path)
            elif isinstance(current, dict):
                key = token if token in current else _ALIASES.get(token, token)
                if key in current:
                    current = current[key]
                    break
                if "data" not in current:
                    raise UnresolvedReference(f"{{{{{path}}}}} 在前序结果中找不到字段 {token}")
                current = current["data"]
            else:
                raise UnresolvedReference(f"{{{{{path}}}}} 在前序结果中找不到字段 {token}")
        else:
            raise UnresolvedReference(f"{{{{{path}}}}} 在前序结果中找不到字段 {token}")
    if isinstance(current, list):
        current = _single(current, path)
    if current is None or current == "" or isinstance(current, (dict, list)):
        raise UnresolvedReference(f"{{{{{path}}}}} 没有解析出具体值")
    return current


def resolve_references(value: Any, outputs: dict[str, Any], problems: list[str]) -> Any:
    """Return ``value`` with references substituted; unresolved ones go to ``problems``."""
    if isinstance(value, dict):
        return {k: resolve_references(v, outputs, problems) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_references(v, outputs, problems) for v in value]
    if not isinstance(value, str) or "{{" not in value:
        return value
    full = _FULL.match(value)
    try:
        if full:
            return _lookup(outputs, full.group(1))
        return _EMBEDDED.sub(lambda m: str(_lookup(outputs, m.group(1))), value)
    except UnresolvedReference as exc:
        problems.append(str(exc))
        return value


def unresolved_placeholders(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            p
            for k, v in value.items()
            if k != "_runtime_context"
            for p in unresolved_placeholders(v)
        ]
    if isinstance(value, list):
        return [p for v in value for p in unresolved_placeholders(v)]
    return [value] if isinstance(value, str) and "{{" in value else []


def unresolved_message(step_label: str, problems: list[str]) -> str:
    detail = "；".join(dict.fromkeys(problems))[:400]
    return (
        f"步骤「{step_label}」的参数引用了前序结果但无法确定具体值（{detail}），"
        "本步骤未执行；此前已完成的步骤保持不变。请先核对原任务进度，再说明具体的产品、客户或仓库。"
    )


UNRESOLVED_CODE = "unresolved_param_reference"


def refuse_unresolved_step(run: Any, step: Any, node_outputs: dict[str, Any]) -> bool:
    """Resolve ``step.params`` in place; on failure fail the run without calling a tool.

    Runs before the confirmation gate, so the approval card and its grant hash
    cover the concrete values rather than the template text.
    """
    problems: list[str] = []
    resolved = resolve_references(dict(step.params or {}), node_outputs, problems)
    if not problems:
        problems = [f"无法识别的占位符 {p[:80]}" for p in unresolved_placeholders(resolved)]
    if not problems:
        if resolved != step.params:
            step.params = resolved
            run.add_event("step.references_resolved", f"步骤 {step.node_id} 参数引用已解析")
        return False
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    unsafe = []
    for completed in run.steps:
        if completed.status != "completed":
            continue
        spec = get_tool_action_spec(completed.tool_id, completed.action)
        if not (completed.idempotent and spec and spec.idempotent):
            unsafe.append(completed.step_id)
    if unsafe:
        run.metadata["non_retryable"] = True
        run.metadata["recovery"] = {
            "state": "manual_reconciliation_required",
            "error_code": UNRESOLVED_CODE,
            "step_ids": unsafe,
        }
    message = unresolved_message(step.description or step.node_id, problems)
    step.status = "failed"
    step.error = message
    step.output = {"success": False, "error_code": UNRESOLVED_CODE, "message": message}
    run.status = "failed"
    run.error = message
    run.final_output = {
        "node_outputs": dict(node_outputs),
        "failed_step_id": step.step_id,
        "error": message,
        "error_code": UNRESOLVED_CODE,
    }
    run.add_event(
        "step.reference_unresolved",
        message,
        {"step_id": step.step_id, "node_id": step.node_id, "problems": problems[:5]},
    )
    return True
