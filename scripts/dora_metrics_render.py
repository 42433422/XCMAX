#!/usr/bin/env python3
"""根据 ``metrics/dora-*.json`` 日快照或 ``deploy_events.jsonl`` 生成 DORA 月报 Markdown。

输出：``metrics/dora-monthly-YYYYMM.md``

用法::

  python3 scripts/dora_metrics_render.py --month 202606
  python3 scripts/dora_metrics_render.py --events metrics/deploy_events.jsonl --month 202606
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FHD_ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = FHD_ROOT / "metrics"
DORA_METRICS = FHD_ROOT / "scripts" / "dora_metrics.py"
DATA_SOURCES_DOC = METRICS_DIR / "DORA_DATA_SOURCES.md"


def _parse_month(month: str) -> tuple[datetime, datetime]:
    s = month.strip()
    if len(s) != 6 or not s.isdigit():
        raise SystemExit(f"invalid --month {month!r}, expected YYYYMM")
    start = datetime(int(s[:4]), int(s[4:6]), 1, tzinfo=timezone.utc)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _load_daily_snapshots(month: str) -> list[dict[str, Any]]:
    start, end = _parse_month(month)
    out: list[dict[str, Any]] = []
    for path in sorted(METRICS_DIR.glob("dora-2*.json")):
        stem = path.stem  # dora-YYYYMMDD
        if not stem.startswith("dora-") or len(stem) != len("dora-YYYYMMDD"):
            continue
        day_s = stem.split("-", 1)[1]
        try:
            day = datetime.strptime(day_s, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if start <= day < end:
            out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def _report_from_events(events_path: Path, *, window_days: int) -> dict[str, Any]:
    proc = subprocess.run(
        [
            sys.executable,
            str(DORA_METRICS),
            "--events",
            str(events_path),
            "--window-days",
            str(window_days),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def _pick_report(month: str, *, events_path: Optional[Path], window_days: int) -> dict[str, Any]:
    if events_path and events_path.is_file():
        return _report_from_events(events_path, window_days=window_days)

    dailies = _load_daily_snapshots(month)
    if dailies:
        return dailies[-1].get("report") or dailies[-1]

    seed = METRICS_DIR / "deploy_events.seed.jsonl"
    if seed.is_file():
        return _report_from_events(seed, window_days=window_days)
    raise SystemExit(
        f"no data for month {month}: add metrics/dora-*.json, deploy_events.jsonl, or deploy_events.seed.jsonl"
    )


def _data_sources_blurb() -> str:
    doc = "[`metrics/DORA_DATA_SOURCES.md`](DORA_DATA_SOURCES.md)" if DATA_SOURCES_DOC.is_file() else "`metrics/DORA_DATA_SOURCES.md`"
    return (
        f"四指标（部署频率、变更前置时长、变更失败率、MTTR）字段定义与 GitHub Actions 采集规则见 {doc}。\n"
        "日快照：`dora-metrics-collect.yml` → `metrics/dora-YYYYMMDD.json`；事件流：`metrics/deploy_events.jsonl`。"
    )


def render_markdown(*, month: str, report: dict[str, Any], meta: Optional[dict[str, Any]] = None) -> str:
    meta = meta or {}
    generated = meta.get("generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# DORA 月报 — {month[:4]}-{month[4:6]}",
        "",
        f"> 生成时间（UTC）：`{generated}`",
        "",
        "## 四指标（滚动 30 天窗口）",
        "",
        "| 指标 | 值 | DORA 带 |",
        "|------|-----|---------|",
        f"| 部署频率（次/天） | {report.get('deployment_frequency_per_day')} | {report.get('performance_band')} |",
        f"| 变更前置时长（小时，中位） | {report.get('lead_time_hours_median')} | — |",
        f"| 变更失败率 | {report.get('change_failure_rate')} | — |",
        f"| MTTR（小时，中位） | {report.get('mttr_hours_median')} | — |",
        "",
        f"- 窗口天数：`{report.get('window_days', 30)}`",
        f"- 窗口内部署次数：`{report.get('total_deploys')}`",
        "",
        "## 数据来源说明",
        "",
        _data_sources_blurb(),
        "",
    ]
    if meta.get("events_file"):
        lines.extend(
            [
                "## 原始事件",
                "",
                f"- 事件文件：`{meta['events_file']}`",
                f"- 事件条数：`{meta.get('events_count', '—')}`",
                "",
            ]
        )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render DORA monthly markdown report")
    parser.add_argument("--month", required=True, help="YYYYMM")
    parser.add_argument("--events", default="", help="optional deploy_events.jsonl")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--out", default="", help="default metrics/dora-monthly-YYYYMM.md")
    args = parser.parse_args(argv)

    root = FHD_ROOT.resolve()
    events_path = Path(args.events) if args.events else METRICS_DIR / "deploy_events.jsonl"
    if not events_path.is_absolute():
        events_path = root / events_path
    events_path = events_path.resolve()
    report = _pick_report(args.month, events_path=events_path if events_path.is_file() else None, window_days=args.window_days)

    meta: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if events_path.is_file():
        meta["events_file"] = str(events_path.relative_to(root))
        meta["events_count"] = sum(1 for _ in events_path.read_text(encoding="utf-8").splitlines() if _.strip())

    out = Path(args.out) if args.out else METRICS_DIR / f"dora-monthly-{args.month}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(month=args.month, report=report, meta=meta), encoding="utf-8")
    print(f"[ok] wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
