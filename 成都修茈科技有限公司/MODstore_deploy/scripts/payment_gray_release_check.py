#!/usr/bin/env python3
"""Preflight checks for the Python -> Java payment gray release.

Usage:
    python scripts/payment_gray_release_check.py --base-url http://127.0.0.1:8080
    python scripts/payment_gray_release_check.py --base-url https://java-pay \
        --admin-token "$STAGING_ADMIN_JWT" --json

The script exits with status ``0`` only if every probe in the report has
``ok=True``. It is safe to run from CI smoke jobs and from the manual gray
release runbook in ``docs/PAYMENT_GRAY_RELEASE.md``.

Probes:
- ``actuator_health``: GET ``{base_url}/actuator/health`` (Spring Boot)
- ``payment_plans``: GET ``{base_url}/api/payment/plans`` (no auth)
- ``payment_diagnostics``: GET ``{base_url}/api/payment/diagnostics`` (admin
  JWT, optional)
- ``contract_match``: static check that ``PAYMENT_BACKEND`` and
  ``JAVA_PAYMENT_SERVICE_URL`` agree with the contract proxy prefixes.

The script never writes to any database or file system; it can be aborted at
any point.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx  # noqa: E402

from modstore_server.application.payment_gateway import PaymentGatewayService  # noqa: E402
from modstore_server.payment_contract import PROXY_PREFIXES  # noqa: E402


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)
    message: str = ""


def _http_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> tuple[int | None, dict[str, Any] | str | None, str]:
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.get(url, headers=headers or {})
    except httpx.HTTPError as exc:
        return None, None, f"{type(exc).__name__}: {exc}"
    body: dict[str, Any] | str
    try:
        body = response.json()
    except ValueError:
        body = response.text[:500]
    return response.status_code, body, ""


def probe_contract_alignment(*, payment_backend: str | None = None, java_url: str | None = None) -> ProbeResult:
    """Verify that the FastAPI gateway will actually proxy to Java.

    This is a pure-Python check; it does not contact the network and is safe
    to run before the Java service is even up."""

    gateway = PaymentGatewayService(backend=payment_backend, java_url=java_url)
    ok = gateway.backend == "java"
    proxied = {prefix: gateway.should_proxy_to_java(prefix + "/probe") for prefix in PROXY_PREFIXES}
    if ok and not all(proxied.values()):
        ok = False
        message = "Gateway is in java mode but not all contract prefixes are proxied"
    elif not ok:
        message = (
            f"PAYMENT_BACKEND={gateway.backend!r}; gray release requires PAYMENT_BACKEND=java"
        )
    else:
        message = "PaymentGatewayService will proxy contract prefixes to Java"
    return ProbeResult(
        name="contract_match",
        ok=ok,
        detail={
            "backend": gateway.backend,
            "java_url": gateway.java_url,
            "proxied_prefixes": proxied,
        },
        message=message,
    )


def probe_actuator_health(base_url: str) -> ProbeResult:
    url = f"{base_url.rstrip('/')}/actuator/health"
    status, body, error = _http_get(url)
    if error:
        return ProbeResult(name="actuator_health", ok=False, detail={"url": url}, message=error)
    ok = status == 200 and isinstance(body, dict) and str(body.get("status", "")).upper() == "UP"
    return ProbeResult(
        name="actuator_health",
        ok=bool(ok),
        detail={"url": url, "status_code": status, "body": body},
        message="" if ok else "Java actuator did not report UP",
    )


def probe_payment_plans(base_url: str) -> ProbeResult:
    url = f"{base_url.rstrip('/')}/api/payment/plans"
    status, body, error = _http_get(url)
    if error:
        return ProbeResult(name="payment_plans", ok=False, detail={"url": url}, message=error)
    ok = status == 200 and isinstance(body, dict) and isinstance(body.get("plans"), list)
    return ProbeResult(
        name="payment_plans",
        ok=bool(ok),
        detail={
            "url": url,
            "status_code": status,
            "plan_count": len(body["plans"]) if ok and isinstance(body, dict) else 0,
        },
        message="" if ok else f"Unexpected /api/payment/plans response: status={status}",
    )


def probe_payment_diagnostics(base_url: str, admin_token: str) -> ProbeResult:
    url = f"{base_url.rstrip('/')}/api/payment/diagnostics"
    status, body, error = _http_get(url, headers={"Authorization": f"Bearer {admin_token}"})
    if error:
        return ProbeResult(name="payment_diagnostics", ok=False, detail={"url": url}, message=error)
    if status == 200 and isinstance(body, dict) and bool(body.get("ok", False)) and body.get("alipay_configured") is True:
        return ProbeResult(
            name="payment_diagnostics",
            ok=True,
            detail={"url": url, "status_code": status, "body": body},
        )
    return ProbeResult(
        name="payment_diagnostics",
        ok=False,
        detail={"url": url, "status_code": status, "body": body},
        message="Diagnostics endpoint did not report alipay_configured",
    )


def run_probes(*, base_url: str, admin_token: str = "", payment_backend: str | None = None, java_url: str | None = None) -> list[ProbeResult]:
    if java_url is None:
        java_url = base_url
    results: list[ProbeResult] = [
        probe_contract_alignment(payment_backend=payment_backend, java_url=java_url),
        probe_actuator_health(base_url),
        probe_payment_plans(base_url),
    ]
    if admin_token:
        results.append(probe_payment_diagnostics(base_url, admin_token))
    return results


def format_report(results: Sequence[ProbeResult]) -> dict[str, Any]:
    return {
        "ok": all(r.ok for r in results),
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": [asdict(r) for r in results if not r.ok],
        "all": [asdict(r) for r in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Java payment service gray release preflight")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("JAVA_PAYMENT_SERVICE_URL", "http://127.0.0.1:8080"),
        help="Java service base URL (e.g. http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--admin-token",
        default=os.environ.get("MODSTORE_ADMIN_TOKEN", ""),
        help="Admin Bearer token for /api/payment/diagnostics (optional)",
    )
    parser.add_argument(
        "--payment-backend",
        default=os.environ.get("PAYMENT_BACKEND"),
        help="Override PAYMENT_BACKEND for the contract alignment probe",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    args = parser.parse_args(argv)

    results = run_probes(
        base_url=args.base_url,
        admin_token=args.admin_token.strip(),
        payment_backend=args.payment_backend,
        java_url=args.base_url,
    )
    report = format_report(results)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for r in results:
            status = "OK" if r.ok else "FAIL"
            print(f"[{status}] {r.name}: {r.message or 'pass'}")
        print()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
