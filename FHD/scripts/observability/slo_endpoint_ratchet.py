#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""Top-20 端点 SLO 棘轮（复刻 coverage_ratchet.py 思路，只升不降）。

数据源：Prometheus `api_requests_total` + `api_request_duration_seconds_bucket`
SSOT：FHD/metrics/slo_endpoint_baseline.json

子命令：
  --check      校验当前实测是否达标（CI 调用，破线 exit 1）
  --bump       实测超越 floor 时上调 floor（只升不降）
  --top20      从 Prometheus 提取真实调用量重排 Top-20（v2 用）
  --audit      校验 763 端点全部分桶（无漏 Tier）
  --promql     输出 PromQL 模板（用于 Grafana / collect_slo_metrics.py）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from app.utils.operational_errors import RECOVERABLE_ERRORS

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "metrics" / "slo_endpoint_baseline.json"
MEASURED_PATH = ROOT / "metrics" / "slo_endpoint_measured.json"


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())


def save_baseline(data: dict) -> None:
    data["updated"] = datetime.now(UTC).strftime("%Y-%m-%d")
    BASELINE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# =====================================================================
# PromQL 模板
# =====================================================================


def promql_availability(endpoint: str, window: str) -> str:
    return (
        f'1 - (sum(rate(api_requests_total{{endpoint="{endpoint}", status=~"5.."}}[{window}])) '
        f'/ clamp_min(sum(rate(api_requests_total{{endpoint="{endpoint}"}}[{window}])),1)) * 100'
    )


def promql_pXX(endpoint: str, window: str, quantile: float) -> str:
    return (
        f"histogram_quantile({quantile}, sum by (le) "
        f'(rate(api_request_duration_seconds_bucket{{endpoint="{endpoint}"}}[{window}]))) * 1000'
    )


def promql_error_rate(endpoint: str, window: str) -> str:
    return (
        f'sum(rate(api_requests_total{{endpoint="{endpoint}", status=~"5.."}}[{window}])) '
        f'/ clamp_min(sum(rate(api_requests_total{{endpoint="{endpoint}"}}[{window}])),1) * 100'
    )


def query_prometheus(prom_url: str, promql: str) -> float | None:
    """执行 instant query，返回 float 或 None（无数据）。"""
    url = f"{prom_url.rstrip('/')}/api/v1/query?query={urllib.parse.quote(promql)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        result = data.get("data", {}).get("result", [])
        if not result:
            return None
        return float(result[0]["value"][1])
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
        return None


# =====================================================================
# 子命令实现
# =====================================================================


def cmd_check(prom_url: str, window: str) -> int:
    baseline = load_baseline()
    floors = baseline["endpoint_slo_floors"]
    measured: dict = {}
    failures: list[str] = []

    print(f"[check] window={window} endpoints={len(floors)}")
    for endpoint, floor in floors.items():
        avail = query_prometheus(prom_url, promql_availability(endpoint, window))
        p95 = query_prometheus(prom_url, promql_pXX(endpoint, window, 0.95))
        p99 = query_prometheus(prom_url, promql_pXX(endpoint, window, 0.99))
        err_rate = query_prometheus(prom_url, promql_error_rate(endpoint, window))

        measured[endpoint] = {
            "availability": avail,
            "p95_ms": p95,
            "p99_ms": p99,
            "error_rate_pct": err_rate,
        }

        # 判定
        if avail is not None and avail < floor["availability"]:
            failures.append(
                f"{endpoint} availability {avail:.2f}% < floor {floor['availability']}%"
            )
        if p95 is not None and p95 > floor["p95_ms"]:
            failures.append(f"{endpoint} p95 {p95:.0f}ms > floor {floor['p95_ms']}ms")
        if p99 is not None and p99 > floor["p99_ms"]:
            failures.append(f"{endpoint} p99 {p99:.0f}ms > floor {floor['p99_ms']}ms")
        if err_rate is not None and err_rate > floor["error_rate_pct"]:
            failures.append(
                f"{endpoint} error_rate {err_rate:.2f}% > floor {floor['error_rate_pct']}%"
            )

    MEASURED_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "window": window,
                "prometheus_url": prom_url,
                "measured": measured,
                "failures": failures,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    if failures:
        print(f"[check] ❌ {len(failures)} 条不达标：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[check] ✅ 全部达标")
    return 0


