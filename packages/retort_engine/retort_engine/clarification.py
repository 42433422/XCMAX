"""Build blocking Retort clarification questions from intent-alignment results.

This module is deterministic and side-effect free. Persistence / TTL / human
answer loops live in Modstore ``retort_clarification_gate``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def build_clarification_questions(
    assessment: Mapping[str, Any] | None,
    *,
    strategy_intent: str = "",
    changed_files: Sequence[Any] | None = None,
    max_questions: int = 3,
) -> list[dict[str, Any]]:
    """Return structured clarification questions (may be empty when aligned)."""

    intent = str(strategy_intent or "").strip()
    files = _normalize_paths(changed_files)
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
        questions.append(
            {
                "id": "intent_misaligned",
                "priority": "P0",
                "question": (
                    f"变更文件与声明意图未对齐（缺失参考：{keyword_hint}）。"
                    "请确认真实意图，或说明为何这些文件仍符合目标。"
                ),
                "reason": "retort_intent_misaligned",
                "blocking": True,
                "missing_keywords": missing,
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


def enrich_strategy_intent(strategy_intent: str, answers: Mapping[str, Any] | Sequence[Any]) -> str:
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


def clarification_needed(assessment: Mapping[str, Any] | None, strategy_intent: str = "") -> bool:
    intent = str(strategy_intent or "").strip()
    if not intent or len(intent) < 12:
        return True
    status = str((assessment or {}).get("status") or "").strip()
    return status in {"misaligned", "engine_unavailable"}


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


__all__ = [
    "build_clarification_questions",
    "clarification_needed",
    "enrich_strategy_intent",
]
