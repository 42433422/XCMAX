"""Tests for the continuous-learning layer in distillation_trainer."""

from __future__ import annotations

import json
from unittest.mock import patch

from app.application.distillation.continuous_learning import (
    ContinuousLearningCorpus,
    LearningSample,
    build_continuous_learning_corpus,
    export_continuous_training_data,
)
from app.application.distillation.continuous_learning_collectors import (
    collect_bug_fix_learning,
    collect_change_request_learning,
    collect_user_feedback_samples,
)
from app.application.distillation.continuous_learning_models import INTENT_LABELS
from app.services.bert_intent_service import INTENT_LABELS as RUNTIME_INTENT_LABELS
from app.services.distillation_trainer import main


def _read_jsonl(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_label_set_aligns_with_runtime_bert_service():
    assert INTENT_LABELS == RUNTIME_INTENT_LABELS
    assert len(INTENT_LABELS) >= 28
    assert "business_docking" in INTENT_LABELS


def test_collect_user_feedback_samples_approves_confirmed_and_corrected(tmp_path):
    memory_path = tmp_path / "memory_store.json"
    memory_path.write_text(
        json.dumps(
            {
                "u1": {
                    "feedback_history": [
                        {
                            "timestamp": "2026-07-29T10:00:00",
                            "message": "查客户列表",
                            "recognized_intent": "customers",
                            "user_feedback": "confirmed",
                        },
                        {
                            "timestamp": "2026-07-29T10:01:00",
                            "message": "导出客户表",
                            "recognized_intent": "upload_file",
                            "corrected_intent": "customer_export",
                            "user_feedback": "corrected",
                        },
                        {
                            "timestamp": "2026-07-29T10:02:00",
                            "message": "不要打印标签",
                            "recognized_intent": "print_label",
                            "user_feedback": "negated",
                        },
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    samples = collect_user_feedback_samples(memory_path)
    by_text = {sample.text: sample for sample in samples}

    assert by_text["查客户列表"].status == "approved"
    assert by_text["查客户列表"].label == "customers"
    assert by_text["导出客户表"].status == "approved"
    assert by_text["导出客户表"].label == "customer_export"
    assert by_text["不要打印标签"].status == "candidate"
    assert by_text["不要打印标签"].label == "negation"


def test_collect_change_requests_produces_review_samples_and_knowhow(tmp_path):
    ticket_dir = tmp_path / "tickets"
    ticket_dir.mkdir()
    (ticket_dir / "100.json").write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "id": "a1",
                        "ticket_no": "CR-100-0001",
                        "change_type": "bug_fix",
                        "title": "打印标签偏移",
                        "description": "客户反馈标签位置错位",
                        "admin_note": "修复打印偏移参数",
                        "status": "closed",
                        "label": "print_label",
                        "priority": "high",
                    },
                    {
                        "id": "a2",
                        "ticket_no": "CR-100-0002",
                        "change_type": "feature_request",
                        "title": "希望做 ERP 对接",
                        "description": "客户资料需要从外部 ERP 同步",
                        "status": "pending",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    samples, units = collect_change_request_learning([ticket_dir])
    by_source = {sample.source_id: sample for sample in samples}

    assert by_source["CR-100-0001"].status == "approved"
    assert by_source["CR-100-0001"].label == "print_label"
    assert by_source["CR-100-0002"].status == "candidate"
    assert by_source["CR-100-0002"].label == "business_docking"
    assert len(units) == 1
    assert units[0].resolution == "修复打印偏移参数"
    assert "bug_fix" in units[0].domain_tags


def test_bug_fix_learning_and_training_export_are_review_gated(tmp_path):
    bugfix_path = tmp_path / "bugfixes.jsonl"
    bugfix_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "source_id": "PR-9",
                        "title": "发货记录查询 500",
                        "problem": "客户打开出货记录时报错",
                        "root_cause": "查询字段缺失",
                        "fix": "补齐 shipment_records 查询字段",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "source_id": "PR-10",
                        "title": "未知问题",
                        "problem": "只有模糊描述",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    samples, units = collect_bug_fix_learning(bugfix_path)
    corpus = ContinuousLearningCorpus(min_confidence=0.75)
    for sample in samples:
        corpus.add_sample(sample)
    for unit in units:
        corpus.add_knowledge_unit(unit)

    base_path = tmp_path / "base.jsonl"
    base_path.write_text(
        json.dumps({"text": "你好", "label": "greet"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "training.jsonl"
    stats = export_continuous_training_data(base_path, output_path, corpus)
    rows = _read_jsonl(output_path)

    assert stats["base_rows"] == 1
    assert stats["learning_rows"] == 1
    assert [row["label"] for row in rows] == ["greet", "shipment_records"]
    assert corpus.stats()["knowledge_units_total"] == 2


def test_corpus_review_decisions_and_artifacts(tmp_path):
    corpus = ContinuousLearningCorpus(min_confidence=0.75)
    sample = LearningSample(
        text="发微信给客户",
        label="wechat_send",
        source_type="production_ticket",
        source_id="CR-1",
        confidence=0.65,
        status="candidate",
    )
    corpus.add_sample(sample)
    decisions_path = tmp_path / "review.jsonl"
    decisions_path.write_text(
        json.dumps(
            {
                "sample_id": sample.sample_id,
                "status": "approved",
                "reviewer": "ops",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    assert corpus.apply_review_decisions(decisions_path) == 1
    assert corpus.samples[sample.sample_id].status == "approved"

    paths = corpus.write_artifacts(tmp_path / "learning")
    assert _read_jsonl(tmp_path / "learning" / "approved_samples.jsonl")[0]["trainable"] is True
    manifest = json.loads((tmp_path / "learning" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["stats"]["trainable_total"] == 1
    assert paths["review_queue"].endswith("review_queue.jsonl")


def test_main_review_only_builds_learning_corpus_without_training(tmp_path):
    memory_path = tmp_path / "memory_store.json"
    memory_path.write_text(
        json.dumps(
            {
                "u1": {
                    "feedback_history": [
                        {
                            "timestamp": "2026-07-29T10:00:00",
                            "message": "查客户",
                            "recognized_intent": "customers",
                            "user_feedback": "confirmed",
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "learning"
    missing_base = tmp_path / "missing.jsonl"

    with (
        patch(
            "sys.argv",
            [
                "distillation_trainer",
                "--data",
                str(missing_base),
                "--learn-from-feedback",
                str(memory_path),
                "--learning-output",
                str(out_dir),
                "--review-only",
            ],
        ),
        patch("app.services.distillation_trainer.DistillationTrainer") as mock_trainer,
    ):
        result = main()

    assert result["merge_stats"]["total_rows"] == 1
    assert result["corpus_stats"]["trainable_total"] == 1
    assert (out_dir / "training_data.continuous.jsonl").exists()
    mock_trainer.assert_not_called()


def test_build_continuous_learning_corpus_combines_sources(tmp_path):
    feedback_path = tmp_path / "memory.json"
    feedback_path.write_text(
        json.dumps(
            {
                "u1": {
                    "feedback_history": [
                        {
                            "message": "系统设置在哪",
                            "recognized_intent": "settings",
                            "user_feedback": "confirmed",
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "app.application.distillation.continuous_learning_collectors.collect_distillation_log_samples",
            return_value=[
                LearningSample(
                    text="模板预览",
                    label="template_preview",
                    source_type="distillation_log",
                    source_id="1",
                    status="approved",
                )
            ],
        ),
        patch(
            "app.application.distillation.continuous_learning_collectors.collect_change_request_learning",
            return_value=([], []),
        ),
        patch(
            "app.application.distillation.continuous_learning_collectors.collect_bug_fix_learning",
            return_value=([], []),
        ),
    ):
        corpus = build_continuous_learning_corpus(
            feedback_path=feedback_path,
            include_distillation_log=True,
        )

    assert corpus.stats()["by_source"] == {
        "customer_feedback": 1,
        "distillation_log": 1,
    }
    assert corpus.stats()["trainable_total"] == 2
