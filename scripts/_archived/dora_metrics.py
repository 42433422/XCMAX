#!/usr/bin/env python3
"""DORA 四指标计算 — 对标大厂用数据驱动「发不发 / 放不放量」决策。

四指标：
  1. Deployment Frequency  部署频率（每日均次）
  2. Lead Time for Changes 变更前置时长（commit → deploy 的中位小时数）
  3. Change Failure Rate   变更失败率（失败部署 / 总部署）
  4. MTTR                  平均恢复时长（失败 → 恢复的中位小时数）

输入：部署事件 JSONL，每行一条：
  {"deploy_id":"d1","deployed_at":"2026-06-01T08:25:00Z","commit_at":"2026-06-01T08:00:00Z",
   "status":"success|failed","restored_at":"2026-06-01T09:00:00Z"}

输出：
  - JSON（人读 / 审计）
  - Prometheus textfile（写入 node_exporter textfile collector 或 pushgateway）
    用于 Grafana DORA 看板（dora_deployment_frequency_per_day 等）。

用法：
  python3 scripts/dora_metrics.py --events deploy_events.jsonl --window-days 30 \
      --prom-out /var/lib/node_exporter/textfile/dora.prom
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class DeployEvent:
    deploy_id: str
    deployed_at: datetime
    commit_at: Optional[datetime]
    status: str
    restored_at: Optional[datetime]

    @classmethod
    def from_dict(cls, d: dict) -> Optional["DeployEvent"]:
        deployed = _parse_ts(d.get("deployed_at"))
        if deployed is None:
            return None
        return cls(
            deploy_id=str(d.get("deploy_id") or ""),
            deployed_at=deployed,
            commit_at=_parse_ts(d.get("commit_at")),
            status=str(d.get("status") or "success").strip().lower(),
            restored_at=_parse_ts(d.get("restored_at")),
        )


@dataclass(frozen=True)
class DoraReport:
    window_days: int
    total_deploys: int
    deployment_frequency_per_day: float
    lead_time_hours_median: Optional[float]
    change_failure_rate: float
    mttr_hours_median: Optional[float]
    performance_band: str


def _median(values: list[float]) -> Optional[float]:
    return round(statistics.median(values), 3) if values else None


def _band(freq_per_day: float, lead_h: Optional[float], cfr: float, mttr_h: Optional[float]) -> str:
    """粗略对标 DORA Elite/High/Medium/Low（按实际可计维度求均分）。

    无失败时 MTTR 为 None（视为最佳，不拉低均分）；lead 缺失时不计入分母。
    """
    score = 0
    dims = 0
    score += 3 if freq_per_day >= 1 else 2 if freq_per_day >= 1 / 7 else 1
    dims += 1
    if lead_h is not None:
        score += 3 if lead_h < 24 else 2 if lead_h < 24 * 7 else 1
        dims += 1
    if cfr <= 0.15:
        score += 3
    elif cfr <= 0.30:
        score += 2
    else:
        score += 1
    dims += 1
    # MTTR：有失败才计入；无失败不惩罚（恢复时长不适用）
    if mttr_h is not None:
        score += 3 if mttr_h < 1 else 2 if mttr_h < 24 else 1
        dims += 1
    avg = score / dims if dims else 0.0
    if avg >= 2.75:
        return "Elite"
    if avg >= 2.0:
        return "High"
    if avg >= 1.5:
        return "Medium"
    return "Low"


def compute_dora(events: Iterable[DeployEvent], *, window_days: int = 30, now: Optional[datetime] = None) -> DoraReport:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    window = [e for e in events if e.deployed_at >= cutoff]

    total = len(window)
    freq = round(total / window_days, 3) if window_days > 0 else 0.0

    lead_times = [
        (e.deployed_at - e.commit_at).total_seconds() / 3600.0
        for e in window
        if e.commit_at is not None and e.deployed_at >= e.commit_at
    ]
    failed = [e for e in window if e.status in ("failed", "fail", "rollback", "rolled_back")]
    cfr = round(len(failed) / total, 3) if total else 0.0

    mttrs = [
        (e.restored_at - e.deployed_at).total_seconds() / 3600.0
        for e in failed
        if e.restored_at is not None and e.restored_at >= e.deployed_at
    ]

    lead_median = _median(lead_times)
    mttr_median = _median(mttrs)
    return DoraReport(
        window_days=window_days,
        total_deploys=total,
        deployment_frequency_per_day=freq,
        lead_time_hours_median=lead_median,
        change_failure_rate=cfr,
        mttr_hours_median=mttr_median,
        performance_band=_band(freq, lead_median, cfr, mttr_median),
    )


def load_events(path: str) -> list[DeployEvent]:
    out: list[DeployEvent] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = DeployEvent.from_dict(d)
            if ev is not None:
                out.append(ev)
    return out


def to_prometheus(report: DoraReport) -> str:
    lines = [
        "# HELP dora_deployment_frequency_per_day DORA: deployments per day",
        "# TYPE dora_deployment_frequency_per_day gauge",
        f"dora_deployment_frequency_per_day {report.deployment_frequency_per_day}",
        "# HELP dora_lead_time_hours_median DORA: median lead time for changes (hours)",
        "# TYPE dora_lead_time_hours_median gauge",
        f"dora_lead_time_hours_median {report.lead_time_hours_median if report.lead_time_hours_median is not None else 'NaN'}",
        "# HELP dora_change_failure_rate DORA: change failure rate (0..1)",
        "# TYPE dora_change_failure_rate gauge",
        f"dora_change_failure_rate {report.change_failure_rate}",
        "# HELP dora_mttr_hours_median DORA: median time to restore (hours)",
        "# TYPE dora_mttr_hours_median gauge",
        f"dora_mttr_hours_median {report.mttr_hours_median if report.mttr_hours_median is not None else 'NaN'}",
        "# HELP dora_total_deploys DORA: total deploys in window",
        "# TYPE dora_total_deploys gauge",
        f"dora_total_deploys {report.total_deploys}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DORA four-key metrics")
    parser.add_argument("--events", required=True, help="deploy events JSONL path")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--prom-out", default="", help="optional Prometheus textfile output path")
    args = parser.parse_args(argv)

    events = load_events(args.events)
    report = compute_dora(events, window_days=args.window_days)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))

    if args.prom_out:
        with open(args.prom_out, "w", encoding="utf-8") as fh:
            fh.write(to_prometheus(report))
        print(f"[ok] wrote prometheus textfile → {args.prom_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
