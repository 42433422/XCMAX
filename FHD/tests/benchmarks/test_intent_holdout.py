"""留出评测集（intent_holdout_set.json）与混淆矩阵的独立校验。

审计口径：现有 97 条回归集不是独立留出集；留出集必须与回归集输入文本零重叠、
覆盖 8+ 业务域各 ≥10 条、拒绝/安全与域外各 ≥10 条，供 --holdout 棘轮量化差距。
"""

from __future__ import annotations

import json

import pytest

from scripts.dev import intent_benchmark as runner

HOLDOUT_PATH = runner.HOLDOUT_PATH
GOLDEN_PATH = runner.GOLDEN_PATH

# 每域最少条数（审计关闭条件：8 业务域 + 拒绝/安全 + 域外各 ≥10）
MIN_PER_DOMAIN = 10
MIN_TOTAL = 100


@pytest.fixture(scope="module")
def holdout_cases() -> list[dict]:
    return json.loads(HOLDOUT_PATH.read_text(encoding="utf-8"))


def test_holdout_loads_with_benchmark_schema(holdout_cases):
    """留出集必须能通过跑分脚本自身的 schema 校验（复用匹配器口径）。"""
    assert runner._load_cases(HOLDOUT_PATH) == holdout_cases


def test_holdout_meets_minimum_size(holdout_cases):
    assert len(holdout_cases) >= MIN_TOTAL


def test_holdout_every_case_has_domain_and_expected(holdout_cases):
    for case in holdout_cases:
        assert isinstance(case.get("domain"), str) and case["domain"], f"missing domain: {case}"
        assert any(
            case.get(key)
            for key in (
                "check",
                "expect_negated",
                "expected_out_of_scope",
                "expected_tool",
                "expected_primary",
            )
        ), f"missing expected outcome: {case}"
        assert isinstance(case.get("text"), str) and case["text"].strip()


def test_holdout_domain_coverage(holdout_cases):
    from collections import Counter

    counts = Counter(case["domain"] for case in holdout_cases)
    required = {
        "customers",
        "products",
        "sales",
        "inventory",
        "finance",
        "reports",
        "shipment",
        "rejection",
        "out_of_scope",
    }
    missing = required - set(counts)
    assert not missing, f"holdout set missing domains: {missing}"
    for domain, n in counts.items():
        assert n >= MIN_PER_DOMAIN, f"domain {domain} has only {n} cases (< {MIN_PER_DOMAIN})"


def test_holdout_negative_cases_minimum(holdout_cases):
    negative = [c for c in holdout_cases if c["domain"] in ("rejection", "out_of_scope")]
    assert len(negative) >= 2 * MIN_PER_DOMAIN


def test_holdout_zero_overlap_with_golden_set(holdout_cases):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    golden_texts = {case["text"] for case in golden}
    holdout_texts = {case["text"] for case in holdout_cases}
    overlap = golden_texts & holdout_texts
    assert not overlap, f"holdout must not reuse golden set inputs: {overlap}"
    assert len(holdout_texts) == len(holdout_cases), "holdout texts must be unique"


def test_build_confusion_matrix_counts_expected_predicted():
    per_case = [
        {"expected_domain": "customers", "predicted_domain": "customers"},
        {"expected_domain": "customers", "predicted_domain": "unknown"},
        {"expected_domain": "customers", "predicted_domain": "sales"},
        {"expected_domain": "sales", "predicted_domain": "customers"},
        {"expected_domain": "out_of_scope", "predicted_domain": "unknown"},
    ]
    matrix = runner.build_confusion_matrix(per_case)
    assert matrix["customers"] == {"customers": 1, "unknown": 1, "sales": 1}
    assert matrix["sales"] == {"customers": 1}
    assert matrix["out_of_scope"] == {"unknown": 1}


def test_predicted_domain_mapping():
    assert runner._predicted_domain({}, {"tool_key": "materials"}) == "inventory"
    assert runner._predicted_domain({}, {"tool_key": "shipment_generate"}) == "sales"
    assert runner._predicted_domain({}, {"tool_key": None, "primary_intent": None}) == "unknown"
    assert runner._predicted_domain({}, {"tool_key": "nonexistent_tool"}) == "unknown"
    assert runner._predicted_domain({"check": "greeting"}, {"tool_key": None}) == "greeting"
    assert runner._predicted_domain({"expect_negated": True}, {"is_negated": True}) == "rejection"
    assert runner._predicted_domain({"expect_negated": True}, {}) == "unknown"


def test_domain_accuracy_and_round_agreement():
    cases = [
        {"text": "客户名册", "domain": "customers", "expected_tool": "customers"},
        {"text": "碳酸钙还剩多少", "domain": "inventory", "expected_tool": "materials"},
    ]
    result = runner.run_holdout(cases, repeat=3, dataset_sha256="abc", source_sha="def")
    assert result["total"] == 2
    assert result["repeat"] == 3
    assert result["round_agreement"] == 1.0  # 规则层确定性：轮间必须完全一致
    assert result["dataset_sha256"] == "abc"
    assert result["confusion_matrix"]
    assert set(result["accuracy_by_domain"]) == {"customers", "inventory"}


def test_holdout_out_of_scope_matches_unrouted_text():
    case = {"text": "月亮离地球有多远", "domain": "out_of_scope", "expected_out_of_scope": True}
    assert runner._match_rule(case, case["text"]) is True
    wrong = {"text": "查询库存", "domain": "inventory", "expected_out_of_scope": True}
    assert runner._match_rule(wrong, wrong["text"]) is False


def test_holdout_ratchet_requires_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "HOLDOUT_BASELINE_PATH", tmp_path / "missing.json")
    assert runner._check_holdout_ratchet({"accuracy_overall": 0.5}) == 1


def test_holdout_ratchet_blocks_regression(monkeypatch, tmp_path):
    baseline = tmp_path / "holdout_baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "dataset_sha256": "sha-x",
                "accuracy_overall": 0.60,
                "accuracy_by_domain": {
                    "customers": {"accuracy": 0.8, "correct": 8, "total": 10},
                    "sales": {"accuracy": 0.5, "correct": 5, "total": 10},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "HOLDOUT_BASELINE_PATH", baseline)
    current = {
        "dataset_sha256": "sha-x",
        "total": 20,
        "accuracy_overall": 0.65,  # 总体升了
        "accuracy_by_domain": {
            "customers": {"accuracy": 0.7, "correct": 7, "total": 10},  # 但 customers 域退步
            "sales": {"accuracy": 0.6, "correct": 6, "total": 10},
        },
    }
    assert runner._check_holdout_ratchet(current) == 1
    current_ok = json.loads(json.dumps(current))
    current_ok["accuracy_by_domain"]["customers"]["accuracy"] = 0.9
    current_ok["accuracy_by_domain"]["customers"]["correct"] = 9
    assert runner._check_holdout_ratchet(current_ok) == 0


def test_holdout_ratchet_blocks_dataset_drift(monkeypatch, tmp_path):
    baseline = tmp_path / "holdout_baseline.json"
    baseline.write_text(
        json.dumps(
            {"dataset_sha256": "sha-old", "accuracy_overall": 0.1, "accuracy_by_domain": {}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "HOLDOUT_BASELINE_PATH", baseline)
    assert runner._check_holdout_ratchet({"dataset_sha256": "sha-new"}) == 1
