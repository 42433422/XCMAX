"""知识库检索质量基线：锁定 69 条评测的召回、拒答与跨库指标。

只在 hash 降级模式下断言（CI 未配置语义模型时即 hash）；配置了 fastembed
的环境跳过，避免把不同向量后端的结果混为一谈。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_EVAL_PATH = Path(__file__).resolve().parents[2] / "scripts/dev/knowledge_retrieval_eval.py"


def _eval_module():
    spec = importlib.util.spec_from_file_location("knowledge_retrieval_eval", _EVAL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def evaluation():
    return _eval_module()


def _require_hash(metrics: dict) -> None:
    if metrics.get("embedding_mode") != "hash":
        pytest.skip(f"语义向量模式 {metrics.get('embedding_mode')} 不适用 hash 基线")


def test_hybrid_baseline_single_dataset(evaluation) -> None:
    metrics = evaluation.run(rerank=False, multi=False)
    _require_hash(metrics)

    assert metrics["recall@1"] >= 0.84
    assert metrics["recall@5"] >= 0.99
    assert metrics["mrr"] >= 0.90
    assert metrics["answer_grounded_rate"] >= 0.99


def test_keyword_mode_baseline(evaluation) -> None:
    metrics = evaluation.run(rerank=False, multi=False, retrieval_mode="keyword")
    _require_hash(metrics)

    assert metrics["recall@1"] >= 0.86
    assert metrics["recall@5"] >= 0.99


def test_hybrid_baseline_multi_dataset(evaluation) -> None:
    metrics = evaluation.run(rerank=False, multi=True)
    _require_hash(metrics)

    assert metrics["datasets"] == 3
    assert metrics["recall@1"] >= 0.84
    assert metrics["recall@5"] >= 0.97


def test_out_of_domain_queries_are_refused(evaluation) -> None:
    single = evaluation.run_ood(multi=False)
    multi = evaluation.run_ood(multi=True)
    _require_hash(single)

    assert single["ood_refused_rate"] == 1.0
    assert multi["ood_refused_rate"] == 1.0
