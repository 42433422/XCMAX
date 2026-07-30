"""Collectors and exporters for distillation continuous learning."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from app.services.distillation_continuous_learning_models import (
    CONTINUOUS_LEARNING_DIR,
    CONTINUOUS_TRAINING_DATA_NAME,
    ContinuousLearningCorpus,
    KnowledgeUnit,
    LearningSample,
    _coerce_dict,
    _coerce_float,
    _load_jsonish_rows,
    _now_iso,
    infer_intent_label,
    normalize_intent_label,
)

logger = logging.getLogger(__name__)


def _write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect_user_feedback_samples(memory_path: str | Path | None = None) -> list[LearningSample]:
    """Collect reviewer-backed intent samples from user memory feedback history."""

    source_path = Path(memory_path or os.path.join(BASE_DIR, "user_memory", "memory_store.json"))
    if not source_path.is_file():
        return []
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []

    samples: list[LearningSample] = []
    for user_id, memory in raw.items():
        if not isinstance(memory, dict):
            continue
        feedback_history = memory.get("feedback_history")
        if not isinstance(feedback_history, list):
            continue
        for idx, record in enumerate(feedback_history):
            if not isinstance(record, dict):
                continue
            text = _normalize_text(record.get("message"))
            if not text:
                continue
            feedback = str(record.get("user_feedback") or "").strip()
            recognized = normalize_intent_label(record.get("recognized_intent"))
            corrected_raw = record.get("corrected_intent")
            corrected = normalize_intent_label(corrected_raw) if corrected_raw else ""
            if feedback == "corrected" and corrected:
                label = corrected
                confidence = 0.98
                status = "approved"
            elif feedback == "confirmed":
                label = recognized
                confidence = 0.9
                status = "approved"
            elif feedback == "negated":
                label = corrected or infer_intent_label(text)
                confidence = 0.55
                status = "candidate"
            else:
                label = corrected or recognized or infer_intent_label(text)
                confidence = 0.6
                status = "candidate"

            samples.append(
                LearningSample(
                    text=text,
                    label=label,
                    source_type="customer_feedback",
                    source_id=f"{user_id}:{record.get('timestamp') or idx}",
                    confidence=confidence,
                    slots=_coerce_dict(record.get("slots")),
                    metadata={
                        "user_id": user_id,
                        "feedback": feedback,
                        "recognized_intent": recognized,
                        "corrected_intent": corrected,
                        "source_path": str(source_path),
                    },
                    evidence={"feedback_record": record},
                    status=status,
                    created_at=str(record.get("timestamp") or _now_iso()),
                )
            )
    return samples


def _default_ticket_roots() -> list[Path]:
    try:
        from app.services.user_cs_change_request import _store_roots
    except ImportError:
        return []
    return [Path(root) for root in _store_roots()]


def collect_change_request_learning(
    ticket_roots: Iterable[str | Path] | None = None,
) -> tuple[list[LearningSample], list[KnowledgeUnit]]:
    """Collect samples and know-how units from customer-service change tickets."""

    roots = [Path(root) for root in ticket_roots] if ticket_roots else _default_ticket_roots()
    samples: list[LearningSample] = []
    units: list[KnowledgeUnit] = []
    for root in roots:
        for row in _load_jsonish_rows(root):
            ticket_id = _normalize_text(row.get("ticket_no") or row.get("id"))
            title = _normalize_text(row.get("title"))
            desc = _normalize_text(row.get("description"))
            admin_note = _normalize_text(row.get("admin_note"))
            text = _row_text(title, desc, admin_note)
            if not text:
                continue
            explicit_label = row.get("label") or row.get("intent") or row.get("corrected_intent")
            label = (
                normalize_intent_label(explicit_label)
                if explicit_label
                else infer_intent_label(text)
            )
            status_raw = str(row.get("status") or "").strip()
            resolved = status_raw in RESOLVED_TICKET_STATUSES
            approved = resolved and explicit_label and label != "unk"
            samples.append(
                LearningSample(
                    text=text,
                    label=label,
                    source_type="production_ticket",
                    source_id=ticket_id or _stable_id(root, title, desc),
                    confidence=0.92 if approved else 0.65,
                    slots=_coerce_dict(row.get("slots")),
                    metadata={
                        "change_type": row.get("change_type"),
                        "status": status_raw,
                        "priority": row.get("priority"),
                        "market_user_id": row.get("market_user_id"),
                        "source_path": str(root),
                        "needs_review": not approved,
                    },
                    evidence={"ticket": row},
                    status="approved" if approved else "candidate",
                    created_at=str(row.get("updated_at") or row.get("created_at") or _now_iso()),
                )
            )
            if row.get("change_type") == "bug_fix" or admin_note:
                units.append(
                    KnowledgeUnit(
                        title=title or "客服变更工单",
                        summary=_row_text(desc, admin_note, max_chars=4000),
                        problem=desc or title,
                        resolution=admin_note,
                        source_type="production_ticket",
                        source_id=ticket_id,
                        domain_tags=[
                            str(row.get("change_type") or ""),
                            label,
                            str(row.get("priority") or ""),
                        ],
                        evidence={"ticket": row},
                        created_at=str(
                            row.get("updated_at") or row.get("created_at") or _now_iso()
                        ),
                    )
                )
    return samples, units


def collect_bug_fix_learning(
    bugfix_path: str | Path | None = None,
) -> tuple[list[LearningSample], list[KnowledgeUnit]]:
    """Collect learning artifacts from structured bug-fix JSON/JSONL files."""

    if not bugfix_path:
        return [], []
    samples: list[LearningSample] = []
    units: list[KnowledgeUnit] = []
    for row in _load_jsonish_rows(bugfix_path):
        title = _normalize_text(row.get("title") or row.get("summary"))
        problem = _row_text(row.get("problem"), row.get("description"), row.get("symptom"))
        resolution = _row_text(row.get("resolution"), row.get("fix"), row.get("root_cause"))
        text = _row_text(title, problem, resolution)
        if not text:
            continue
        explicit_label = row.get("label") or row.get("intent")
        label = (
            normalize_intent_label(explicit_label) if explicit_label else infer_intent_label(text)
        )
        source_id = _normalize_text(
            row.get("source_id") or row.get("issue") or row.get("pr") or row.get("commit")
        )
        approved = bool(resolution and label != "unk")
        samples.append(
            LearningSample(
                text=text,
                label=label,
                source_type="bug_fix",
                source_id=source_id or _stable_id(title, problem, resolution),
                confidence=0.9 if approved else 0.6,
                metadata={
                    "component": row.get("component"),
                    "severity": row.get("severity"),
                    "source_path": str(bugfix_path),
                    "needs_review": not approved,
                },
                evidence={"bug_fix": row},
                status="approved" if approved else "candidate",
                created_at=str(row.get("fixed_at") or row.get("created_at") or _now_iso()),
            )
        )
        units.append(
            KnowledgeUnit(
                title=title or "bug fix",
                summary=_row_text(problem, resolution, max_chars=4000),
                problem=problem,
                resolution=resolution,
                source_type="bug_fix",
                source_id=source_id,
                domain_tags=[
                    label,
                    str(row.get("component") or ""),
                    str(row.get("severity") or ""),
                ],
                evidence={"bug_fix": row},
                created_at=str(row.get("fixed_at") or row.get("created_at") or _now_iso()),
            )
        )
    return samples, units


def collect_distillation_log_samples(
    engine: Any | None = None, *, limit: int = 1000
) -> list[LearningSample]:
    """Collect already persisted distillation_log rows as source-traced samples."""

    if engine is None:
        from app.db import engine as default_engine

        engine = default_engine
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, query, intent, slots, confidence, source, created_at
                    FROM distillation_log
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": int(limit)},
            ).all()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("读取 distillation_log 失败: %s", exc)
        return []

    samples: list[LearningSample] = []
    for row in rows:
        row_map = getattr(row, "_mapping", row)
        confidence = _coerce_float(row_map["confidence"], 0.8)
        samples.append(
            LearningSample(
                text=row_map["query"],
                label=row_map["intent"],
                source_type="distillation_log",
                source_id=str(row_map["id"]),
                confidence=confidence,
                slots=_coerce_dict(row_map["slots"]),
                metadata={
                    "source": row_map["source"],
                    "created_at": str(row_map["created_at"]),
                },
                status="approved" if confidence >= 0.8 else "candidate",
            )
        )
    return samples


def build_continuous_learning_corpus(
    *,
    feedback_path: str | Path | None = None,
    ticket_roots: Iterable[str | Path] | None = None,
    bugfix_path: str | Path | None = None,
    include_defaults: bool = False,
    include_distillation_log: bool = False,
    review_decisions_path: str | Path | None = None,
    min_confidence: float = 0.75,
    distillation_engine: Any | None = None,
) -> ContinuousLearningCorpus:
    """Build a deduplicated, review-gated corpus from operational signals."""

    corpus = ContinuousLearningCorpus(min_confidence=min_confidence)
    if include_distillation_log:
        for sample in collect_distillation_log_samples(distillation_engine):
            corpus.add_sample(sample)
    if include_defaults or feedback_path:
        for sample in collect_user_feedback_samples(feedback_path):
            corpus.add_sample(sample)
    if include_defaults or ticket_roots:
        samples, units = collect_change_request_learning(ticket_roots)
        for sample in samples:
            corpus.add_sample(sample)
        for unit in units:
            corpus.add_knowledge_unit(unit)
    if bugfix_path:
        samples, units = collect_bug_fix_learning(bugfix_path)
        for sample in samples:
            corpus.add_sample(sample)
        for unit in units:
            corpus.add_knowledge_unit(unit)
    corpus.apply_review_decisions(review_decisions_path)
    return corpus


def _read_training_rows(data_path: str | Path | None) -> list[dict[str, Any]]:
    if not data_path:
        return []
    source = Path(data_path)
    if not source.is_file():
        return []
    rows: list[dict[str, Any]] = []
    if source.suffix == ".jsonl":
        with source.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                data = json.loads(line)
                if not isinstance(data, dict):
                    continue
                label = normalize_intent_label(data.get("label"), default="")
                if label not in LABEL_TO_ID:
                    continue
                rows.append(
                    {
                        "text": str(data.get("text", "")),
                        "label": label,
                        "slots": _coerce_dict(data.get("slots")),
                        "source": data.get("source", "base_training_data"),
                    }
                )
    elif source.suffix == ".tsv":
        with source.open(encoding="utf-8") as f:
            next(f, None)
            for raw in f:
                parts = raw.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                label = normalize_intent_label(parts[1], default="")
                if label in LABEL_TO_ID:
                    rows.append(
                        {
                            "text": parts[0],
                            "label": label,
                            "slots": {},
                            "source": "base_training_data",
                        }
                    )
    return rows


def export_continuous_training_data(
    base_data_path: str | Path | None,
    output_path: str | Path,
    corpus: ContinuousLearningCorpus,
    *,
    include_candidates: bool = False,
) -> dict[str, Any]:
    """Merge base data with approved operational samples into one training JSONL."""

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in _read_training_rows(base_data_path):
        key = (_normalize_text(row.get("text")), str(row.get("label")))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    learning_count = 0
    for sample in corpus.trainable_samples(include_candidates=include_candidates):
        key = (_normalize_text(sample.text), sample.label)
        if key in seen:
            continue
        seen.add(key)
        rows.append(sample.to_training_row())
        learning_count += 1
    _write_jsonl(output_path, rows)
    return {
        "output_path": str(output_path),
        "base_rows": len(rows) - learning_count,
        "learning_rows": learning_count,
        "total_rows": len(rows),
        "include_candidates": include_candidates,
    }
