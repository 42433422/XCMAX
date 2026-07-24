"""Build blocking Retort clarification questions from intent-alignment results.

This module is deterministic and side-effect free. Persistence / TTL / human
answer loops live in Modstore ``retort_clarification_gate``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_SENSITIVE_PATH_RE = re.compile(
    r"(^|/)("
    r"\.env|"
    r"secrets?|"
    r"credentials?|"
    r"auth|"
    r"payment|"
    r"alembic|"
    r"migrations?|"
    r"docker-entrypoint|"
    r"deploy|"
    r"keys?|"
    r"cert|"
    r"id_rsa|"
    r"\.pem|"
    r"wallet"
    r")(/|\.|$)",
    re.IGNORECASE,
)
_SECRET_LINE_RE = re.compile(
    r"(api[_-]?key|secret|password|token|private[_-]?key)\s*[:=]",
    re.IGNORECASE,
)
_RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def build_clarification_questions(
    assessment: Mapping[str, Any] | None,
    *,
    strategy_intent: str = "",
    changed_files: Sequence[Any] | None = None,
    max_questions: int = 3,
    risk_level: str = "",
) -> list[dict[str, Any]]:
    """Return structured clarification questions (may be empty when aligned)."""

    intent = str(strategy_intent or "").strip()
    files = _normalize_paths(changed_files)
    added_samples = _added_line_samples(changed_files, limit=6)
    sensitive = [path for path in files if _SENSITIVE_PATH_RE.search(path)]
    secretish = [line for line in added_samples if _SECRET_LINE_RE.search(line)]
    risk = str(risk_level or "").strip().lower()
    assessment = assessment if isinstance(assessment, Mapping) else {}
    status = str(assessment.get("status") or "").strip()
    missing = [
        str(item).strip()
        for item in (assessment.get("missing_keywords") or [])
        if str(item).strip()
    ][:8]
    questions: list[dict[str, Any]] = []

    if not intent:
        questions.append(
            {
                "id": "intent_missing",
                "priority": "P0",
                "question": "本次变更的战略意图是什么？请用一句话说明要解决的问题与成功标准。",
                "reason": "strategy_intent_missing",
                "blocking": True,
            }
        )
    elif len(intent) < 12:
        questions.append(
            {
                "id": "intent_too_short",
                "priority": "P0",
                "question": f"当前意图过短（「{intent}」）。请补充范围、非目标与验收标准。",
                "reason": "strategy_intent_ambiguous",
                "blocking": True,
            }
        )

    if status == "misaligned":
        keyword_hint = "、".join(missing[:5]) if missing else "关键意图词"
        sample_hint = ""
        if added_samples:
            preview = " / ".join(added_samples[:2])
            sample_hint = f" 新增片段示例：`{preview}`。"
        file_hint = "、".join(files[:4]) if files else "（无路径）"
        questions.append(
            {
                "id": "intent_misaligned",
                "priority": "P0",
                "question": (
                    f"变更与声明意图未对齐（缺失参考：{keyword_hint}；路径：{file_hint}）。"
                    f"{sample_hint}"
                    "请确认真实意图，或说明这些改动为何仍符合目标。"
                ),
                "reason": "retort_intent_misaligned",
                "blocking": True,
                "missing_keywords": missing,
                "changed_files_sample": files[:8],
                "added_lines_sample": added_samples[:4],
            }
        )

    if sensitive:
        questions.append(
            {
                "id": "sensitive_path_confirm",
                "priority": "P0",
                "question": (
                    "检测到敏感路径改动："
                    + "、".join(sensitive[:5])
                    + "。请确认是否授权触碰认证/密钥/支付/迁移/部署相关文件，以及回滚方案。"
                ),
                "reason": "sensitive_path_change",
                "blocking": True,
                "sensitive_paths": sensitive[:8],
            }
        )

    if secretish:
        questions.append(
            {
                "id": "secret_like_addition",
                "priority": "P0",
                "question": (
                    "新增内容疑似包含密钥/口令字段（已脱敏预览）。"
                    "请确认没有明文密钥入库；若必须配置，说明应改走环境变量/密钥柜的方式。"
                ),
                "reason": "secret_like_diff",
                "blocking": True,
            }
        )

    if _RISK_ORDER.get(risk, 0) >= _RISK_ORDER["high"] or len(files) >= 12:
        questions.append(
            {
                "id": "risk_acceptance",
                "priority": "P1",
                "question": (
                    f"当前风险等级为 {risk or 'elevated'}，改动文件约 {len(files)} 个。"
                    "请确认可接受的最大影响面，以及是否允许自动合并/部署。"
                ),
                "reason": "elevated_risk_or_large_diff",
                "blocking": True,
                "risk_level": risk or "elevated",
                "changed_file_count": len(files),
            }
        )

    if files and not intent:
        sample = "、".join(files[:3])
        questions.append(
            {
                "id": "changed_files_context",
                "priority": "P1",
                "question": f"本次改动涉及 {sample} 等路径，请说明它们各自服务哪个目标。",
                "reason": "changed_files_need_context",
                "blocking": True,
            }
        )

    # Deduplicate by id while preserving order.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in questions:
        qid = str(row.get("id") or "")
        if not qid or qid in seen:
            continue
        seen.add(qid)
        out.append(row)
        if len(out) >= max(1, int(max_questions or 3)):
            break
    return out


def enrich_strategy_intent(
    strategy_intent: str, answers: Mapping[str, Any] | Sequence[Any]
) -> str:
    """Merge human answers into a richer strategy intent string."""

    base = str(strategy_intent or "").strip()
    chunks: list[str] = []
    if isinstance(answers, Mapping):
        for key, value in answers.items():
            text = str(value or "").strip()
            if text:
                chunks.append(f"{key}: {text}")
    else:
        for index, value in enumerate(answers or [], start=1):
            if isinstance(value, Mapping):
                qid = str(value.get("id") or value.get("question_id") or f"q{index}")
                text = str(value.get("answer") or value.get("text") or "").strip()
            else:
                qid = f"q{index}"
                text = str(value or "").strip()
            if text:
                chunks.append(f"{qid}: {text}")
    if not chunks:
        return base
    suffix = "；".join(chunks)
    if not base:
        return suffix[:4000]
    if suffix in base:
        return base[:4000]
    return f"{base} | 澄清补充：{suffix}"[:4000]


def clarification_needed(
    assessment: Mapping[str, Any] | None,
    strategy_intent: str = "",
    *,
    changed_files: Sequence[Any] | None = None,
    risk_level: str = "",
) -> bool:
    intent = str(strategy_intent or "").strip()
    if not intent or len(intent) < 12:
        return True
    status = str((assessment or {}).get("status") or "").strip()
    if status in {"misaligned", "engine_unavailable"}:
        return True
    files = _normalize_paths(changed_files)
    if any(_SENSITIVE_PATH_RE.search(path) for path in files):
        return True
    if any(
        _SECRET_LINE_RE.search(line)
        for line in _added_line_samples(changed_files, limit=20)
    ):
        return True
    risk = str(risk_level or "").strip().lower()
    if _RISK_ORDER.get(risk, 0) >= _RISK_ORDER["high"] or len(files) >= 12:
        return True
    return False


def _normalize_paths(changed_files: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    for item in changed_files or []:
        if isinstance(item, str):
            path = item.strip()
        elif isinstance(item, Mapping):
            path = str(item.get("path") or "").strip()
        else:
            path = ""
        if path and path not in out:
            out.append(path)
    return out


def _added_line_samples(
    changed_files: Sequence[Any] | None, *, limit: int = 6
) -> list[str]:
    samples: list[str] = []
    for item in changed_files or []:
        if not isinstance(item, Mapping):
            continue
        for hunk in item.get("hunks") or []:
            if not isinstance(hunk, Mapping):
                continue
            for change in hunk.get("changes") or []:
                if not isinstance(change, Mapping):
                    continue
                if change.get("type") != "add":
                    continue
                text = str(change.get("text") or "").strip()
                if not text or text.startswith("+++") or text.startswith("---"):
                    continue
                # Never keep likely secret values in samples.
                redacted = _SECRET_LINE_RE.sub(r"\1=<redacted>", text)
                samples.append(redacted[:160])
                if len(samples) >= limit:
                    return samples
    return samples


__all__ = [
    "build_clarification_questions",
    "clarification_needed",
    "enrich_strategy_intent",
]
