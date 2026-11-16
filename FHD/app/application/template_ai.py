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
_PROPOSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_type": {"type": "string"},
        "template_index": {"type": "integer"},
        "name": {"type": "string"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "field_mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["source", "target"],
            },
        },
    },
    "required": ["target_type", "confidence"],
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


def _ask(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    lane: str,
    max_tokens: int = 400,
) -> LlmAssistResult:
    try:
        return _complete(messages, schema=schema, max_tokens=max_tokens, lane=lane)
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
    raw_index = result.data.get("index")
    if raw_index is None:
        return None
    try:
        index = int(raw_index)
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


def propose_import_template(
    *,
    file_name: str,
    sheet_title: str = "",
    headers: Iterable[Any] = (),
    samples: dict[str, Iterable[Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    targets: list[dict[str, Any]] | None = None,
    minimum_confidence: float = 0.6,
) -> dict[str, Any] | None:
    """一次调用识别导入目标、挑选/生成字段映射并给出模板名。

    返回值只是提案：目标类型、命中的候选序号（没有则 -1）、模板名、置信度、
    依据和字段映射。调用方必须自行校验列是否存在、必填是否覆盖。
    """
    head = [str(item).strip() for item in headers if str(item).strip()][:40]
    if not head or not targets:
        return None
    samples = samples or {}
    sample_lines = []
    for header in head:
        values = [
            str(value)[:40]
            for value in list(samples.get(header) or [])[:3]
            if value not in (None, "")
        ]
        if values:
            sample_lines.append(f"{header}：{' / '.join(values)}")
    target_lines = []
    for item in targets:
        fields = "、".join(
            f"{field.get('label')}({field.get('key')})" for field in item.get("fields") or []
        )
        target_lines.append(f"- {item.get('type')}（{item.get('label')}）字段：{fields}")
    candidate_lines = []
    for index, item in enumerate(candidates or []):
        candidate_lines.append(
            f"{index}. {item.get('name') or ''}｜目标 {item.get('target_type') or ''}"
            f"｜表头 {', '.join(list((item.get('source_features') or {}).get('headers') or [])[:12])}"
        )
    messages = [
        {
            "role": "system",
            "content": (
                "你在识别企业 Excel/CSV 的业务目标并生成导入字段映射。只输出 JSON。"
                "表头是列名，样例行只用于判断列的含义。"
                "target_type 只能从给定目标里选；字段映射的 source 必须是给定表头之一，"
                "target 必须是该目标的字段 key。"
                "已有候选模板能匹配时给出 template_index，否则给 -1 并自行生成映射。"
                "流水/台账（采购、应收、对账、考勤原始记录）不要强行映射成客户或产品主数据。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"文件名：{file_name}\n工作表：{sheet_title}\n"
                f"表头：{' | '.join(head)}\n样例：\n"
                + "\n".join(sample_lines)
                + "\n可选目标：\n"
                + "\n".join(target_lines)
                + "\n已有候选模板：\n"
                + ("\n".join(candidate_lines) or "（无）")
            ),
        },
    ]
    result = _ask(messages, schema=_PROPOSE_SCHEMA, lane="template_propose", max_tokens=900)
    if not result.used_llm or result.degraded or not isinstance(result.data, dict):
        return None
    data = result.data
    target = str(data.get("target_type") or "").strip()
    if target not in {str(item.get("type") or "") for item in targets}:
        return None
    raw_index = data.get("template_index")
    try:
        confidence = float(data.get("confidence") or 0)
        index = int(raw_index) if raw_index is not None else -1
    except (TypeError, ValueError):
        return None
    if confidence < minimum_confidence:
        return None
    if index >= len(candidates or []):
        index = -1
    mappings = []
    for item in list(data.get("field_mappings") or []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        field = str(item.get("target") or "").strip()
        if not source or not field:
            continue
        try:
            item_confidence = float(item.get("confidence") or confidence)
        except (TypeError, ValueError):
            item_confidence = confidence
        mappings.append(
            {"source": source, "target": field, "confidence": round(item_confidence, 4)}
        )
    return {
        "target_type": target,
        "template_index": index,
        "name": _clean_name(str(data.get("name") or "")),
        "confidence": round(confidence, 4),
        "reason": str(data.get("reason") or "")[:200],
        "field_mappings": mappings,
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
    "propose_import_template",
    "rank_templates",
    "rename_meaningless_templates",
    "suggest_template_name",
]
