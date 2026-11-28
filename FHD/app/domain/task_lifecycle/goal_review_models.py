"""Strict goal review schemas and frozen source identities; no execution authority."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from itertools import islice
from typing import Any, Literal

from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field


class PlanToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    node_id: str = Field(min_length=1, max_length=80)
    tool_id: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=200)
    params: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list, max_length=64)
    approval_required: bool


class PlannedToolCall(PlanToolAction):
    response_excerpt: str = Field(
        min_length=1, max_length=4000, description="当前成稿中包含该动作的原文"
    )


class PlannedNavigation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    navigation_id: str = Field(min_length=1, max_length=80)
    response_excerpt: str = Field(min_length=1, max_length=4000)


class FileCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    evidence_id: str = Field(min_length=1, max_length=200)
    source_excerpt: str = Field(
        min_length=1, max_length=4000, description="宿主文件证据中的连续原文"
    )
    response_excerpt: str = Field(
        min_length=1, max_length=4000, description="由该文件证据支撑的当前成稿原文"
    )


class GoalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    goal_id: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=4000)
    kind: Literal["reply", "read", "write", "constraint", "planned_action"]
    status: Literal["satisfied", "unmet", "not_applicable"]
    evidence_ids: list[str] = Field(max_length=256)
    reason: str = Field(min_length=1, max_length=4000)
    planned_calls: list[PlannedToolCall] = Field(
        default_factory=list,
        max_length=64,
        description="planned_action 的业务动作契约。纯文字方案使用 reply。",
    )
    planned_navigation: list[PlannedNavigation] = Field(
        default_factory=list,
        max_length=20,
        description="planned_action 的人工页面入口和成稿原文。",
    )
    file_basis: Literal["independent", "passages", "complete"] | None = Field(
        default=None,
        description=(
            "independent：目标与成稿均不依赖附件事实；passages：依赖附件局部内容；"
            "complete：汇总、比较或完整性声明需要完整范围。历史助手答复不属于文件证据。"
        ),
    )
    file_citations: list[FileCitation] = Field(
        default_factory=list,
        max_length=64,
        description="逐项关联成稿事实与实际文件引文。缺少所需来源时目标为 unmet。",
    )


class GoalReview(BaseModel):
    """A non-executing semantic assessment, constrained by host receipt validation."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    goals: list[GoalAssessment] = Field(min_length=1, max_length=64)
    violations: list[str] = Field(max_length=64)
    uncovered_sources: list[str] = Field(max_length=64)
    feedback: str = Field(max_length=12000)
    feedback_disposition: Literal["none", "advisory", "blocking"] | None = None
    plan_content: Literal["steps", "narrative"] | None = Field(
        default=None,
        description=(
            "从原始要求与成稿独立识别方案类型。出现或要求具体工具、参数或产品入口时为 steps，"
            "包括尚未核实的具体声明。narrative 仅用于与产品能力无关的文字方案。"
        ),
    )


def goal_source_catalogue(
    contract: dict[str, Any], answers: Sequence[dict[str, Any]] = ()
) -> dict[str, dict[str, Any]]:
    """Derive locatable obligations from frozen user input, never assistant/tool claims."""
    kinds = ["reply", "constraint"] + (
        ["planned_action"]
        if contract["scope"].get("requested_deliverable") == "action_plan"
        else ["read", "write"]
    )
    sources = {
        "request": {"text": contract["request"]["text"], "role": "user", "allowed_kinds": kinds}
    }
    for item in contract["request"].get("attachments") or []:
        metadata, preview = item.get("metadata") or {}, item.get("preview") or {}
        digest, text = metadata.get("sha256"), preview.get("text")
        if (
            item.get("source") == "owned_elt_upload"
            and isinstance(digest, str)
            and len(digest) == 64
            and isinstance(text, str)
            and text.strip()
        ):
            # A document specifies acceptance criteria, never permission to act.
            # Only the frozen user request can authorize a read/write objective.
            sources["attachment:" + digest] = {
                "text": text,
                "role": "attachment",
                "allowed_kinds": ["constraint"],
            }
    for row in answers:
        identity, text = row.get("source_id"), row.get("answer")
        if (
            isinstance(identity, str)
            and identity.startswith("answer:")
            and identity != "answer:"
            and identity not in sources
            and isinstance(text, str)
            and text.strip()
        ):
            sources[identity] = {"text": text, "role": "user", "allowed_kinds": kinds}
    objective = (contract["scope"].get("constraints") or {}).get("objective")
    if isinstance(objective, str) and objective.strip():
        sources["objective"] = {
            "text": objective,
            "role": "host",
            "allowed_kinds": ["read", "write"],
        }
    for index, row in enumerate(contract["request"].get("history") or []):
        if (
            isinstance(row, dict)
            and row.get("role") == "user"
            and isinstance(row.get("content"), str)
            and row["content"].strip()
        ):
            sources[f"history:{index}:user"] = {
                "text": row["content"],
                "role": "user",
                "allowed_kinds": ["reply", "constraint"],
            }
    return sources


