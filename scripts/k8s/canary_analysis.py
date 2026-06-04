#!/usr/bin/env python3
"""Canary 自动分析 — 对标大厂（Kayenta 风格）的指标判定门。

将「按时间条件（installer 日）promote」升级为「按指标条件 promote/rollback」：
对比 canary 与 baseline(stable) 的错误率与 p95 延迟，给出确定性判决。

设计：
- 纯决策函数 ``analyze`` 与 I/O（Prometheus 查询）分离，便于单测。
- CLI 退出码驱动 deploy.yml：
    0 = PROMOTE（指标健康，放量/切流）
    1 = ROLLBACK（指标恶化，回滚）
    2 = HOLD（样本不足/查询失败，保持现状等待人工或下一轮）

环境变量（live 模式）：
  PROMETHEUS_URL                  Prometheus base URL（如 http://prometheus:9090）
  CANARY_DEPLOYMENT               canary deployment 名（默认 xcagi-canary）
  BASELINE_DEPLOYMENT             baseline deployment 名（默认 xcagi）
  CANARY_ANALYSIS_WINDOW          PromQL rate 窗口（默认 5m）
  CANARY_MIN_SAMPLES              最少请求样本数，低于则 HOLD（默认 50）
  CANARY_ERROR_ABS_CEILING        canary 5xx 比例绝对上限（默认 0.02 = 2%）
  CANARY_ERROR_DELTA_MARGIN       canary 相对 baseline 允许的错误率增量（默认 0.01）
  CANARY_LATENCY_RATIO_MARGIN     canary p95 相对 baseline 允许的放大比例（默认 0.20 = +20%）
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Optional

PROMOTE = "promote"
ROLLBACK = "rollback"
HOLD = "hold"

_EXIT = {PROMOTE: 0, ROLLBACK: 1, HOLD: 2}


@dataclass(frozen=True)
class CanaryThresholds:
    min_samples: int = 50
    error_abs_ceiling: float = 0.02
    error_delta_margin: float = 0.01
    latency_ratio_margin: float = 0.20

    @classmethod
    def from_env(cls) -> "CanaryThresholds":
        def _f(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, "") or default)
            except ValueError:
                return default

        def _i(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, "") or default)
            except ValueError:
                return default

        return cls(
            min_samples=_i("CANARY_MIN_SAMPLES", cls.min_samples),
            error_abs_ceiling=_f("CANARY_ERROR_ABS_CEILING", cls.error_abs_ceiling),
            error_delta_margin=_f("CANARY_ERROR_DELTA_MARGIN", cls.error_delta_margin),
            latency_ratio_margin=_f("CANARY_LATENCY_RATIO_MARGIN", cls.latency_ratio_margin),
        )


@dataclass(frozen=True)
class CanaryMetrics:
    canary_request_count: float
    canary_error_rate: float
    baseline_error_rate: float
    canary_p95_ms: float
    baseline_p95_ms: float


@dataclass(frozen=True)
class CanaryVerdict:
    decision: str
    reasons: list[str]

    @property
    def exit_code(self) -> int:
        return _EXIT.get(self.decision, 2)


def analyze(metrics: CanaryMetrics, thresholds: CanaryThresholds) -> CanaryVerdict:
    """纯决策：根据 canary vs baseline 指标返回 promote/rollback/hold。"""
    reasons: list[str] = []

    if metrics.canary_request_count < thresholds.min_samples:
        return CanaryVerdict(
            HOLD,
            [
                f"样本不足 canary_requests={metrics.canary_request_count:.0f} "
                f"< min_samples={thresholds.min_samples}",
            ],
        )

    breached = False

    # 错误率：绝对上限
    if metrics.canary_error_rate > thresholds.error_abs_ceiling:
        breached = True
        reasons.append(
            f"canary 错误率 {metrics.canary_error_rate:.4f} 超过绝对上限 "
            f"{thresholds.error_abs_ceiling:.4f}"
        )

    # 错误率：相对 baseline 增量
    error_delta = metrics.canary_error_rate - metrics.baseline_error_rate
    if error_delta > thresholds.error_delta_margin:
        breached = True
        reasons.append(
            f"canary 错误率较 baseline 增量 {error_delta:.4f} 超过允许 "
            f"{thresholds.error_delta_margin:.4f}"
        )

    # 延迟：p95 相对 baseline 放大比例
    if metrics.baseline_p95_ms > 0:
        ratio = (metrics.canary_p95_ms - metrics.baseline_p95_ms) / metrics.baseline_p95_ms
        if ratio > thresholds.latency_ratio_margin:
            breached = True
            reasons.append(
                f"canary p95 {metrics.canary_p95_ms:.0f}ms 较 baseline "
                f"{metrics.baseline_p95_ms:.0f}ms 放大 {ratio * 100:.1f}% "
                f"超过允许 {thresholds.latency_ratio_margin * 100:.0f}%"
            )

    if breached:
        return CanaryVerdict(ROLLBACK, reasons)

    return CanaryVerdict(
        PROMOTE,
        [
            f"错误率 {metrics.canary_error_rate:.4f} (baseline {metrics.baseline_error_rate:.4f}) "
            f"· p95 {metrics.canary_p95_ms:.0f}ms (baseline {metrics.baseline_p95_ms:.0f}ms) 均在阈值内",
        ],
    )


def _prom_query(base_url: str, query: str, timeout: float = 15.0) -> Optional[float]:
    """执行一次 Prometheus instant query，返回首个标量值；失败返回 None。"""
    url = base_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - 网络路径
        print(f"[warn] prometheus query failed: {exc}", file=sys.stderr)
        return None
    if payload.get("status") != "success":
        return None
    result = (payload.get("data") or {}).get("result") or []
    if not result:
        return 0.0
    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def collect_metrics_from_prometheus() -> Optional[CanaryMetrics]:
    """live 模式：从 Prometheus 采集 canary/baseline 指标。"""
    base = os.environ.get("PROMETHEUS_URL", "").strip()
    if not base:
        print("[warn] PROMETHEUS_URL 未设置 → 无法采集指标", file=sys.stderr)
        return None
    canary = os.environ.get("CANARY_DEPLOYMENT", "xcagi-canary")
    baseline = os.environ.get("BASELINE_DEPLOYMENT", "xcagi")
    window = os.environ.get("CANARY_ANALYSIS_WINDOW", "5m")

    def _err_rate(dep: str) -> Optional[float]:
        total = _prom_query(
            base,
            f'sum(rate(http_requests_total{{deployment="{dep}"}}[{window}]))',
        )
        errs = _prom_query(
            base,
            f'sum(rate(http_requests_total{{deployment="{dep}",status=~"5.."}}[{window}]))',
        )
        if total is None or errs is None:
            return None
        return (errs / total) if total > 0 else 0.0

    def _p95_ms(dep: str) -> Optional[float]:
        val = _prom_query(
            base,
            f'histogram_quantile(0.95, sum(rate('
            f'http_request_duration_seconds_bucket{{deployment="{dep}"}}[{window}]))'
            f' by (le))',
        )
        return None if val is None else val * 1000.0

    canary_total = _prom_query(
        base, f'sum(increase(http_requests_total{{deployment="{canary}"}}[{window}]))'
    )
    canary_err = _err_rate(canary)
    baseline_err = _err_rate(baseline)
    canary_p95 = _p95_ms(canary)
    baseline_p95 = _p95_ms(baseline)

    if None in (canary_total, canary_err, baseline_err, canary_p95, baseline_p95):
        return None

    return CanaryMetrics(
        canary_request_count=float(canary_total or 0.0),
        canary_error_rate=float(canary_err or 0.0),
        baseline_error_rate=float(baseline_err or 0.0),
        canary_p95_ms=float(canary_p95 or 0.0),
        baseline_p95_ms=float(baseline_p95 or 0.0),
    )


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    thresholds = CanaryThresholds.from_env()

    # 离线/演练模式：从 --metrics-json 读取，便于 CI dry-run 与 SLO halt 演练
    metrics: Optional[CanaryMetrics] = None
    if "--metrics-json" in argv:
        raw = argv[argv.index("--metrics-json") + 1]
        data = json.loads(raw)
        metrics = CanaryMetrics(
            canary_request_count=float(data.get("canary_request_count", 0)),
            canary_error_rate=float(data.get("canary_error_rate", 0)),
            baseline_error_rate=float(data.get("baseline_error_rate", 0)),
            canary_p95_ms=float(data.get("canary_p95_ms", 0)),
            baseline_p95_ms=float(data.get("baseline_p95_ms", 0)),
        )
    else:
        metrics = collect_metrics_from_prometheus()

    if metrics is None:
        verdict = CanaryVerdict(HOLD, ["指标采集失败或不可用 → HOLD（不自动放量）"])
    else:
        verdict = analyze(metrics, thresholds)

    out = {
        "decision": verdict.decision,
        "exit_code": verdict.exit_code,
        "reasons": verdict.reasons,
        "thresholds": asdict(thresholds),
        "metrics": asdict(metrics) if metrics else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
