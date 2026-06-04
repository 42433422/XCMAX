#!/usr/bin/env python3
"""Rank app/*.py files by uncovered line count for COVERAGE_RAMP iterations.

Reads coverage.py JSON (format 3) or falls back to Cobertura XML (coverage-full.xml).
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rank_from_json(path: Path, *, top: int, prefix: str) -> list[tuple[int, str, float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[tuple[int, str, float]] = []
    for file_path, info in data.get("files", {}).items():
        if not file_path.startswith(prefix) or not file_path.endswith(".py"):
            continue
        summary = info.get("summary") or {}
        missing = summary.get("missing_lines")
        if missing is None:
            missing = len(info.get("missing_lines") or [])
        pct = float(summary.get("percent_covered", 0))
        rows.append((int(missing), file_path, pct))
    rows.sort(key=lambda x: (-x[0], x[1]))
    return rows[:top]


def rank_from_xml(path: Path, *, top: int, prefix: str) -> list[tuple[int, str, float]]:
    root = ET.parse(path).getroot()
    rows: list[tuple[int, str, float]] = []
    for cls in root.iter("class"):
        fn = cls.get("filename", "")
        if not fn.endswith(".py"):
            continue
        file_path = f"app/{fn}" if not fn.startswith("app/") else fn
        if not file_path.startswith(prefix):
            continue
        lines = cls.findall("lines/line")
        if not lines:
            continue
        missing = sum(1 for line in lines if line.get("hits") == "0")
        total = len(lines)
        covered = total - missing
        pct = (covered / total * 100.0) if total else 0.0
        rows.append((missing, file_path, pct))
    rows.sort(key=lambda x: (-x[0], x[1]))
    return rows[:top]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        type=Path,
        default=ROOT / "coverage.json",
        help="coverage.py JSON report (preferred)",
    )
    parser.add_argument(
        "--xml",
        type=Path,
        default=ROOT / "coverage-full.xml",
        help="Cobertura XML fallback",
    )
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--prefix", default="app/", help="File path prefix filter")
    parser.add_argument("--out", type=Path, default=None, help="Write JSON list to path")
    args = parser.parse_args()

    rows: list[tuple[int, str, float]] = []
    if args.json.is_file():
        rows = rank_from_json(args.json, top=args.top, prefix=args.prefix)
        source = str(args.json)
    elif args.xml.is_file():
        rows = rank_from_xml(args.xml, top=args.top, prefix=args.prefix)
        source = str(args.xml)
    else:
        print("rank_coverage_gaps: no coverage.json or coverage-full.xml", file=sys.stderr)
        return 1

    payload = [
        {"missing_lines": m, "path": p, "percent_covered": round(pct, 2)}
        for m, p, pct in rows
    ]
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"source": source, "top": args.top, "files": payload}, indent=2)
            + "\n",
            encoding="utf-8",
        )

    print(f"# source={source} top={args.top}")
    for m, p, pct in rows:
        print(f"{m:5d}  {pct:6.1f}%  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