def review_provenance_defects(raw: Any, sources: dict[str, dict[str, Any]]) -> list[str]:
    """Check source bindings even when unrelated optional wire fields are missing."""
    if not isinstance(raw, dict) or not isinstance(raw.get("goals"), list):
        return []
    seen: set[str] = set()
    errors = []
    for goal in raw["goals"][:64]:
        if not isinstance(goal, dict):
            continue
        identity, origin, quote = (goal.get(key) for key in ("goal_id", "source_id", "source"))
        if (
            not isinstance(identity, str)
            or not isinstance(origin, str)
            or not isinstance(quote, str)
        ):
            continue
        source = sources.get(origin)
        texts = (
            [row["text"] for key, row in sources.items() if key.startswith("history:")]
            if origin == "history"
            else []
        )
        known = bool(texts) if origin == "history" else source is not None
        matches = (
            any(quote in text for text in texts)
            if origin == "history"
            else source is not None and quote in source["text"]
        )
        if identity in seen:
            errors.append(f"goal_id_duplicate: 目标 {identity} 的唯一标识重复")
        if not known:
            errors.append(
                f"goal_source_unknown: 目标 {identity} 的来源 {origin} 不存在，缺少原始请求证据"
            )
        elif not matches:
            errors.append(
                f"goal_source_mismatch: 目标 {identity} 的引用不匹配来源 {origin}，缺少原始请求证据"
            )
        if (
            source
            and goal.get("kind") not in source["allowed_kinds"]
            and origin.startswith("attachment:")
        ):
            errors.append(f"goal_source_kind_invalid: 附件条件 {identity} 不得创建业务操作")
        seen.add(identity)
    return errors


def normalize_review_provenance(raw: Any, contract: dict[str, Any]) -> Any:
    """Normalize current-request aliases only for verbatim frozen request text."""
    if not isinstance(raw, dict) or not isinstance(raw.get("goals"), list):
        return raw
    request = contract["request"]["text"]
    for goal in raw["goals"]:
        if (
            isinstance(goal, dict)
            and goal.get("source_id") in {"original_request", "input", "user_request"}
            and isinstance(goal.get("source"), str)
            and goal["source"] in request
        ):
            goal["source_id"] = "request"
    return raw


def review_judgments(review: dict[str, Any]) -> dict[str, Any]:
    """Only identifiers and verbatim source bindings may change during repair."""
    return {
        **review,
        "goals": [
            {
                key: value
                for key, value in goal.items()
                if key not in {"goal_id", "source_id", "source"}
            }
            for goal in review["goals"]
        ],
    }


