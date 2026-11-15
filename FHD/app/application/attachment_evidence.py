"""附件证据：让模型先对工件取数，再把结果拼成回答前的证据块。

流程是「轻量规划 → 执行只读工具 → 拼证据」，规划失败时退回启发式取数，
整条链路 fail-open：任何异常都不阻断正常对话。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from app.application.attachment_artifacts.models import ArtifactRecord
from app.application.attachment_artifacts.store import ArtifactStore
from app.application.attachment_artifacts.tools import TOOL_SPECS, execute_tool
from app.infrastructure.llm.invoke import chat_completion_openai_format
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 15.0
MAX_CALLS = 3
ARG_VALUE_LIMIT = 120
SUMMARY_LIMIT = 200
SECTION_LIMIT = 400
PROMPT_MESSAGE_LIMIT = 500
_DISABLED_VALUES = {"0", "false", "off", "no"}
_TOOL_NAMES = {str(spec["name"]) for spec in TOOL_SPECS}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_QUOTED = re.compile(r"[\"“”'‘’「」『』]([^\"“”'‘’「」『』]{1,40})[\"“”'‘’「」『』]")
_RANGE = re.compile(r"\d[\d,.]*\s*(?:-|~|～|—|至|到)\s*\d")

_SYSTEM_PROMPT = (
    "你是附件取数规划器。只依据用户问题挑选最少的只读工具调用，"
    "不要臆造工件 id 或表名。只输出 JSON，不要解释。"
)


def evidence_enabled() -> bool:
    """环境变量 XCAGI_ATTACHMENT_EVIDENCE 为 0/false/off/no 时关闭。"""
    raw = str(os.getenv("XCAGI_ATTACHMENT_EVIDENCE", "") or "").strip().lower()
    return raw not in _DISABLED_VALUES


def evidence_system_block(evidence: str) -> str:
    """把证据包装成前置块，约束模型只依据证据中的数字作答。"""
    text = str(evidence or "").strip()
    if not text:
        return ""
    return (
        "【附件证据】以下内容由系统检索得到。只依据该证据中的数字作答；"
        "证据不足就说不知道，不要编造。\n"
        f"{text}\n"
        "【证据结束】"
    )


def _artifact_briefs(store: ArtifactStore, artifact_ids: list[str]) -> list[dict[str, Any]]:
    """给规划器的工件摘要：只取名字与每个 sheet 的列名/行数。"""
    briefs: list[dict[str, Any]] = []
    for artifact_id in artifact_ids:
        try:
            record = store.get(artifact_id)
        except BOUNDARY_ERRORS:  # noqa: BLE001 - 证据采集 fail-open
            logger.debug("attachment evidence read record failed", exc_info=True)
            continue
        if record is None:
            continue
        briefs.append(
            {
                "id": record.id,
                "name": record.name,
                "sheets": [
                    {
                        "name": sheet.name,
                        "columns": list(sheet.columns)[:12],
                        "row_count": sheet.row_count,
                    }
                    for sheet in record.sheets
                ],
            }
        )
    return briefs


def _build_prompt(message: str, briefs: list[dict[str, Any]], limit_calls: int) -> str:
    tools = "\n".join(f"- {spec['name']}: {spec['description']}" for spec in TOOL_SPECS)
    artifacts = _compact(briefs, 1200)
    question = str(message or "").strip()[:PROMPT_MESSAGE_LIMIT]
    return (
        "可用工具：\n"
        f"{tools}\n"
        f"最多 {max(1, limit_calls)} 次调用。\n"
        '输出格式：{"calls":[{"tool":"工具名","args":{...}}]}\n'
        f"可用工件：{artifacts}\n"
        f"用户问题：{question}"
    )


def _message_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    if isinstance(payload.get("content"), str):
        return payload["content"]
    return ""


def _parse_calls(content: str, limit_calls: int) -> list[dict[str, Any]]:
    text = _FENCE.sub("", str(content or "").strip())
    if not text:
        return []
    data = json.loads(text)
    raw_calls = data.get("calls") if isinstance(data, dict) else None
    if not isinstance(raw_calls, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        if tool not in _TOOL_NAMES:
            continue
        args = item.get("args")
        calls.append({"tool": tool, "args": args if isinstance(args, dict) else {}})
        if len(calls) >= max(1, limit_calls):
            break
    return calls


async def _plan_calls(message: str, briefs: list[dict[str, Any]], limit_calls: int) -> list[dict[str, Any]]:
    """让模型挑工具；非 JSON、超时或异常一律返回空列表交给启发式兜底。"""
    try:
        payload = await asyncio.wait_for(
            chat_completion_openai_format(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _build_prompt(message, briefs, limit_calls)},
                ],
                temperature=0.1,
                max_tokens=400,
                profile="attachment_tool",
            ),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        return _parse_calls(_message_content(payload), limit_calls)
    except BOUNDARY_ERRORS:  # noqa: BLE001 - 规划失败退回启发式
        logger.debug("attachment evidence planning skipped", exc_info=True)
        return []


def _needs_rows(message: str) -> bool:
    """问题里出现引号包裹的列名或数字范围时，值得再读一段明细。"""
    text = str(message or "")
    return bool(_QUOTED.search(text) or _RANGE.search(text))


def _heuristic_calls(
    message: str, briefs: list[dict[str, Any]], limit_calls: int
) -> list[dict[str, Any]]:
    if not briefs:
        return []
    first = briefs[0]
    calls = [{"tool": "describe_attachment", "args": {"artifact_id": first["id"]}}]
    sheets = first.get("sheets") or []
    first_sheet = sheets[0] if sheets else {}
    sheet = str(first_sheet.get("name") or "") if isinstance(first_sheet, dict) else ""
    if sheet and _needs_rows(message) and len(calls) < max(1, limit_calls):
        calls.append(
            {
                "tool": "read_slice",
                "args": {"artifact_id": first["id"], "sheet": sheet, "start": 0, "limit": 50},
            }
        )
    return calls


def _compact(value: Any, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _sanitize_args(args: Any) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (args or {}).items() if isinstance(args, dict) else []:
        text = value if isinstance(value, (int, float, bool)) or value is None else str(value)
        if isinstance(text, str):
            text = text[:ARG_VALUE_LIMIT]
        clean[str(key)] = text
    return clean


def _sheet_label(
    tool: str, args: dict[str, Any], result: dict[str, Any], record: ArtifactRecord | None
) -> str:
    if tool in {"describe_attachment", "list_attachments"}:
        return "概览"
    for source in (args, result):
        value = str(source.get("sheet") or "").strip() if isinstance(source, dict) else ""
        if value:
            return value
    if record is not None and record.sheets:
        return record.sheets[0].name
    return "全部"


def _render_result(tool: str, result: dict[str, Any]) -> str:
    """把工具结果压成可读文本；明细行按行拼接，其它结果走紧凑 JSON。"""
    if tool == "read_slice":
        rows = result.get("rows")
        if isinstance(rows, list) and rows:
            lines = [" | ".join(str(cell) for cell in row) for row in rows if isinstance(row, list)]
            if lines:
                return "\n".join(lines)[:SECTION_LIMIT]
    if tool == "list_attachments":
        # 只保留文件名与总数：截断整段 JSON 会让模型只看到前几个附件，
        # 进而漏掉用户实际要导入的文件。
        names = [
            str(item.get("name") or "")
            for item in result.get("attachments") or []
            if isinstance(item, dict)
        ]
        names = [name for name in names if name]
        if names:
            return f"共 {len(names)} 个：" + "、".join(names)
    return _compact(result, SECTION_LIMIT)


def _memory_block(message: str, user_id: str) -> str:
    try:
        from app.application.user_memory.retrieve import build_memory_context

        text = str(
            build_memory_context(message, scope="global", owner_id=user_id or "default") or ""
        ).strip()
    except BOUNDARY_ERRORS:  # noqa: BLE001 - 记忆召回失败静默跳过
        logger.debug("attachment evidence memory recall skipped", exc_info=True)
        return ""
    # 统一证据块标题，避免同一段文本出现两种「记忆」小标题。
    return text.replace("【相关记忆】", "【历史记忆】", 1)


async def collect_evidence(
    message: str,
    artifact_ids: list[str],
    *,
    store: ArtifactStore | None = None,
    user_id: str = "",
    limit_calls: int = MAX_CALLS,
    max_chars: int = 4000,
) -> dict[str, Any]:
    """收集本轮可用的附件证据；无工件、未启用或存储缺失时返回空结果。"""
    result: dict[str, Any] = {"evidence": "", "trace": [], "artifacts": []}
    if not evidence_enabled() or store is None:
        return result
    raw_ids = artifact_ids if isinstance(artifact_ids, (list, tuple, set)) else []
    ids = [str(item).strip() for item in raw_ids if str(item).strip()]
    if not ids:
        return result

    briefs = _artifact_briefs(store, ids)
    if not briefs:
        return result

    calls = await _plan_calls(message, briefs, limit_calls)
    if not calls:
        calls = _heuristic_calls(message, briefs, limit_calls)

    sections: list[str] = []
    trace: list[dict[str, Any]] = []
    used: list[str] = []
    records: dict[str, ArtifactRecord | None] = {brief["id"]: None for brief in briefs}
    names = {brief["id"]: str(brief.get("name") or brief["id"]) for brief in briefs}

    for call in calls[: max(1, limit_calls)]:
        tool = str(call.get("tool") or "")
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        started = time.perf_counter()
        try:
            output = execute_tool(tool, args, store)
        except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - 单个工具失败不影响其余证据
            logger.debug("attachment evidence tool failed", exc_info=True)
            output = {"ok": False, "error": str(exc)}
        elapsed = int((time.perf_counter() - started) * 1000)
        ok = bool(output.get("ok")) if isinstance(output, dict) else False
        trace.append(
            {
                "tool": tool,
                "args": _sanitize_args(args),
                "ok": ok,
                "ms": elapsed,
                "summary": _compact(output, SUMMARY_LIMIT),
            }
        )
        artifact_id = str(args.get("artifact_id") or "")
        if artifact_id and artifact_id not in used:
            used.append(artifact_id)
            if artifact_id in records:
                try:
                    records[artifact_id] = store.get(artifact_id)
                except BOUNDARY_ERRORS:  # noqa: BLE001 - 证据采集 fail-open
                    logger.debug("attachment evidence read record failed", exc_info=True)
        if not ok:
            continue
        record = records.get(artifact_id)
        sheet = _sheet_label(tool, args, output, record)
        name = names.get(artifact_id) or (record.name if record is not None else artifact_id)
        sections.append(f"【工件 {name} / {sheet}】\n{_render_result(tool, output)}")

    blocks: list[str] = []
    memory = _memory_block(message, user_id)
    if memory:
        blocks.append(memory)
    blocks.extend(sections)
    evidence = "\n\n".join(blocks)
    return {
        "evidence": evidence[: max(0, int(max_chars))],
        "trace": trace,
        "artifacts": used,
    }