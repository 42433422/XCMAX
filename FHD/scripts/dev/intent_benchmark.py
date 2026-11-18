"""意图识别评测集跑分（分层棘轮）。

两档口径：
- core：规则引擎已稳定命中的高频明确指令 → 高门槛回归保护（接入 LLM 后一条不许退）。
- semantic：换说法 / 隐式表达 / 口语化 → 当前预期 miss，LLM 分类层上线后的提升目标。

用法：
    python scripts/dev/intent_benchmark.py                 # 跑分 + 写报告
    python scripts/dev/intent_benchmark.py --check         # 棘轮门禁（core 退步即失败）
    python scripts/dev/intent_benchmark.py --llm           # 额外评测配置模型的分类能力
    python scripts/dev/intent_benchmark.py --holdout       # 独立留出集（≥100 条，与回归集零重叠）
    python scripts/dev/intent_benchmark.py --holdout --repeat 3   # 整集跑 3 轮 + 一致率统计
    python scripts/dev/intent_benchmark.py --llm --holdout --repeat 3  # 留出集加测配置模型分类（不执行工具）
    python scripts/dev/intent_benchmark.py --holdout --record     # 建立留出基线（棘轮起点）
    python scripts/dev/intent_benchmark.py --holdout --check      # 留出棘轮：总/逐域准确率只升不降

报告落盘 metrics/intent_benchmark_latest.json；基线 metrics/intent_benchmark_baseline.json。
留出报告落盘 metrics/intent_holdout_latest.json（含逐条结果、混淆矩阵、数据集 sha256）；
留出基线 metrics/intent_holdout_baseline.json。
--llm --holdout 时留出报告追加 llm 块（配置模型的旧分类语料逐轮准确率 + 轮间一致率 + 模型调用证据）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
# 直接以脚本执行（python scripts/dev/intent_benchmark.py）时 sys.path 不含 FHD/，
# app 包不可导入；先把仓库根插入 sys.path 再做 app 级导入。
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.utils.operational_errors import BOUNDARY_ERRORS
from scripts.dev.benchmark_evidence import evidence_identity

GOLDEN_PATH = REPO / "tests" / "benchmarks" / "intent_golden_set.json"
HOLDOUT_PATH = REPO / "tests" / "benchmarks" / "intent_holdout_set.json"
METRICS_DIR = REPO / "metrics"
LATEST_PATH = METRICS_DIR / "intent_benchmark_latest.json"
BASELINE_PATH = METRICS_DIR / "intent_benchmark_baseline.json"
HOLDOUT_LATEST_PATH = METRICS_DIR / "intent_holdout_latest.json"
HOLDOUT_BASELINE_PATH = METRICS_DIR / "intent_holdout_baseline.json"

# 棘轮容忍：core 档准确率低于基线超过该值即判定退步。
CORE_TOLERANCE = 0.02

# tool_key → 业务域（混淆矩阵聚合用；留出集 domain 字段口径一致）。
TOOL_TO_DOMAIN = {
    "shipment_generate": "sales",
    "shipments": "shipment",
    "shipment_template": "shipment",
    "shipment_records": "shipment",
    "template_preview": "shipment",
    "template_extract": "shipment",
    "template_query": "shipment",
    "excel_decompose": "data",
    "excel_analyzer": "data",
    "upload_file": "data",
    "products": "products",
    "show_images": "products",
    "show_videos": "products",
    "customers": "customers",
    "customer_list": "customers",
    "customer_edit": "customers",
    "customer_supplement": "customers",
    "customer_export": "reports",
    "materials": "inventory",
    "price_list": "finance",
    "wechat_send": "wechat",
    "wechat": "wechat",
    "print_label": "print",
    "printer_list": "print",
    "settings": "system",
    "business_docking": "system",
    "ai_ecosystem": "system",
    "tools_table": "system",
    "other_tools": "system",
}


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
                "expected_out_of_scope",
                "expected_route",
                "expected_tool",
                "expected_primary",
            )
        ):
            raise ValueError("each benchmark case needs an expected outcome")
    return cases


def match_rule_result(case: dict, result: dict) -> bool:
    """Shared CLI/pytest outcome matcher; empty expectations never pass."""
    from app.domain.shared_services.intent_service import is_write_intent

    check = case.get("check")
    if check in {"greeting", "goodbye", "help"}:
        return bool(result.get(f"is_{check}")) and not result.get("tool_key")
    if case.get("expect_negated"):
        return bool(result.get("is_negated") or result.get("is_negation_intent")) and not (
            is_write_intent(result.get("tool_key"))
        )
    if case.get("expected_out_of_scope"):
        return not any(
            result.get(key)
            for key in (
                "tool_key",
                "primary_intent",
                "is_greeting",
                "is_goodbye",
                "is_help",
                "is_negated",
                "is_negation_intent",
            )
        )
    expected = {
        key: case[expected_key]
        for key, expected_key in (
            ("tool_key", "expected_tool"),
            ("primary_intent", "expected_primary"),
        )
        if case.get(expected_key) is not None
    }
    return bool(expected) and all(result.get(key) == value for key, value in expected.items())


def _match_rule(case: dict, text: str) -> bool:
    from app.domain.shared_services.intent_service import recognize_intents

    return match_rule_result(case, recognize_intents(text))


def _run_layer(name: str, cases: list[dict], matcher, observer) -> dict:
    stat = defaultdict(lambda: [0, 0])
    failures: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        text = case["text"]
        tier = str(case.get("tier", "core"))
        got = {}
        error = None
        try:
            got = observer(text)
            ok = bool(matcher(case, got))
        except BOUNDARY_ERRORS as exc:  # 单条失败记为 miss，不用规则假装模型成功。
            ok = False
            error = type(exc).__name__
        stat[tier][1] += 1
        if ok:
            stat[tier][0] += 1
        else:
            failures[tier].append(
                {
                    **case,
                    "got": got,
                    **({"error": error} if error else {}),
                }
            )
    return {
        "layer": name,
        "counts": {t: {"correct": c, "total": n} for t, (c, n) in stat.items()},
        "accuracy": {t: (round(c / n, 4) if n else 0.0) for t, (c, n) in stat.items()},
        "failures": dict(failures),
    }


def _predicted_domain(result: dict) -> str:
    """Derive predictions only from observed outputs, never expected labels."""
    tool = result.get("tool_key")
    if tool:
        return TOOL_TO_DOMAIN.get(str(tool), "unknown")
    if result.get("is_negated") or result.get("is_negation_intent"):
        return "rejection"
    if any(result.get(f"is_{key}") for key in ("greeting", "goodbye", "help")):
        return "greeting"
    return TOOL_TO_DOMAIN.get(str(result.get("primary_intent")), "unknown")


def _expected_domain(case: dict) -> str:
    return str(case.get("domain") or "unknown")


def build_confusion_matrix(per_case: list[dict]) -> dict[str, dict[str, int]]:
    """expected_domain × predicted_domain 计数矩阵（嵌套 dict，便于 JSON 落盘）。"""
    matrix: dict[str, dict[str, int]] = {}
    for item in per_case:
        row = matrix.setdefault(item["expected_domain"], {})
        row[item["predicted_domain"]] = row.get(item["predicted_domain"], 0) + 1
    return matrix


def _run_holdout_round(cases: list[dict]) -> list[dict]:
    from app.domain.shared_services.intent_service import _intent_cache, recognize_intents

    _intent_cache.clear()  # Each repetition observes the rules, not a previous round cache.
    rows: list[dict] = []
    for case in cases:
        text = case["text"]
        r: dict = {}
        error = None
        ok = False
        try:
            r = recognize_intents(text)
            ok = match_rule_result(case, r)
        except BOUNDARY_ERRORS as exc:  # 评测隔离边界：单条异常记为 miss，不中断整场评测
            ok = False
            error = type(exc).__name__
        rows.append(
            {
                "text": text,
                "tier": str(case.get("tier", "core")),
                "expected_domain": _expected_domain(case),
                "predicted_domain": _predicted_domain(r),
                "got_tool_key": r.get("tool_key"),
                "got_primary": r.get("primary_intent"),
                "correct": ok,
                **({"error": error} if error else {}),
            }
        )
    return rows


def _run_holdout_llm_round(cases: list[dict]) -> list[dict]:
    """Legacy classification corpus against the configured model; no tool execution."""
    from scripts.dev.intent_benchmark_llm import match_prediction, predict

    # 用例间节流：并发任务（acceptance + holdout）同打一个端点时，无间隔的
    # 连续调用会触发 429 限流，导致整轮 0 完成（fail-closed 判 unmeasured）。
    raw_sleep = (os.environ.get("XCAGI_BENCH_LLM_SLEEP") or "1.0").strip()
    try:
        llm_sleep = max(0.0, float(raw_sleep))
    except ValueError:
        llm_sleep = 1.0

    rows: list[dict] = []
    for case in cases:
        text = case["text"]
        got: dict = {}
        error = None
        ok = False
        try:
            got = predict(text)
            ok = bool(match_prediction(case, got))
        except BOUNDARY_ERRORS as exc:  # 评测隔离边界：单条异常记为 miss，不中断整场评测
            ok = False
            error = type(exc).__name__
        if llm_sleep > 0:
            time.sleep(llm_sleep)
        rows.append(
            {
                "text": text,
                "tier": str(case.get("tier", "core")),
                "expected_domain": _expected_domain(case),
                "got_intent": got.get("intent"),
                "correct": ok,
                **({"error": error} if error else {}),
            }
        )
    return rows


def _round_agreement(rounds: list[list[dict]], *keys: str) -> float:
    """轮间一致率：(correct, key) 组合在后续轮与首轮完全一致的比例。"""
    if len(rounds) < 2 or not rounds[0]:
        return 1.0
    first = rounds[0]
    total = len(first) * (len(rounds) - 1)
    same = sum(
        1
        for later in rounds[1:]
        for a, b in zip(first, later, strict=True)
        if all(a.get(key) == b.get(key) for key in ("correct", *keys))
    )
    return round(same / total, 4) if total else 1.0


def _domain_accuracy(rows: list[dict]) -> dict[str, dict]:
    stat: dict[str, list[int]] = {}
    for row in rows:
        entry = stat.setdefault(row["expected_domain"], [0, 0])
        entry[1] += 1
        if row["correct"]:
            entry[0] += 1
    return {
        domain: {
            "correct": c,
            "total": n,
            "accuracy": round(c / n, 4) if n else 0.0,
        }
        for domain, (c, n) in sorted(stat.items())
    }


def run_holdout(
    cases: list[dict], repeat: int = 1, dataset_sha256: str = "", source_sha: str = ""
) -> dict:
    """留出集评测：整集跑 repeat 轮，规则层确定性 → 统计轮间一致率；产出混淆矩阵。"""
    rounds = [_run_holdout_round(cases) for _ in range(max(1, repeat))]
    per_case = rounds[0]
    agreement = _round_agreement(rounds, "got_tool_key", "predicted_domain")
    correct = sum(1 for row in per_case if row["correct"])
    tier_stat: dict[str, list[int]] = {}
    for row in per_case:
        entry = tier_stat.setdefault(row["tier"], [0, 0])
        entry[1] += 1
        if row["correct"]:
            entry[0] += 1
    return {
        "total": len(per_case),
        "source_sha": source_sha,
        "dataset_sha256": dataset_sha256,
        "measured_at": datetime.now(UTC).isoformat(),
        "repeat": len(rounds),
        "round_agreement": agreement,
        "accuracy_overall": round(correct / len(per_case), 4) if per_case else 0.0,
        "accuracy_by_tier": {
            t: round(c / n, 4) if n else 0.0 for t, (c, n) in sorted(tier_stat.items())
        },
        "accuracy_by_domain": _domain_accuracy(per_case),
        "confusion_matrix": build_confusion_matrix(per_case),
        "cases": per_case,
    }


def _check_holdout_ratchet(result: dict) -> int:
    """留出棘轮：总准确率与逐域准确率只升不降（容忍 0）；基线不存在时报错。"""
    if not HOLDOUT_BASELINE_PATH.is_file():
        print("intent-holdout ERROR: 无留出基线，先运行 --holdout --record 建立基线")
        return 1
    base = json.loads(HOLDOUT_BASELINE_PATH.read_text(encoding="utf-8"))
    if base.get("dataset_sha256") != result.get("dataset_sha256"):
        print("intent-holdout ERROR: 留出集已变更（sha256 不一致），需重新 --record 基线")
        return 1
    bad = 0
    b_total, c_total = (
        float(base.get("accuracy_overall", 0.0)),
        float(result.get("accuracy_overall", 0.0)),
    )
    if c_total < b_total:
        print(f"intent-holdout REGRESSION overall: {c_total:.2%} < baseline {b_total:.2%}")
        bad = 1
    base_domains = base.get("accuracy_by_domain", {})
    for domain, cur in result.get("accuracy_by_domain", {}).items():
        b = float(base_domains.get(domain, {}).get("accuracy", 0.0))
        c = float(cur.get("accuracy", 0.0))
        if c < b:
            print(f"intent-holdout REGRESSION domain[{domain}]: {c:.2%} < baseline {b:.2%}")
            bad = 1
    if bad == 0:
        print(f"intent-holdout OK  overall={c_total:.1%}  (n={result.get('total')})")
    return bad


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


def _measurement_status(evidence: dict, expected: int) -> str:
    return (
        "measured"
        if evidence.get("attempted") == evidence.get("completed") == expected > 0
        and not evidence.get("errors")
        else "unavailable_or_partial"
    )


def _model_gate(llm: dict, minimum: float | None) -> int:
    if llm["measurement_status"] != "measured":
        print(
            "LLM measurement incomplete: see model_calls; this is not a passing acceptance result"
        )
        return 2
    if minimum is not None and min(llm["round_accuracy"]) < minimum:
        print(f"Routing acceptance failed: {min(llm['round_accuracy']):.2%} < {minimum:.2%}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    # Both semantic engines must be disabled for reproducible rule-only evidence.
    with patch.dict(
        os.environ,
        {
            "XCAGI_SKIP_INTENT_LLM": "1",
            "FHD_INTENT_SEMANTIC_ENABLED": "0",
            "XCAGI_INTENT_ENGINE": "off",
        },
    ):
        return _main(argv)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="棘轮门禁模式")
    ap.add_argument("--record", action="store_true", help="把本次跑分写为基线")
    ap.add_argument("--llm", action="store_true", help="同时评测配置模型分类（不执行工具）")
    ap.add_argument(
        "--cases", type=Path, default=GOLDEN_PATH, help="独立脱敏留出集（不自动写回基线）"
    )
    ap.add_argument("--holdout", action="store_true", help="评测独立留出集 intent_holdout_set.json")
    ap.add_argument(
        "--repeat", type=int, default=1, help="整集重复跑 N 轮并统计轮间一致率（配合 --holdout）"
    )
    ap.add_argument("--output", type=Path, help="报告落盘路径（默认按模式选 latest 文件）")
    ap.add_argument("--min-routing-accuracy", type=float, help="显式的模型路由验收门槛（0..1）")
    args = ap.parse_args(argv)
    if args.min_routing_accuracy is not None and (
        not args.llm or not 0 < args.min_routing_accuracy <= 1
    ):
        ap.error("--min-routing-accuracy requires --llm and a value in (0,1]")

    output = args.output or (HOLDOUT_LATEST_PATH if args.holdout else LATEST_PATH)

    if args.holdout:
        if args.repeat < 1:
            ap.error("--repeat must be >= 1")
        holdout_cases = _load_cases(HOLDOUT_PATH)
        identity = evidence_identity(
            HOLDOUT_PATH,
            execution_mode="rule_and_model_classification" if args.llm else "rule_only",
        )
        holdout_result = run_holdout(
            holdout_cases,
            repeat=args.repeat,
            dataset_sha256=identity["dataset_sha256"],
            source_sha=identity["source_sha"],
        )
        holdout_result.update(identity)
        if args.llm:
            from scripts.dev.intent_benchmark_llm import observe_model_calls

            with observe_model_calls() as evidence:
                llm_rounds = [_run_holdout_llm_round(holdout_cases) for _ in range(args.repeat)]
            first = llm_rounds[0]
            llm_correct = sum(1 for row in first if row["correct"])
            llm_tiers: dict[str, list[int]] = {}
            for row in first:
                entry = llm_tiers.setdefault(row["tier"], [0, 0])
                entry[1] += 1
                if row["correct"]:
                    entry[0] += 1
            holdout_result["llm"] = {
                "repeat": len(llm_rounds),
                "accuracy_overall": round(llm_correct / len(first), 4) if first else 0.0,
                "accuracy_by_tier": {
                    t: round(c / n, 4) if n else 0.0 for t, (c, n) in sorted(llm_tiers.items())
                },
                "accuracy_by_domain": _domain_accuracy(first),
                "round_agreement": _round_agreement(llm_rounds, "got_intent"),
                "model_calls": evidence,
                "measurement_status": _measurement_status(
                    evidence, len(holdout_cases) * args.repeat
                ),
                "round_accuracy": [
                    sum(row["correct"] for row in rows) / len(rows) for rows in llm_rounds
                ],
                "cases": first,
                "later_rounds": llm_rounds[1:],
            }
        _record(holdout_result, output)
        print(
            f"[holdout] overall={holdout_result['accuracy_overall']:.1%}  "
            f"tiers={holdout_result['accuracy_by_tier']}  "
            f"rounds={holdout_result['repeat']} agreement={holdout_result['round_agreement']:.1%}"
            f"  (n={holdout_result['total']})"
        )
        for domain, stat in holdout_result["accuracy_by_domain"].items():
            print(f"  domain {domain}: {stat['accuracy']:.1%} ({stat['correct']}/{stat['total']})")
        if "llm" in holdout_result:
            llm = holdout_result["llm"]
            print(
                f"[holdout-llm] overall={llm['accuracy_overall']:.1%}  "
                f"rounds={llm['repeat']} agreement={llm['round_agreement']:.1%}  "
                f"status={llm['measurement_status']}  "
                f"model_calls(attempted={llm['model_calls']['attempted']}, "
                f"completed={llm['model_calls']['completed']})"
            )
        print(f"holdout report → {output}")
        if args.llm:
            failure = _model_gate(holdout_result["llm"], args.min_routing_accuracy)
            if failure:
                return failure
        if args.record:
            baseline_payload = {k: v for k, v in holdout_result.items() if k != "cases"}
            if isinstance(baseline_payload.get("llm"), dict):
                baseline_payload["llm"] = {
                    k: v
                    for k, v in baseline_payload["llm"].items()
                    if k not in {"cases", "later_rounds"}
                }
            HOLDOUT_BASELINE_PATH.write_text(
                json.dumps(baseline_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"holdout baseline written → {HOLDOUT_BASELINE_PATH}")
        if args.check:
            return _check_holdout_ratchet(holdout_result)
        return 0

    if args.record and (args.llm or args.cases != GOLDEN_PATH):
        ap.error("--record only accepts the default rule regression set")
    if args.check and args.cases != GOLDEN_PATH:
        ap.error("--check requires the baseline's original dataset")
    cases = _load_cases(args.cases)
    result: dict = {
        "total": len(cases),
        **evidence_identity(
            args.cases, execution_mode="rule_and_model_classification" if args.llm else "rule_only"
        ),
    }
    from app.domain.shared_services.intent_service import recognize_intents

    result["rule"] = _run_layer("rule", cases, match_rule_result, observer=recognize_intents)

    if args.llm:
        from scripts.dev.intent_benchmark_llm import match_prediction, observe_model_calls, predict

        with observe_model_calls() as evidence:
            result["llm"] = _run_layer(
                "configured_model_classification", cases, match_prediction, observer=predict
            )
        result["llm"]["model_calls"] = evidence
        result["llm"]["measurement_status"] = _measurement_status(evidence, len(cases))
        result["llm"]["round_accuracy"] = [
            sum(row["correct"] for row in result["llm"]["counts"].values()) / len(cases)
        ]

    for layer in ("rule", "llm"):
        if layer in result:
            accs = "  ".join(
                f"{t}={result[layer]['accuracy'].get(t, 0):.1%}" for t in ("core", "semantic")
            )
            print(f"[{layer}] {accs}  (n={result[layer]['counts']})")

    _record(result, output)
    if args.llm:
        failure = _model_gate(result["llm"], args.min_routing_accuracy)
        if failure:
            return failure
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