def preserves_source_bindings(
    previous: dict[str, Any],
    review: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> bool:
    for before, after in zip(previous["goals"], review["goals"], strict=True):
        quote = before["source"]
        if quote in sources.get(before["source_id"], {}).get("text", ""):
            if (before["source_id"], quote) != (after["source_id"], after["source"]):
                return False
        elif (
            any(quote in source["text"] for source in sources.values()) and quote != after["source"]
        ):
            return False
    return True


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate key in goal review JSON")
    return result


def review_schema_defects(errors: Iterable[SchemaValidationError]) -> list[dict[str, object]]:
    """Bounded contract defects only; never include document or response values."""
    defects: list[dict[str, object]] = []
    for error in islice(errors, 128):
        defect: dict[str, object] = {"path": list(error.absolute_path), "rule": error.validator}
        if error.validator == "required" and isinstance(error.instance, dict):
            defect["missing"] = [
                field for field in error.validator_value if field not in error.instance
            ]
        defects.append(defect)
    return defects


def review_json_text(value: str) -> str:
    """Unwrap one presentation fence; all JSON and host checks still apply."""
    text = value.strip()
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].lower() in {"```", "```json"} and lines[-1] == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def verbatim_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    stride = max(1, math.ceil(len(lines) / 128))
    blocks = []
    for start in range(0, len(lines), stride):
        block = "".join(lines[start : start + stride]).strip()
        for offset in range(0, len(block), 4000):
            if bounded := block[offset : offset + 4000].strip():
                blocks.append(bounded)
    return blocks


def file_citation_catalogue(
    file_evidence: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, tuple[str, str]],
]:
    documents = {}
    sources: dict[str, tuple[str, str]] = {}
    for identity, source in file_evidence.items():
        blocks = {}
        for block in verbatim_blocks(source["text"]):
            block_id = f"s{len(sources) + 1}"
            sources[block_id] = (identity, block)
            blocks[block_id] = block
        documents[identity] = {key: value for key, value in source.items() if key != "text"}
        documents[identity]["blocks"] = blocks
    return documents, sources


def resolve_file_citations(
    review: dict[str, Any],
    sources: dict[str, tuple[str, str]],
    responses: dict[str, str],
) -> None:
    for goal in review["goals"]:
        if "file_citations" in goal:
            for cite in goal["file_citations"]:
                identity, source = sources[cite.pop("source_block_id")]
                cite.update(
                    evidence_id=identity,
                    source_excerpt=source,
                    response_excerpt=responses[cite.pop("response_block_id")],
                )


_REFERENCE_PREFIX = re.compile(r"^\[原文消息 #[^\]]*\]\n?")
_LANGUAGE_MENTION = re.compile(
    r"英文|英语|中文|汉语|简体|繁体|日文|日语|韩文|韩语|德文|德语|法文|法语|"
    r"西班牙文|西班牙语|俄文|俄语|葡萄牙语|English|Chinese|Japanese|Korean|German|"
    r"French|Spanish|Russian|Portuguese",
    re.IGNORECASE,
)
_REVISION_CUE = re.compile(
    r"(?:再|更)(?:正式|简洁|详细|礼貌|专业|口语|生动)"
    r"|(?:润色|重写|改写|缩写|扩写|调整|修改|补充|完善)"
    r"(?:一下|一遍)?(?:这封|该|上述|上一版|这个)?(?:邮件|正文|文案|回复|回答|内容|方案|措辞|语气|格式)",
)


def _dominant_script(text: str) -> str:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk >= 8 and cjk * 4 >= latin:
        return "zh"
    if latin >= 40 and latin * 4 >= cjk:
        return "en"
    return ""


def _established_language(request: dict[str, Any]) -> str:
    if _LANGUAGE_MENTION.search(str(request.get("text") or "")):
        return ""
    for row in reversed(request.get("history") or []):
        if isinstance(row, dict) and row.get("role") == "assistant":
            content = _REFERENCE_PREFIX.sub("", str(row.get("content") or ""))
            if script := _dominant_script(content):
                return script
    return ""


def language_continuity_feedback(request: dict[str, Any], response: str) -> str:
    """Reject a revised deliverable that silently switches its established language."""
    if not _REVISION_CUE.search(str(request.get("text") or "")):
        return ""
    expected = _established_language(request)
    actual = _dominant_script(response)
    if not expected or not actual or expected == actual:
        return ""
    name = "英文" if expected == "en" else "中文"
    return f"上一版成稿使用{name}，本轮未要求更换成稿语言；请沿用{name}重写完整成稿。"
