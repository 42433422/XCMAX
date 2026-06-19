#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标注一致性分析：统计 gold/silver/disputed 比例，检测共同偏差。

读取 ``labeled_data.jsonl``，输出：
- gold/silver/disputed 数量与比例
- 各模型的标签分布
- 共同偏差检测（三模型都 >80% 选 conscious → 保守偏差；都选 reflex → 激进偏差）
- 各 processor 在 gold/silver 子集中的分布

输出为表格 + 偏差警告，可写文件（``--output``）或打印到 stdout。

用法::

    python scripts/dev/analyze_label_consensus.py --help
    python scripts/dev/analyze_label_consensus.py \\
        --input resources/routing_policies/labeled_data.jsonl \\
        --output resources/routing_policies/consensus_report.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

FHD_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = FHD_ROOT / "resources" / "routing_policies" / "labeled_data.jsonl"
DEFAULT_OUTPUT = FHD_ROOT / "resources" / "routing_policies" / "consensus_report.txt"

PROCESSORS = ("reflex", "subconscious", "conscious")
PROVIDERS = ("deepseek", "openai", "qwen")
PROVIDER_DISPLAY = {"deepseek": "DeepSeek-V3", "openai": "GPT-4o", "qwen": "Qwen-Max"}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """简易等宽表格。"""
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    sep = "  ".join("-" * w for w in widths)
    head = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    body = "\n".join(
        "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)) for r in rows
    )
    return f"{head}\n{sep}\n{body}"


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    consensus_counts = Counter(r.get("consensus", "unknown") for r in rows)
    label_counts = Counter(r.get("label", "") for r in rows if r.get("label"))

    # 各模型标签分布
    per_provider: dict[str, Counter] = {p: Counter() for p in PROVIDERS}
    per_provider_available: dict[str, int] = {p: 0 for p in PROVIDERS}
    for r in rows:
        labels = r.get("labels") or {}
        for p in PROVIDERS:
            v = labels.get(p)
            if v is None:
                continue
            per_provider_available[p] += 1
            per_provider[p][v.get("processor", "")] += 1

    # gold/silver 子集中的 processor 分布
    gold_labels = Counter(
        r.get("label") for r in rows if r.get("consensus") == "gold" and r.get("label")
    )
    silver_labels = Counter(
        r.get("label") for r in rows if r.get("consensus") == "silver" and r.get("label")
    )

    # 偏差检测：每个模型选某 processor 的比例
    bias_warnings: list[str] = []
    bias_threshold = 0.8
    for p in PROVIDERS:
        avail = per_provider_available[p]
        if avail == 0:
            continue
        for proc in PROCESSORS:
            ratio = per_provider[p].get(proc, 0) / avail
            if ratio >= bias_threshold:
                if proc == "conscious":
                    bias_warnings.append(
                        f"保守偏差：{PROVIDER_DISPLAY[p]} 有 {ratio:.1%} 样本选 conscious"
                        "（过度倾向高延迟处理器）"
                    )
                elif proc == "reflex":
                    bias_warnings.append(
                        f"激进偏差：{PROVIDER_DISPLAY[p]} 有 {ratio:.1%} 样本选 reflex"
                        "（过度倾向低延迟处理器）"
                    )
                else:
                    bias_warnings.append(
                        f"分布异常：{PROVIDER_DISPLAY[p]} 有 {ratio:.1%} 样本选 {proc}"
                    )

    # 三模型整体共同偏差
    total_valid = sum(per_provider_available.values())
    if total_valid > 0:
        overall = Counter()
        for p in PROVIDERS:
            overall.update(per_provider[p])
        for proc in PROCESSORS:
            ratio = overall.get(proc, 0) / total_valid
            if ratio >= bias_threshold:
                bias_warnings.append(
                    f"共同偏差：三模型合计有 {ratio:.1%} 样本选 {proc}"
                )

    return {
        "total": total,
        "consensus_counts": dict(consensus_counts),
        "label_counts": dict(label_counts),
        "per_provider": {p: dict(c) for p, c in per_provider.items()},
        "per_provider_available": per_provider_available,
        "gold_labels": dict(gold_labels),
        "silver_labels": dict(silver_labels),
        "bias_warnings": bias_warnings,
    }


def render_report(stats: dict[str, Any]) -> str:
    total = stats["total"]
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("NeuroBus LLM 标注一致性报告")
    lines.append("=" * 60)
    lines.append(f"样本总数：{total}")
    if total == 0:
        lines.append("（无样本）")
        return "\n".join(lines)

    cc = stats["consensus_counts"]
    lines.append("")
    lines.append("【一致性分级】")
    consensus_rows: list[list[str]] = []
    for level in ("gold", "silver", "disputed"):
        n = cc.get(level, 0)
        pct = f"{n / total:.1%}" if total else "0.0%"
        consensus_rows.append([level, str(n), pct])
    consensus_rows.append(["合计", str(total), "100.0%"])
    lines.append(_format_table(["级别", "数量", "占比"], consensus_rows))

    lines.append("")
    lines.append("【多数派标签分布】")
    lc = stats["label_counts"]
    label_total = sum(lc.values())
    label_rows: list[list[str]] = []
    for proc in PROCESSORS:
        n = lc.get(proc, 0)
        pct = f"{n / label_total:.1%}" if label_total else "0.0%"
        label_rows.append([proc, str(n), pct])
    label_rows.append(["(空)", str(lc.get("", 0)), "-"])
    lines.append(_format_table(["processor", "数量", "占比"], label_rows))

    lines.append("")
    lines.append("【各模型标签分布】")
    pp = stats["per_provider"]
    ppa = stats["per_provider_available"]
    model_rows: list[list[str]] = []
    for p in PROVIDERS:
        avail = ppa.get(p, 0)
        if avail == 0:
            model_rows.append([PROVIDER_DISPLAY[p], "0", "0", "0", "0"])
            continue
        c = pp.get(p, {})
        model_rows.append(
            [
                PROVIDER_DISPLAY[p],
                str(c.get("reflex", 0)),
                str(c.get("subconscious", 0)),
                str(c.get("conscious", 0)),
                str(avail),
            ]
        )
    lines.append(_format_table(["模型", "reflex", "subconscious", "conscious", "有效样本"], model_rows))

    lines.append("")
    lines.append("【gold/silver 子集 processor 分布】")
    sub_rows: list[list[str]] = []
    gl = stats["gold_labels"]
    sl = stats["silver_labels"]
    for proc in PROCESSORS:
        sub_rows.append([proc, str(gl.get(proc, 0)), str(sl.get(proc, 0))])
    lines.append(_format_table(["processor", "gold", "silver"], sub_rows))

    lines.append("")
    lines.append("【偏差检测】")
    bw = stats["bias_warnings"]
    if not bw:
        lines.append("未检测到共同偏差（阈值 80%）。")
    else:
        for w in bw:
            lines.append(f"⚠ {w}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="标注一致性分析：统计 gold/silver/disputed 比例，检测共同偏差",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="labeled_data.jsonl 路径")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="报告输出路径（默认仅打印 stdout）",
    )
    args = parser.parse_args(argv)

    rows = _load_rows(args.input)
    stats = analyze(rows)
    report = render_report(stats)
    print(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(f"\n[consensus] 报告已写入 {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
