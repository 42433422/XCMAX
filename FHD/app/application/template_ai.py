"""AI-assisted template naming and matching (advisory, always degradable).

模板库的两类 AI 能力都放在这里，规则永远优先：

- ``suggest_template_name``：给导入切出的区段起业务名，模型不可用时返回空串，调用方保留原命名。
- ``rank_templates``：在候选模板里按用户说法做语义排序；模型不可用或分数不够时返回 None，
  调用方回退到精确/唯一匹配。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from app.application.elt.llm_assist import LlmAssistResult, _complete
from app.utils.operational_errors import RECOVERABLE_ERRORS

_NAME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["name"],
}
_RANK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "index": {"type": "integer"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["index", "confidence"],
}

_NAME_LIMIT = 24
# 机器生成的占位名：文件名-区段N、Sheet1-模板、Excel、模板1 等。
_MEANINGLESS_RE = re.compile(
    r"^(?:.*[-_]\s*(?:区段|区域|region|sheet)\s*\d*|sheet\s*\d+|excel\s*\d*|模板\s*\d*|.*-模板)$",
    re.I,
)


def is_meaningless_name(name: str) -> bool:
    """已有的模板名是否只是机器占位（可以安全尝试 AI 重命名）。"""
    return bool(_MEANINGLESS_RE.match(str(name or "").strip()))


def _ask(messages: list[dict[str, str]], *, schema: dict[str, Any], lane: str) -> LlmAssistResult:
    try:
        return _complete(messages, schema=schema, max_tokens=400, lane=lane)
    except RECOVERABLE_ERRORS:
        return LlmAssistResult()


def _clean_name(raw: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", str(raw or "")).strip().strip("《》\"'`")
    value = re.sub(r"\s+", " ", value)
    return value[:_NAME_LIMIT]


def suggest_template_name(
    *,
    file_name: str,
    sheet_title: str = "",
    region_label: str = "",
    target_type: str = "",
    headers: Iterable[Any] = (),
) -> str:
    """让模型给区段起一个业务名；不可用或答案不可信时返回空串。"""
    head = [str(item).strip() for item in headers if str(item).strip()][:12]
    if not file_name and not sheet_title:
        return ""
    messages = [
        {
            "role": "system",
            "content": (
                "你在给企业 Excel 模板起名。只输出 JSON。"
                f"名称不超过 {_NAME_LIMIT} 个汉字，必须是业务含义（如“材料采购明细”“生产打印单”“客户对账表”），"
                "不要包含日期、文件名后缀、编号或“模板”二字。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"文件名：{file_name}\n工作表：{sheet_title}\n区段：{region_label}\n"
                f"导入目标：{target_type}\n表头：{' | '.join(head)}"
            ),
        },
    ]
    result = _ask(messages, schema=_NAME_SCHEMA, lane="template_name")
    if not result.used_llm or result.degraded or not isinstance(result.data, dict):
        return ""
    name = _clean_name(str(result.data.get("name") or ""))
    try:
        confidence = float(result.data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if not name or confidence < 0.5 or is_meaningless_name(name):
        return ""
    return name


def rank_templates(
    *,
    requirement: str,
    candidates: list[dict[str, Any]],
    minimum_confidence: float = 0.6,
) -> dict[str, Any] | None:
    """按用户说法在候选模板中选出最合适的一个；选不出时返回 None。"""
    requirement = str(requirement or "").strip()
    if not requirement or not candidates:
        return None
    lines = []
    for index, item in enumerate(candidates):
        lines.append(
            f"{index}. 名称：{item.get('name') or ''}｜范围：{item.get('scope') or item.get('template_type') or ''}"
            f"｜说明：{str(item.get('description') or '')[:60]}"
        )
    messages = [
        {
            "role": "system",
            "content": (
                "你在为企业文档模板做语义匹配。只输出 JSON：index 为候选序号（从 0 开始），"
                "confidence 为 0~1。没有任何候选符合用户要求时 index 输出 -1、confidence 输出 0。"
            ),
        },
        {"role": "user", "content": f"用户要求：{requirement}\n候选：\n" + "\n".join(lines)},
    ]
    result = _ask(messages, schema=_RANK_SCHEMA, lane="template_match")
    if not result.used_llm or result.degraded or not isinstance(result.data, dict):
        return None
    try:
        index = int(result.data.get("index"))
        confidence = float(result.data.get("confidence") or 0)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= len(candidates) or confidence < minimum_confidence:
        return None
    return {
        "index": index,
        "confidence": round(confidence, 4),
        "reason": str(result.data.get("reason") or "")[:160],
        "template": candidates[index],
    }


def rename_meaningless_templates(service: Any, *, limit: int = 3) -> list[dict[str, str]]:
    """把模板库里机器占位名换成业务名；每次最多处理 ``limit`` 个，失败静默跳过。"""
    try:
        templates = [
            item
            for item in (service.get_templates().get("templates") or [])
            if str(item.get("source") or "") == "db" and item.get("db_id")
        ]
    except RECOVERABLE_ERRORS:
        return []
    used = {str(item.get("name") or "").strip() for item in templates}
    renamed: list[dict[str, str]] = []
    for item in templates:
        if len(renamed) >= limit:
            break
        current = str(item.get("name") or "").strip()
        if not is_meaningless_name(current):
            continue
        file_name = str(item.get("filename") or "").strip() or current
        proposal = suggest_template_name(
            file_name=file_name,
            sheet_title=str(item.get("business_scope") or ""),
            target_type=str(item.get("template_type") or ""),
            headers=_stored_labels(item),
        )
        if not proposal or proposal in used:
            continue
        result = service.update_template(int(item["db_id"]), {"template_name": proposal})
        if not (isinstance(result, dict) and result.get("success")):
            continue
        used.discard(current)
        used.add(proposal)
        renamed.append({"id": str(item["db_id"]), "from": current, "to": proposal})
    return renamed


def _stored_labels(item: dict[str, Any]) -> list[str]:
    fields = item.get("fields")
    if not isinstance(fields, list):
        return []
    return [str(field.get("label") or "") for field in fields if isinstance(field, dict)]


__all__ = [
    "is_meaningless_name",
    "rank_templates",
    "rename_meaningless_templates",
    "suggest_template_name",
]
