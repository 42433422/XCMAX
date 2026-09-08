"""
意图识别 golden set 基准（可复现 README / 营销声称中的准确率数字）。

分档口径（tier 字段，缺省视为 core）：
- core：规则引擎已稳定命中的高频明确指令 → 硬门禁，默认 ≥95%（INTENT_BENCHMARK_MIN_ACCURACY）。
- semantic：换说法 / 隐式表达 / 口语化 → 规则引擎预期 miss，由 LLM 意图闸兜底；
  仅测量并写入报告，除非显式设置 INTENT_BENCHMARK_MIN_ACCURACY_SEMANTIC。

若需验证「99%+」营销口径，在 workflow_dispatch 时设置 INTENT_BENCHMARK_MIN_ACCURACY=0.99。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

GOLDEN_PATH = Path(__file__).with_name("intent_golden_set.json")
REPORT_DIR = Path(__file__).resolve().parents[2] / "test_reports"


def _load_golden() -> list[dict]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) >= 10
    return data


def _match_case(result: dict, case: dict, text: str) -> bool:
    check = case.get("check")
    if check == "greeting":
        from app.services.intent_service import is_greeting

        return is_greeting(text)
    if check == "goodbye":
        from app.services.intent_service import is_goodbye

        return is_goodbye(text)

    exp_tool = case.get("expected_tool")
    exp_primary = case.get("expected_primary")
    tool = result.get("tool_key")
    primary = result.get("primary_intent")
    if exp_tool is not None and tool != exp_tool:
        return False
    if exp_primary is not None and primary != exp_primary:
        return False
    return True


@pytest.fixture(scope="module")
def golden_cases():
    os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
    return _load_golden()


@pytest.mark.skipif(
    not os.environ.get("INTENT_BENCHMARK_RUN", "").strip(),
    reason="需要完整意图栈/DB；本地设 INTENT_BENCHMARK_RUN=1 再跑（见 intent-benchmark.yml）",
)
def test_intent_golden_set_accuracy(golden_cases):
    from app.services.intent_service import recognize_intents

    correct = 0
    failures: list[dict] = []
    tier_stat: dict[str, list[int]] = {}
    tier_failures: dict[str, list[dict]] = {}
    for case in golden_cases:
        text = case["text"]
        tier = str(case.get("tier", "core"))
        result = recognize_intents(text)
        if _match_case(result, case, text):
            correct += 1
            tier_stat.setdefault(tier, [0, 0])[0] += 1
        else:
            failure = {
                "text": text,
                "expected_tool": case.get("expected_tool"),
                "expected_primary": case.get("expected_primary"),
                "got_tool": result.get("tool_key"),
                "got_primary": result.get("primary_intent"),
            }
            failures.append(failure)
            tier_stat.setdefault(tier, [0, 0])[1] += 1
            tier_failures.setdefault(tier, []).append(failure)

    accuracy = correct / len(golden_cases)
    min_acc = float(os.environ.get("INTENT_BENCHMARK_MIN_ACCURACY", "0.95"))
    min_acc_semantic = os.environ.get("INTENT_BENCHMARK_MIN_ACCURACY_SEMANTIC")

    tier_accuracy = {
        tier: round(hit / (hit + miss), 4) if (hit + miss) else 0.0
        for tier, (hit, miss) in tier_stat.items()
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "total": len(golden_cases),
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "min_required": min_acc,
        "tier_accuracy": tier_accuracy,
        "failures": failures[:20],
    }
    (REPORT_DIR / "intent_benchmark_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    core_n = sum(tier_stat.get("core", [0, 0]))
    core_hit = tier_stat.get("core", [0, 0])[0]
    core_acc = (core_hit / core_n) if core_n else 0.0
    assert core_acc >= min_acc, (
        f"Intent core accuracy {core_acc:.2%} below threshold {min_acc:.2%}; "
        f"failures sample: {tier_failures.get('core', failures)[:3]}"
    )
    if min_acc_semantic is not None:
        sem_hit, sem_miss = tier_stat.get("semantic", [0, 0])
        sem_acc = (sem_hit / (sem_hit + sem_miss)) if (sem_hit + sem_miss) else 0.0
        assert sem_acc >= float(min_acc_semantic), (
            f"Intent semantic accuracy {sem_acc:.2%} below threshold {min_acc_semantic}; "
            f"failures sample: {tier_failures.get('semantic', [])[:3]}"
        )
