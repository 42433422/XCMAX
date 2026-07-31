"""CLI helpers for distillation continuous learning."""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from app.application.distillation.continuous_learning import (
    CONTINUOUS_LEARNING_DIR,
    CONTINUOUS_TRAINING_DATA_NAME,
    build_continuous_learning_corpus,
    export_continuous_training_data,
)

logger = logging.getLogger(__name__)


def add_learning_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--learn-from-defaults",
        action="store_true",
        help="从默认用户反馈和客服变更工单目录构建持续学习语料",
    )
    parser.add_argument(
        "--learn-from-feedback",
        type=str,
        default=None,
        help="用户反馈 memory JSON",
    )
    parser.add_argument(
        "--learn-from-tickets",
        action="append",
        default=[],
        help="客服/生产工单 JSON 或目录，可重复传入",
    )
    parser.add_argument(
        "--learn-from-bugfixes",
        type=str,
        default=None,
        help="bug 修复 JSON/JSONL",
    )
    parser.add_argument(
        "--learn-from-distillation-log",
        action="store_true",
        help="把数据库 distillation_log 中未外部化的样本纳入候选语料",
    )
    parser.add_argument(
        "--review-decisions",
        type=str,
        default=None,
        help="审核决策 JSON/JSONL",
    )
    parser.add_argument(
        "--learning-output",
        type=str,
        default=None,
        help="持续学习语料和 manifest 输出目录",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.75,
        help="自动进入训练集的最低置信度",
    )
    parser.add_argument(
        "--include-candidates",
        action="store_true",
        help="将候选样本也写入连续训练数据（默认只写 approved）",
    )
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="只生成候选集/审核队列/know-how manifest，不启动模型训练",
    )


def maybe_prepare_continuous_learning(
    args: argparse.Namespace,
    *,
    data_path: str,
) -> tuple[str, dict[str, Any] | None]:
    """Apply learning flags and return updated data_path or early review-only payload."""
    learning_requested = any(
        [
            args.learn_from_defaults,
            args.learn_from_feedback,
            args.learn_from_tickets,
            args.learn_from_bugfixes,
            args.learn_from_distillation_log,
            args.review_decisions,
        ]
    )
    if not learning_requested:
        return data_path, None

    learning_output = args.learning_output or CONTINUOUS_LEARNING_DIR
    corpus = build_continuous_learning_corpus(
        feedback_path=args.learn_from_feedback,
        ticket_roots=args.learn_from_tickets or None,
        bugfix_path=args.learn_from_bugfixes,
        include_defaults=args.learn_from_defaults,
        include_distillation_log=args.learn_from_distillation_log,
        review_decisions_path=args.review_decisions,
        min_confidence=args.min_confidence,
    )
    artifacts = corpus.write_artifacts(learning_output)
    merged_data_path = os.path.join(learning_output, CONTINUOUS_TRAINING_DATA_NAME)
    base_data_path = data_path if os.path.exists(data_path) else None
    merge_stats = export_continuous_training_data(
        base_data_path,
        merged_data_path,
        corpus,
        include_candidates=args.include_candidates,
    )
    logger.info(
        "持续学习语料已生成: samples=%s, knowhow=%s, training_rows=%s",
        corpus.stats()["samples_total"],
        corpus.stats()["knowledge_units_total"],
        merge_stats["total_rows"],
    )
    logger.info("审核队列: %s", artifacts["review_queue"])
    if args.review_only:
        return data_path, {
            "artifacts": artifacts,
            "merge_stats": merge_stats,
            "corpus_stats": corpus.stats(),
        }
    return merged_data_path, None
