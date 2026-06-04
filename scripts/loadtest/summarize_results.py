#!/usr/bin/env python3
"""汇总 k6 results-load.json 为 GitHub Step Summary 行。

用法：python3 summarize_results.py <results.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def summarize(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    lines: list[str] = []
    metrics = data.get("metrics", {}) or {}

    for name, m in metrics.items():
        values = (m or {}).get("values", {}) or {}
        if not values:
            continue
        line = f"- **{name}**"
        if "avg" in values:
            line += f" avg={values['avg']:.1f}ms"
        if "min" in values:
            line += f" min={values['min']:.1f}ms"
        if "max" in values:
            line += f" max={values['max']:.1f}ms"
        if "p(90)" in values:
            line += f" p90={values['p(90)']:.1f}ms"
        if "p(95)" in values:
            line += f" p95={values['p(95)']:.1f}ms"
        if "p(99)" in values:
            line += f" p99={values['p(99)']:.1f}ms"
        if "rate" in values:
            line += f" rate={values['rate']:.3f}/s"
        if "count" in values:
            line += f" n={int(values['count'])}"
        lines.append(line)

    root = data.get("root_group", {}) or {}
    checks = root.get("checks", []) or []
    failed = [c for c in checks if (c or {}).get("fails")]
    if failed:
        lines.append("")
        lines.append("**Failed checks:**")
        for c in failed:
            lines.append(f"- `{c.get('name', '?')}`: {c.get('fails')} failures")

    return lines


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: summarize_results.py <results.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.exists():
        print(f"results file not found: {path}", file=sys.stderr)
        return 1
    for line in summarize(path):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
