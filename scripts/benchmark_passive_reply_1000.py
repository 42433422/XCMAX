#!/usr/bin/env python3
"""
被动回复本地基准：默认 1000 条（质量门 / coerce / 长上下文），不调 LLM。

  cd FHD && .venv/bin/python3 scripts/benchmark_passive_reply_1000.py
  ... --count 1000 --json /tmp/passive_bench.json
  ... --llm 5   # 额外抽 5 次真 LLM（慢、计费）
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class CaseResult:
    case_id: int
    kind: str
    expect: str
    ok: bool
    detail: str = ""


@dataclass
class BenchReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    by_kind: Counter = field(default_factory=Counter)
    fail_reasons: Counter = field(default_factory=Counter)
    elapsed_ms: float = 0.0
    context_1000: dict = field(default_factory=dict)
    llm_sample: list = field(default_factory=list)


def _gen_cases(count: int, *, seed: int) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []
    topics = [
        ("合同", "按{n}万先出合同草案，付款想三七开，验收后付尾款"),
        ("方案", "今晚8点前要方案链接，培训要店长+店员两套"),
        ("PPT", "上次PPT作业活动页并进方案，配方部分重点写"),
        ("增项", "金蝶和企微审批增项大概多少，先报个数"),
        ("门店", "下周先上{shop}家店，费用能按店数折算吗"),
        ("预算", "预算{n}万左右，含库存和会员吗"),
        ("交付", "希望{weeks}周内试点上线，合同里写清周期"),
    ]
    good_reply_for = {
        "合同": "好的，按{n}万我先拟合同草案，付款三七开、验收后尾款写进条款。",
        "方案": "好的，今晚8点前发方案链接，培训含店长和店员两套手册。",
        "PPT": "收到，PPT活动页并进方案第三章，配方部分单独写一节。",
        "增项": "金蝶对接约2～3万、企微审批约1～2万，我整理增项表发您。",
        "门店": "可以，先上{shop}家店可按店数折算，我在合同里写清计费方式。",
        "预算": "预算{n}万可做标准版，含库存和基础会员，复杂报表另议。",
        "交付": "好的，{weeks}周试点周期写进合同：前两周确认、中间联调、最后试点。",
    }
    i = 0
    while len(cases) < count:
        topic, inc_tpl = rng.choice(topics)
        n = rng.randint(8, 28)
        shop = rng.randint(2, 12)
        weeks = rng.randint(4, 10)
        inc = inc_tpl.format(n=n, shop=shop, weeks=weeks)
        variant = i % 7
        if variant == 0:
            good = good_reply_for[topic].format(n=n, shop=shop, weeks=weeks)
            cases.append(
                {
                    "kind": "anchor_good",
                    "expect": "pass",
                    "incoming": inc,
                    "reply": good,
                }
            )
        elif variant == 1:
            cases.append(
                {
                    "kind": "anchor_bad_canned",
                    "expect": "fail",
                    "incoming": inc,
                    "reply": "收到您的消息，稍后为您详细回复。",
                }
            )
        elif variant == 2:
            cases.append(
                {
                    "kind": "anchor_bad_echo",
                    "expect": "fail",
                    "incoming": inc,
                    "reply": f'具体词句是："{inc}"',
                }
            )
        elif variant == 3:
            quoted = good_reply_for[topic].format(n=n, shop=shop, weeks=weeks)
            cases.append(
                {
                    "kind": "coerce_mimo_ok",
                    "expect": "pass",
                    "incoming": inc,
                    "raw": f"首先分析用户输入。例如：「{quoted}」",
                }
            )
        elif variant == 4:
            cases.append(
                {
                    "kind": "coerce_chat_log_trap",
                    "expect": "pass",
                    "incoming": inc,
                    "raw": (
                        f"近期群聊：模拟客户: 若下周只能先上{shop}家店\n"
                        f"模拟客户: {inc}\n"
                        f"例如：「{good_reply_for[topic].format(n=n, shop=shop, weeks=weeks)}」"
                    ),
                }
            )
        elif variant == 5:
            cases.append(
                {
                    "kind": "identity_det",
                    "expect": "pass",
                    "incoming": "你们是谁家的",
                    "reply": None,
                }
            )
        else:
            cases.append(
                {
                    "kind": "sanitize_meta",
                    "expect": "fail_or_empty",
                    "incoming": inc,
                    "raw": (
                        "Looking at the user message. 客户的最新消息需要参考近期群聊。"
                        "不要照抄。作为客服已经回复过。"
                    ),
                }
            )
        i += 1
    return cases[:count]


def _run_case(case: dict, case_id: int) -> CaseResult:
    from app.services.wechat_passive_group_monitor import (
        _CHAT_LOG_LINE_RE,
        _coerce_passive_llm_reply_text,
        _collect_passive_reply_quality_issues,
        _reply_addresses_incoming,
        build_deterministic_passive_reply,
        sanitize_passive_group_reply_text,
    )

    kind = str(case.get("kind") or "")
    expect = str(case.get("expect") or "")
    inc = str(case.get("incoming") or "")

    if kind == "identity_det":
        det = build_deterministic_passive_reply(inc, client_name="客户")
        ok = bool(det) and "修茈" in (det or "")
        return CaseResult(case_id, kind, expect, ok, det or "")

    if kind.startswith("coerce_") or kind == "sanitize_meta":
        raw = str(case.get("raw") or "")
        if kind == "sanitize_meta":
            out = sanitize_passive_group_reply_text(raw, client_name="客户")
            ok = not out
            return CaseResult(case_id, kind, expect, ok, (out or "(empty)")[:120])
        out = _coerce_passive_llm_reply_text(raw, client_name="客户", incoming=inc)
        ok = bool(out) and _reply_addresses_incoming(out, inc)
        if ok and _CHAT_LOG_LINE_RE.search(out or ""):
            ok = False
        return CaseResult(case_id, kind, expect, ok, (out or "(empty)")[:120])

    rep = str(case.get("reply") or "")
    issues = _collect_passive_reply_quality_issues(rep, incoming=inc)
    addresses = _reply_addresses_incoming(rep, inc)
    if expect == "pass":
        ok = addresses and not issues
        detail = ";".join(issues) if issues else "ok"
        return CaseResult(case_id, kind, expect, ok, detail)
    ok = (not addresses) or bool(issues)
    detail = f"addr={addresses} issues={issues}"
    return CaseResult(case_id, kind, expect, ok, detail[:120])


def _bench_context_1000() -> dict:
    from app.services.wechat_passive_group_monitor import _passive_recent_context_char_limit

    lines: list[str] = []
    for i in range(1000):
        role = "我" if i % 2 == 0 else "模拟客户"
        lines.append(f"{role}: 第{i}轮讨论条目，涉及方案/合同/付款/门店{i % 20}。")
    full = "\n".join(lines)
    cap = _passive_recent_context_char_limit()
    clipped = full[-cap:] if len(full) > cap else full
    line_count = clipped.count("\n") + 1
    return {
        "message_count": 1000,
        "full_chars": len(full),
        "prompt_cap": cap,
        "clipped_chars": len(clipped),
        "lines_in_prompt": line_count,
        "tail_preview": clipped[-200:].replace("\n", " | "),
    }


def _run_llm_samples(n: int, incoming: str, recent: str) -> list[dict]:
    import asyncio

    from app.services.wechat_passive_group_monitor import build_passive_reply_text

    out: list[dict] = []
    for i in range(n):
        t0 = time.perf_counter()
        try:
            text, src, err = build_passive_reply_text(
                incoming=incoming,
                stage="negotiating",
                client_name="模拟客户",
                group_name="测试专属",
                use_llm=True,
                recent_context=recent,
            )
            ms = (time.perf_counter() - t0) * 1000
            out.append(
                {
                    "i": i + 1,
                    "source": src,
                    "ms": round(ms, 1),
                    "reply": (text or "")[:160],
                    "error": (err or "")[:200],
                }
            )
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            out.append({"i": i + 1, "source": "error", "ms": round(ms, 1), "error": str(exc)[:200]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="被动回复 1000 条本地基准")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", type=str, default="", help="写入 JSON 报告路径")
    parser.add_argument("--llm", type=int, default=0, help="额外真 LLM 抽样次数")
    args = parser.parse_args()

    cases = _gen_cases(args.count, seed=args.seed)
    t0 = time.perf_counter()
    results: list[CaseResult] = []
    for idx, case in enumerate(cases):
        results.append(_run_case(case, idx + 1))

    report = BenchReport()
    report.total = len(results)
    report.elapsed_ms = (time.perf_counter() - t0) * 1000
    report.context_1000 = _bench_context_1000()

    for r in results:
        report.by_kind[r.kind] += 1
        if r.ok:
            report.passed += 1
        else:
            report.failed += 1
            report.fail_reasons[f"{r.kind}:{r.detail[:60]}"] += 1

    if args.llm > 0:
        inc = "按15万先出合同草案吧，付款想三七开，验收后付尾款"
        recent = "\n".join(
            f"{'我' if i % 2 else '模拟客户'}: 长聊第{i}轮"
            for i in range(900, 1000)
        )
        report.llm_sample = _run_llm_samples(args.llm, inc, recent)

    summary = {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "pass_rate": round(report.passed / max(1, report.total) * 100, 2),
        "elapsed_ms": round(report.elapsed_ms, 1),
        "by_kind": dict(report.by_kind),
        "failed_samples": [
            {"id": r.case_id, "kind": r.kind, "detail": r.detail}
            for r in results
            if not r.ok
        ][:30],
        "context_1000": report.context_1000,
        "llm_sample": report.llm_sample,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.json}", file=sys.stderr)

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