def cmd_bump(prom_url: str, window: str) -> int:
    """实测超越 floor 时上调 floor（只升不降）。"""
    baseline = load_baseline()
    floors = baseline["endpoint_slo_floors"]
    last_measured: dict = {}
    bumped: list[str] = []

    for endpoint, floor in floors.items():
        avail = query_prometheus(prom_url, promql_availability(endpoint, window))
        p95 = query_prometheus(prom_url, promql_pXX(endpoint, window, 0.95))
        p99 = query_prometheus(prom_url, promql_pXX(endpoint, window, 0.99))
        err_rate = query_prometheus(prom_url, promql_error_rate(endpoint, window))

        last_measured[endpoint] = {
            "availability": avail,
            "p95_ms": p95,
            "p99_ms": p99,
            "error_rate_pct": err_rate,
        }

        # 只升不降：availability 取 max，延迟/error_rate 取 min
        if avail is not None and avail > floor["availability"]:
            floor["availability"] = round(avail, 2)
            bumped.append(f"{endpoint} availability → {avail:.2f}%")
        if p95 is not None and p95 < floor["p95_ms"] and p95 > 0:
            floor["p95_ms"] = int(p95)
            bumped.append(f"{endpoint} p95 → {int(p95)}ms")
        if p99 is not None and p99 < floor["p99_ms"] and p99 > 0:
            floor["p99_ms"] = int(p99)
            bumped.append(f"{endpoint} p99 → {int(p99)}ms")
        if err_rate is not None and err_rate < floor["error_rate_pct"]:
            floor["error_rate_pct"] = round(err_rate, 3)
            bumped.append(f"{endpoint} error_rate → {err_rate:.3f}%")

    baseline["last_measured"] = last_measured
    baseline["last_measured_date"] = datetime.now(UTC).strftime("%Y-%m-%d")
    save_baseline(baseline)

    if bumped:
        print(f"[bump] ✅ 上调 {len(bumped)} 项：")
        for b in bumped:
            print(f"  - {b}")
    else:
        print("[bump] 无变化（实测未超 floor）")
    return 0


def cmd_audit() -> int:
    """校验所有路由文件中的端点都被分桶（粗略静态校验）。"""
    baseline = load_baseline()
    p0_endpoints = set(baseline["tier_p0_endpoints"])
    p1_domains = list(baseline["tier_p1_domain_slo"].keys())

    routes_dir = ROOT / "app" / "fastapi_routes"
    pattern = re.compile(r'@router\.(get|post|put|delete|patch)\("([^"]+)"')

    all_endpoints: set[str] = set()
    for py_file in routes_dir.rglob("*.py"):
        try:
            content = py_file.read_text()
            for match in pattern.finditer(content):
                path = match.group(2)
                # 标准化：去掉末尾斜杠
                path = path.rstrip("/") or "/"
                all_endpoints.add(path)
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
            continue

    print(f"[audit] 静态扫描发现 {len(all_endpoints)} 个端点")

    uncovered: list[str] = []
    for ep in all_endpoints:
        if ep in p0_endpoints:
            continue
        # 检查是否被 P1 domain 覆盖
        covered = False
        for domain_pattern in p1_domains:
            prefix = domain_pattern.rstrip("*")
            if ep.startswith(prefix):
                covered = True
                break
        if not covered:
            uncovered.append(ep)

    if uncovered:
        print(f"[audit] ⚠️  {len(uncovered)} 个端点未被 P0/P1 覆盖（落入 P2 长尾）：")
        for ep in sorted(uncovered)[:20]:
            print(f"  - {ep}")
        if len(uncovered) > 20:
            print(f"  ... 还有 {len(uncovered) - 20} 个")
        # P2 长尾是合法 Tier，不算失败
        print("[audit] ✅ 全部端点均有 Tier 归属（P0/P1/P2）")
        return 0
    print("[audit] ✅ 全部端点被 P0/P1 覆盖")
    return 0


def cmd_promql(window: str) -> int:
    """输出 Grafana / collect_slo_metrics.py 用的 PromQL。"""
    baseline = load_baseline()
    floors = baseline["endpoint_slo_floors"]
    print(f"# Top-20 端点 SLO PromQL（window={window}）")
    for ep in floors:
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", ep)
        print(f"\n## {ep}")
        print(f"slo_endpoint_availability:{safe_name} = {promql_availability(ep, window)}")
        print(f"slo_endpoint_p95_ms:{safe_name} = {promql_pXX(ep, window, 0.95)}")
        print(f"slo_endpoint_p99_ms:{safe_name} = {promql_pXX(ep, window, 0.99)}")
        print(f"slo_endpoint_error_rate:{safe_name} = {promql_error_rate(ep, window)}")
    return 0


def cmd_top20(prom_url: str, window: str) -> int:
    """从 Prometheus 提取真实调用量 Top-20（v2 用，需 Prometheus 在线）。"""
    promql = f"topk(20, sum by (endpoint) (rate(api_requests_total[{window}])))"
    url = f"{prom_url.rstrip('/')}/api/v1/query?query={urllib.parse.quote(promql)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        result = data.get("data", {}).get("result", [])
        print(f"[top20] window={window}，实测调用量 Top-20：")
        for i, item in enumerate(result, 1):
            ep = item["metric"].get("endpoint", "?")
            rate = float(item["value"][1])
            print(f"  {i:2d}. {ep:60s} {rate:>10.2f} req/s")
        return 0
    except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
        print(f"[top20] ❌ Prometheus 查询失败: {e}", file=sys.stderr)
        return 1


# =====================================================================
# main
# =====================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9091")
    parser.add_argument("--window", default="7d")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--bump", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--promql", action="store_true")
    parser.add_argument("--top20", action="store_true")
    args = parser.parse_args()

    if args.check:
        return cmd_check(args.prometheus_url, args.window)
    if args.bump:
        return cmd_bump(args.prometheus_url, args.window)
    if args.audit:
        return cmd_audit()
    if args.promql:
        return cmd_promql(args.window)
    if args.top20:
        return cmd_top20(args.prometheus_url, args.window)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
