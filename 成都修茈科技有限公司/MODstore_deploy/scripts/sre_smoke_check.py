#!/usr/bin/env python3
"""MODstore deployment smoke checks for SRE runbooks."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: int | None = None
    latency_ms: int | None = None
    message: str = ""


def _join(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _request_json(url: str, timeout: float) -> tuple[int, Any, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "modstore-sre-smoke/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(256 * 1024)
        text = body.decode("utf-8", errors="replace")
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or text.strip().startswith(("{", "[")):
            try:
                return response.status, json.loads(text), text
            except json.JSONDecodeError:
                return response.status, None, text
        return response.status, None, text


def check_http(name: str, url: str, timeout: float, expected_status: set[int] | None = None) -> CheckResult:
    expected = expected_status or {200}
    started = time.perf_counter()
    try:
        status, payload, text = _request_json(url, timeout)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ok = status in expected
        message = ""
        if not ok:
            message = f"unexpected status {status}: {text[:300]}"
        elif isinstance(payload, dict):
            if payload.get("status") in {"degraded", "down"}:
                ok = False
                message = json.dumps(payload, ensure_ascii=False)[:300]
        return CheckResult(name=name, ok=ok, status=status, latency_ms=elapsed_ms, message=message)
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        return CheckResult(name=name, ok=exc.code in expected, status=exc.code, latency_ms=elapsed_ms, message=body[:300])
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return CheckResult(name=name, ok=False, latency_ms=elapsed_ms, message=str(exc))


def check_prometheus_targets(prometheus_url: str, timeout: float) -> CheckResult:
    started = time.perf_counter()
    url = _join(prometheus_url, "/api/v1/targets")
    try:
        status, payload, text = _request_json(url, timeout)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if status != 200 or not isinstance(payload, dict):
            return CheckResult("prometheus.targets", False, status, elapsed_ms, text[:300])
        active_targets = payload.get("data", {}).get("activeTargets", [])
        unhealthy = [
            f"{target.get('labels', {}).get('job')}:{target.get('health')}"
            for target in active_targets
            if target.get("health") != "up"
        ]
        ok = not unhealthy
        return CheckResult(
            "prometheus.targets",
            ok,
            status,
            elapsed_ms,
            "unhealthy targets: " + ", ".join(unhealthy) if unhealthy else "",
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return CheckResult("prometheus.targets", False, latency_ms=elapsed_ms, message=str(exc))


def build_checks(args: argparse.Namespace) -> list[CheckResult]:
    checks = [
        check_http("api.legacy_health", _join(args.base_url, "/api/health"), args.timeout),
        check_http("api.health", _join(args.base_url, "/health/"), args.timeout),
        check_http("api.liveness", _join(args.base_url, "/health/live"), args.timeout),
        check_http("api.readiness", _join(args.base_url, "/health/ready"), args.timeout),
        check_http("api.market_catalog", _join(args.base_url, "/api/market/catalog"), args.timeout, {200, 401, 403}),
    ]
    if args.market_url:
        checks.append(check_http("market.index", _join(args.market_url, "/market/"), args.timeout))
    if args.payment_url:
        checks.append(check_http("payment.health", _join(args.payment_url, "/actuator/health"), args.timeout))
        checks.append(check_http("payment.plans", _join(args.base_url, "/api/payment/plans"), args.timeout, {200, 401, 403, 502}))
    if args.prometheus_url:
        checks.append(check_http("prometheus.ready", _join(args.prometheus_url, "/-/ready"), args.timeout))
        checks.append(check_prometheus_targets(args.prometheus_url, args.timeout))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MODstore SRE smoke checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="FastAPI base URL")
    parser.add_argument("--market-url", default="", help="Market/Nginx base URL, for example http://127.0.0.1:4173")
    parser.add_argument("--payment-url", default="", help="Java payment service URL, for example http://127.0.0.1:8080")
    parser.add_argument("--prometheus-url", default="", help="Prometheus URL, for example http://127.0.0.1:9090")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    checks = build_checks(args)
    payload = {
        "ok": all(check.ok for check in checks),
        "checks": [asdict(check) for check in checks],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
