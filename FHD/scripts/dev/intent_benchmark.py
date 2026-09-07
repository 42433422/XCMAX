"""意图识别评测集跑分（分层棘轮）。

两档口径：
- core：规则引擎已稳定命中的高频明确指令 → 高门槛回归保护（接入 LLM 后一条不许退）。
- semantic：换说法 / 隐式表达 / 口语化 → 当前预期 miss，LLM 分类层上线后的提升目标。

用法：
    python scripts/dev/intent_benchmark.py                 # 跑分 + 写报告
    python scripts/dev/intent_benchmark.py --check         # 棘轮门禁（core 退步即失败）
    python scripts/dev/intent_benchmark.py --llm           # 额外评测 LLM 兜底层

报告落盘 metrics/intent_benchmark_latest.json；基线 metrics/intent_benchmark_baseline.json。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GOLDEN_PATH = REPO / "tests" / "benchmarks" / "intent_golden_set.json"
METRICS_DIR = REPO / "metrics"
LATEST_PATH = METRICS_DIR / "intent_benchmark_latest.json"
BASELINE_PATH = METRICS_DIR / "intent_benchmark_baseline.json"

# 棘轮容忍：core 档准确率低于基线超过该值即判定退步。
CORE_TOLERANCE = 0.02


def _load_cases() -> list[dict]:
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(cases, list) and len(cases) >= 50, "golden set 规模异常"
    return cases


def _match_rule(case: dict, text: str) -> bool:
    from app.services.intent_service import is_goodbye, is_greeting, recognize_intents

    if case.get("check") == "greeting":
        return bool(is_greeting(text))
    if case.get("check") == "goodbye":
        return bool(is_goodbye(text))
    if case.get("check") == "help":
        return bool(recognize_intents(text).get("is_help"))
    r = recognize_intents(text)
    if case.get("expect_negated"):
        return bool(r.get("is_negated") or r.get("is_negation_intent"))
    exp_tool = case.get("expected_tool")
    exp_primary = case.get("expected_primary")
    if exp_tool is not None and r.get("tool_key") != exp_tool:
        return False
    if exp_primary is not None and r.get("primary_intent") != exp_primary:
        return False
    return True


def _run_layer(name: str, cases: list[dict], matcher) -> dict:
    stat = defaultdict(lambda: [0, 0])
    failures: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        text = case["text"]
        tier = str(case.get("tier", "core"))
        try:
            ok = bool(matcher(case, text))
        except Exception as exc:  # noqa: BLE001 - 评测层单条异常记为 miss
            ok = False
            failures[tier].append({"text": text, "error": str(exc)[:120]})
        stat[tier][1] += 1
        if ok:
            stat[tier][0] += 1
        else:
            got = {}
            try:
                from app.services.intent_service import recognize_intents

                r = recognize_intents(text)
                got = {"tool_key": r.get("tool_key"), "primary_intent": r.get("primary_intent")}
            except Exception:  # noqa: BLE001
                pass
            failures[tier].append(
                {
                    "text": text,
                    "got": got,
                    **{
                        k: case.get(k)
                        for k in ("expected_tool", "expected_primary", "check")
                        if case.get(k)
                    },
                }
            )
    acc = {t: (round(c / n, 4) if n else 0.0) for t, (c, n) in stat.items()}
    return {
        "layer": name,
        "counts": {t: {"correct": c, "total": n} for t, (c, n) in stat.items()},
        "accuracy": acc,
        "failures": {t: f[:30] for t, f in failures.items()},
    }


def _record(result: dict) -> None:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_ratchet(result: dict) -> int:
    """core 档棘轮：低于基线 - 容忍即失败。semantic 只升不降（有基线时）。"""
    if not BASELINE_PATH.is_file():
        print("intent-benchmark: 无基线，跳过棘轮（先 --record 建基线）")
        return 0
    base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    base_acc = base.get("rule", {}).get("accuracy", {})
    cur_acc = result.get("rule", {}).get("accuracy", {})
    bad = 0
    for tier in ("core", "semantic"):
        b, c = float(base_acc.get(tier, 0.0)), float(cur_acc.get(tier, 0.0))
        tol = CORE_TOLERANCE if tier == "core" else 0.0
        if c < b - tol:
            print(f"intent-benchmark REGRESSION {tier}: {c:.2%} < baseline {b:.2%}")
            bad = 1
    if bad == 0:
        print(
            "intent-benchmark OK  "
            + "  ".join(f"{t}={cur_acc.get(t, 0):.1%}" for t in ("core", "semantic"))
        )
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="棘轮门禁模式")
    ap.add_argument("--record", action="store_true", help="把本次跑分写为基线")
    ap.add_argument("--llm", action="store_true", help="同时评测 LLM 兜底层（需平台模型配置）")
    args = ap.parse_args(argv)

    os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
    sys.path.insert(0, str(REPO))

    cases = _load_cases()
    result: dict = {"total": len(cases)}
    result["rule"] = _run_layer("rule", cases, _match_rule)

    if args.llm:
        from scripts.dev.intent_benchmark_llm import match_llm  # type: ignore[import-not-found]

        result["llm"] = _run_layer("llm", cases, match_llm)

    for layer in ("rule", "llm"):
        if layer in result:
            accs = "  ".join(
                f"{t}={result[layer]['accuracy'].get(t, 0):.1%}" for t in ("core", "semantic")
            )
            print(f"[{layer}] {accs}  (n={result[layer]['counts']})")

    _record(result)
    if args.record:
        BASELINE_PATH.write_text(
            json.dumps(
                {k: v for k, v in result.items() if k != "failures"}
                | {
                    "rule": {**result["rule"], "failures": "omitted"},
                    **(
                        {"llm": {**result["llm"], "failures": "omitted"}} if "llm" in result else {}
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"baseline written → {BASELINE_PATH}")
    if args.check:
        return _check_ratchet(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
