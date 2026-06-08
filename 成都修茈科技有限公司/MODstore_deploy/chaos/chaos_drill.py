#!/usr/bin/env python3
"""Controlled Docker Compose chaos drills for MODstore."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Scenario:
    name: str
    impact: str
    inject: list[list[str]]
    recover: list[list[str]]
    observe: list[str]


SCENARIOS: dict[str, Scenario] = {
    "redis-stop": Scenario(
        name="redis-stop",
        impact="Validate Redis failure impact on auth, replay protection, cache, RAG, and alerts.",
        inject=[["docker", "compose", "stop", "redis"]],
        recover=[["docker", "compose", "up", "-d", "redis"]],
        observe=[
            "Prometheus target health",
            "FastAPI 5xx rate",
            "Java payment errors and replay protection logs",
        ],
    ),
    "rabbitmq-stop": Scenario(
        name="rabbitmq-stop",
        impact="Validate RabbitMQ failure impact on payment startup dependencies and event plumbing.",
        inject=[["docker", "compose", "stop", "rabbitmq"]],
        recover=[["docker", "compose", "up", "-d", "rabbitmq"]],
        observe=[
            "RabbitMQ container health",
            "payment-service logs",
            "Webhook delivery metrics",
        ],
    ),
    "payment-restart": Scenario(
        name="payment-restart",
        impact="Validate Java payment restart behavior, FastAPI proxy 502s, and recovery time.",
        inject=[["docker", "compose", "restart", "payment-service"]],
        recover=[["docker", "compose", "up", "-d", "payment-service"]],
        observe=[
            "modstore_payment_proxy_requests_total{status=\"502\"}",
            "payment-service /actuator/health",
            "sre_smoke_check payment.health",
        ],
    ),
    "postgres-stop": Scenario(
        name="postgres-stop",
        impact="Validate database outage impact on readiness, payment health, alerts, and recovery.",
        inject=[["docker", "compose", "stop", "postgres"]],
        recover=[["docker", "compose", "up", "-d", "postgres"]],
        observe=[
            "health_api database status",
            "Java Hikari errors",
            "ModstoreTargetDown and 5xx alerts",
        ],
    ),
    "api-restart": Scenario(
        name="api-restart",
        impact="Validate FastAPI restart impact on frontend API calls, payment proxy, and alerts.",
        inject=[["docker", "compose", "restart", "api"]],
        recover=[["docker", "compose", "up", "-d", "api"]],
        observe=[
            "market /api requests",
            "Prometheus modstore-api target",
            "sre_smoke_check api.*",
        ],
    ),
}


def run_command(command: list[str], execute: bool) -> int:
    printable = " ".join(command)
    print(f"$ {printable}")
    if not execute:
        return 0
    return subprocess.call(command, cwd=ROOT)


def run_smoke(args: argparse.Namespace, execute: bool) -> int:
    command = [
        sys.executable,
        "scripts/sre_smoke_check.py",
        "--base-url",
        args.base_url,
    ]
    if args.market_url:
        command.extend(["--market-url", args.market_url])
    if args.payment_url:
        command.extend(["--payment-url", args.payment_url])
    if args.prometheus_url:
        command.extend(["--prometheus-url", args.prometheus_url])
    return run_command(command, execute)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a controlled MODstore chaos drill.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--duration", type=int, default=60, help="Fault duration in seconds")
    parser.add_argument("--confirm", action="store_true", help="Actually execute the drill")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip smoke checks before and after the drill")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--market-url", default="http://127.0.0.1:4173")
    parser.add_argument("--payment-url", default="http://127.0.0.1:8080")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    args = parser.parse_args()

    scenario = SCENARIOS[args.scenario]
    execute = args.confirm
    print(f"Scenario: {scenario.name}")
    print(f"Impact: {scenario.impact}")
    print("Observe:")
    for item in scenario.observe:
        print(f"- {item}")
    if not execute:
        print("\nDry run only. Re-run with --confirm in a staging environment to execute.")

    if not args.skip_smoke:
        print("\nPre-check:")
        if run_smoke(args, execute) != 0 and execute:
            print("Pre-check failed; aborting drill.")
            return 1

    print("\nInject fault:")
    for command in scenario.inject:
        code = run_command(command, execute)
        if code != 0:
            return code

    if execute:
        print(f"\nHolding fault for {args.duration}s...")
        time.sleep(max(1, args.duration))
    else:
        print(f"\nWould hold fault for {args.duration}s.")

    print("\nRecover:")
    for command in scenario.recover:
        code = run_command(command, execute)
        if code != 0:
            return code

    if not args.skip_smoke:
        print("\nPost-check:")
        return run_smoke(args, execute)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
