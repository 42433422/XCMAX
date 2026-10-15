"""意图识别评测集跑分（分层棘轮）。

两档口径：
- core：规则引擎已稳定命中的高频明确指令 → 高门槛回归保护（接入 LLM 后一条不许退）。
- semantic：换说法 / 隐式表达 / 口语化 → 当前预期 miss，LLM 分类层上线后的提升目标。

用法：
    python scripts/dev/intent_benchmark.py                 # 跑分 + 写报告
    python scripts/dev/intent_benchmark.py --check         # 棘轮门禁（core 退步即失败）
    python scripts/dev/intent_benchmark.py --llm           # 额外评测 LLM 兜底层
    python scripts/dev/intent_benchmark.py --holdout       # 独立留出集（≥100 条，与回归集零重叠）
    python scripts/dev/intent_benchmark.py --holdout --repeat 3   # 整集跑 3 轮 + 一致率统计
    python scripts/dev/intent_benchmark.py --llm --holdout --repeat 3  # 留出集加测真实 LLM 路由层
    python scripts/dev/intent_benchmark.py --holdout --record     # 建立留出基线（棘轮起点）
    python scripts/dev/intent_benchmark.py --holdout --check      # 留出棘轮：总/逐域准确率只升不降

报告落盘 metrics/intent_benchmark_latest.json；基线 metrics/intent_benchmark_baseline.json。
留出报告落盘 metrics/intent_holdout_latest.json（含逐条结果、混淆矩阵、数据集 sha256）；
留出基线 metrics/intent_holdout_baseline.json。
--llm --holdout 时留出报告追加 llm 块（真实路由层逐轮准确率 + 轮间一致率 + 模型调用证据）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
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
    if case.get("expected_out_of_scope"):
        return not r.get("tool_key") and not r.get("primary_intent")
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
                        for k in (
                            "expected_tool",
                            "expected_primary",
                            "expected_route",
                            "expected_slots",
                            "expect_negated",
                            "check",
                        )
                        if k in case
                    },
                }
            )
    acc = {t: (round(c / n, 4) if n else 0.0) for t, (c, n) in stat.items()}
    return {
        "layer": name,
        "counts": {t: {"correct": c, "total": n} for t, (c, n) in stat.items()},
        "accuracy": acc,
        "failures": dict(failures),
    }


def _predicted_domain(case: dict, r: dict) -> str:
    """把实际路由结果映射回业务域；无法识别归 unknown。"""
    if case.get("check") in ("greeting", "goodbye", "help"):
        return "greeting"
    if case.get("expect_negated"):
        return "rejection" if (r.get("is_negated") or r.get("is_negation_intent")) else "unknown"
    tool = r.get("tool_key") or r.get("primary_intent")
    if not tool:
        return "unknown"
    return TOOL_TO_DOMAIN.get(str(tool), "unknown")


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
    from app.services.intent_service import is_goodbye, is_greeting, recognize_intents

    rows: list[dict] = []
    for case in cases:
        text = case["text"]
        r: dict = {}
        error = None
        ok = False
        try:
            if case.get("check") == "greeting":
                ok = bool(is_greeting(text))
                r = {"tool_key": "greeting" if ok else None}
            elif case.get("check") == "goodbye":
                ok = bool(is_goodbye(text))
                r = {"tool_key": "goodbye" if ok else None}
            elif case.get("check") == "help":
                r = recognize_intents(text)
                ok = bool(r.get("is_help"))
            else:
                r = recognize_intents(text)
                ok = _match_rule(case, text)
        except BOUNDARY_ERRORS as exc:  # 评测隔离边界：单条异常记为 miss，不中断整场评测
            ok = False
            error = type(exc).__name__
        rows.append(
            {
                "text": text,
                "tier": str(case.get("tier", "core")),
                "expected_domain": _expected_domain(case),
                "predicted_domain": _predicted_domain(case, r),
                "got_tool_key": r.get("tool_key"),
                "got_primary": r.get("primary_intent"),
                "correct": ok,
                **({"error": error} if error else {}),
            }
        )
    return rows


def _run_holdout_llm_round(cases: list[dict]) -> list[dict]:
    """留出集单轮 LLM 路由评测：走真实 normal router（含 LLM 意图闸），只看路由结果。"""
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


def _round_agreement(rounds: list[list[dict]], key: str) -> float:
    """轮间一致率：(correct, key) 组合在后续轮与首轮完全一致的比例。"""
    if len(rounds) < 2 or not rounds[0]:
        return 1.0
    first = rounds[0]
    total = len(first) * (len(rounds) - 1)
    same = sum(
        1
        for later in rounds[1:]
        for a, b in zip(first, later, strict=True)
        if (a["correct"], a.get(key)) == (b["correct"], b.get(key))
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
    agreement = 1.0
    if len(rounds) > 1:
        total = len(per_case) * (len(rounds) - 1)
        same = sum(
            1
            for later in rounds[1:]
            for a, b in zip(per_case, later, strict=True)
            if (a["correct"], a["got_tool_key"], a["predicted_domain"])
            == (b["correct"], b["got_tool_key"], b["predicted_domain"])
        )
        agreement = round(same / total, 4) if total else 1.0
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="棘轮门禁模式")
    ap.add_argument("--record", action="store_true", help="把本次跑分写为基线")
    ap.add_argument("--llm", action="store_true", help="同时评测 LLM 兜底层（需平台模型配置）")
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
        not args.llm or not 0 <= args.min_routing_accuracy <= 1
    ):
        ap.error("--min-routing-accuracy requires --llm and a value in [0,1]")

    os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
    sys.path.insert(0, str(REPO))

    output = args.output or (HOLDOUT_LATEST_PATH if args.holdout else LATEST_PATH)

    if args.holdout:
        if args.repeat < 1:
            ap.error("--repeat must be >= 1")
        holdout_cases = _load_cases(HOLDOUT_PATH)
        identity = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        )
        holdout_result = run_holdout(
            holdout_cases,
            repeat=args.repeat,
            dataset_sha256=hashlib.sha256(HOLDOUT_PATH.read_bytes()).hexdigest(),
            source_sha=identity.stdout.strip(),
        )
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
                "measurement_status": (
                    "measured"
                    if evidence["completed"] and not evidence["errors"]
                    else "unavailable_or_partial"
                ),
                "cases": first,
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
        if args.record:
            baseline_payload = {k: v for k, v in holdout_result.items() if k != "cases"}
            if isinstance(baseline_payload.get("llm"), dict):
                baseline_payload["llm"] = {
                    k: v for k, v in baseline_payload["llm"].items() if k != "cases"
                }
            HOLDOUT_BASELINE_PATH.write_text(
                json.dumps(baseline_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"holdout baseline written → {HOLDOUT_BASELINE_PATH}")
        if args.check:
            return _check_holdout_ratchet(holdout_result)
        if args.llm and holdout_result["llm"]["measurement_status"] != "measured":
            print(
                "LLM measurement incomplete: see model_calls; this is not a passing acceptance result"
            )
            return 2
        return 0

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

    _record(result, output)
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
