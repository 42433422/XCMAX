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
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# 直接以脚本执行（python scripts/dev/intent_benchmark.py）时 sys.path 不含 FHD/，
# app 包不可导入；先把仓库根插入 sys.path 再做 app 级导入。
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.utils.operational_errors import BOUNDARY_ERRORS  # noqa: E402

GOLDEN_PATH = REPO / "tests" / "benchmarks" / "intent_golden_set.json"
METRICS_DIR = REPO / "metrics"
LATEST_PATH = METRICS_DIR / "intent_benchmark_latest.json"
BASELINE_PATH = METRICS_DIR / "intent_benchmark_baseline.json"

# 棘轮容忍：core 档准确率低于基线超过该值即判定退步。
CORE_TOLERANCE = 0.02


def _load_cases(path: Path = GOLDEN_PATH) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("golden set must be a non-empty list")
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("text"), str):
            raise ValueError("each benchmark case needs text")
        if not any(
            case.get(key)
            for key in (
                "check",
                "expect_negated",
                "expected_route",
                "expected_tool",
                "expected_primary",
            )
        ):
            raise ValueError("each benchmark case needs an expected outcome")
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
    if exp_tool is None and exp_primary is None:
        return False
    if exp_tool is not None and r.get("tool_key") != exp_tool:
        return False
    if exp_primary is not None and r.get("primary_intent") != exp_primary:
        return False
    return True


def _run_layer(name: str, cases: list[dict], matcher, observer=None) -> dict:
    stat = defaultdict(lambda: [0, 0])
    failures: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        text = case["text"]
        tier = str(case.get("tier", "core"))
        got = {}
        error = None
        try:
            if observer is not None:
                got = observer(text)
                ok = bool(matcher(case, got))
            else:
                ok = bool(matcher(case, text))
        except BOUNDARY_ERRORS as exc:  # 评测隔离边界：单条异常记为 miss，不中断整场评测
            ok = False
            error = type(exc).__name__
        stat[tier][1] += 1
        if ok:
            stat[tier][0] += 1
        else:
            try:
                from app.services.intent_service import recognize_intents

                if observer is None:
                    r = recognize_intents(text)
                    got = {"tool_key": r.get("tool_key"), "primary_intent": r.get("primary_intent")}
            except BOUNDARY_ERRORS:  # 评测隔离边界：对照组失败记为空观测
                pass
            failures[tier].append(
                {
                    "text": text,
                    "got": got,
                    **({"error": error} if error else {}),
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


def _record(result: dict, path: Path = LATEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


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
    ap.add_argument(
        "--cases", type=Path, default=GOLDEN_PATH, help="独立脱敏留出集（不自动写回基线）"
    )
    ap.add_argument("--output", type=Path, default=LATEST_PATH)
    ap.add_argument("--min-routing-accuracy", type=float, help="显式的模型路由验收门槛（0..1）")
    args = ap.parse_args(argv)
    if args.min_routing_accuracy is not None and (
        not args.llm or not 0 <= args.min_routing_accuracy <= 1
    ):
        ap.error("--min-routing-accuracy requires --llm and a value in [0,1]")

    os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
    sys.path.insert(0, str(REPO))

    if args.record and (args.llm or args.cases != GOLDEN_PATH):
        ap.error("--record only accepts the default rule regression set")
    if args.check and args.cases != GOLDEN_PATH:
        ap.error("--check requires the baseline's original dataset")
    cases = _load_cases(args.cases)
    identity = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    )
    result: dict = {
        "total": len(cases),
        "source_sha": identity.stdout.strip(),
        "dataset_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "measured_at": datetime.now(UTC).isoformat(),
    }
    result["rule"] = _run_layer("rule", cases, _match_rule)

    if args.llm:
        from scripts.dev.intent_benchmark_llm import match_prediction, observe_model_calls, predict

        with observe_model_calls() as evidence:
            result["llm"] = _run_layer(
                "normal_router_with_llm", cases, match_prediction, observer=predict
            )
        result["llm"]["model_calls"] = evidence
        result["llm"]["measurement_status"] = (
            "measured"
            if evidence["completed"] and not evidence["errors"]
            else "unavailable_or_partial"
        )

    for layer in ("rule", "llm"):
        if layer in result:
            accs = "  ".join(
                f"{t}={result[layer]['accuracy'].get(t, 0):.1%}" for t in ("core", "semantic")
            )
            print(f"[{layer}] {accs}  (n={result[layer]['counts']})")

    _record(result, args.output)
    if args.llm and result["llm"]["measurement_status"] != "measured":
        print(
            "LLM measurement incomplete: see model_calls; this is not a passing acceptance result"
        )
        return 2
    if args.min_routing_accuracy is not None:
        counts = result["llm"]["counts"].values()
        correct = sum(item["correct"] for item in counts)
        accuracy = correct / len(cases)
        if accuracy < args.min_routing_accuracy:
            print(f"Routing acceptance failed: {accuracy:.2%} < {args.min_routing_accuracy:.2%}")
            return 1
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
