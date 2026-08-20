#!/usr/bin/env python3
"""Guarded DR promotion controller.

The controller deliberately requires three independent facts before promotion:
the primary HTTPS and SSH paths are both down, authoritative DNS has selected
only the DR address, and a fresh provider-side fencing proof exists. This keeps
a two-node network partition from creating two writable database primaries.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Decision:
    consecutive: int
    promote: bool
    reason: str


def decide(
    *,
    enabled: bool,
    primary_https_ok: bool,
    primary_ssh_ok: bool,
    authoritative_addresses: Iterable[str],
    secondary_ip: str,
    standby_ready: bool,
    fence_ready: bool,
    previous_consecutive: int,
    threshold: int,
) -> Decision:
    addresses = set(authoritative_addresses)
    if not enabled:
        return Decision(0, False, "disabled")
    if primary_https_ok:
        return Decision(0, False, "primary_https_healthy")
    if primary_ssh_ok:
        return Decision(0, False, "primary_host_reachable")
    if addresses != {secondary_ip}:
        return Decision(0, False, "authoritative_dns_has_not_fenced_primary")
    if not standby_ready:
        return Decision(0, False, "standby_not_ready")
    consecutive = previous_consecutive + 1
    if consecutive < threshold:
        return Decision(consecutive, False, "waiting_for_consecutive_evidence")
    if not fence_ready:
        return Decision(consecutive, False, "provider_fence_proof_missing")
    return Decision(consecutive, True, "all_promotion_guards_satisfied")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def env_bool(values: dict[str, str], key: str, default: str = "0") -> bool:
    return values.get(key, os.environ.get(key, default)).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def setting(values: dict[str, str], key: str, default: str) -> str:
    return os.environ.get(key, values.get(key, default))


def run(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def https_probe(domain: str, primary_ip: str, path: str) -> bool:
    result = run(
        [
            "curl",
            "-fsS",
            "--connect-timeout",
            "4",
            "--max-time",
            "8",
            "--resolve",
            f"{domain}:443:{primary_ip}",
            f"https://{domain}{path}",
        ],
        timeout=10,
    )
    return result.returncode == 0


def tcp_probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=4):
            return True
    except OSError:
        return False


def authoritative_addresses(domain: str) -> set[str]:
    ns_result = run(["dig", "+short", "NS", domain])
    nameservers = sorted(
        {
            line.strip().rstrip(".")
            for line in ns_result.stdout.splitlines()
            if line.strip()
        }
    )
    if ns_result.returncode != 0 or not nameservers:
        return set()
    answers: set[str] = set()
    for nameserver in nameservers:
        result = run(["dig", "+short", f"@{nameserver}", domain, "A"])
        if result.returncode != 0:
            return set()
        current = {
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and line[0].isdigit()
        }
        if not current:
            return set()
        answers.update(current)
    return answers


def status_values(command: str) -> dict[str, str]:
    result = run([command])
    if result.returncode != 0:
        return {}
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def valid_fence_proof(path: Path, primary_ip: str, now: int) -> bool:
    try:
        stat = path.stat()
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if stat.st_uid != 0 or stat.st_mode & 0o077:
        return False
    return (
        doc.get("primary_ip") == primary_ip
        and doc.get("fenced") is True
        and int(doc.get("expires_at", 0)) >= now
    )


def trusted_executable(path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    return (
        path.is_absolute()
        and path.is_file()
        and stat.st_uid == 0
        and not stat.st_mode & 0o022
        and os.access(path, os.X_OK)
    )


def atomic_json(path: Path, value: dict[str, object], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def main() -> int:
    if os.geteuid() != 0:
        print("请以 root 运行", file=sys.stderr)
        return 2

    env_path = Path(
        os.environ.get("OPS_DR_AUTO_FAILOVER_ENV", "/etc/xcmax-dr-auto-failover.env")
    )
    values = load_env(env_path)
    state_path = Path(
        setting(
            values,
            "OPS_DR_FAILOVER_STATE",
            "/var/lib/xcmax-dr/failover-guard.json",
        )
    )
    witness_path = Path(
        setting(
            values,
            "OPS_DR_FAILOVER_WITNESS",
            "/var/lib/xcmax-dr/failover-witness.json",
        )
    )
    fence_path = Path(
        setting(
            values,
            "OPS_DR_FENCE_PROOF",
            "/var/lib/xcmax-dr/provider-fence-proof.json",
        )
    )
    primary_ip = setting(values, "OPS_DR_PRIMARY_IP", "119.27.178.147")
    secondary_ip = setting(values, "OPS_DR_SECONDARY_IP", "43.138.211.142")
    domain = setting(values, "OPS_DR_DOMAIN", "xiu-ci.com")
    health_path = setting(values, "OPS_DR_PRIMARY_HEALTH_PATH", "/fhd-api/api/health")
    threshold = int(setting(values, "OPS_DR_FAILOVER_THRESHOLD", "3"))
    status_command = setting(
        values, "OPS_DR_STATUS_COMMAND", "/usr/local/sbin/xcmax-dr-status"
    )
    promote_command = setting(
        values, "OPS_DR_PROMOTE_COMMAND", "/usr/local/sbin/xcmax-dr-promote"
    )
    fence_command = Path(
        setting(
            values,
            "OPS_DR_FENCE_COMMAND",
            "/usr/local/sbin/xcmax-dr-tencent-fence",
        )
    )
    enabled = env_bool(values, "OPS_DR_AUTO_FAILOVER_ENABLED")
    now = int(time.time())

    previous: dict[str, object] = {}
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    previous_consecutive = int(previous.get("consecutive", 0))

    primary_https_ok = https_probe(domain, primary_ip, health_path)
    primary_ssh_ok = tcp_probe(primary_ip, 22)
    addresses = authoritative_addresses(domain)
    status = status_values(status_command)
    standby_ready = (
        status.get("wal_in_recovery") == "t"
        and status.get("wal_pg16_in_recovery") == "t"
    )
    fence_ready = valid_fence_proof(fence_path, primary_ip, now)
    decision = decide(
        enabled=enabled,
        primary_https_ok=primary_https_ok,
        primary_ssh_ok=primary_ssh_ok,
        authoritative_addresses=addresses,
        secondary_ip=secondary_ip,
        standby_ready=standby_ready,
        fence_ready=fence_ready,
        previous_consecutive=previous_consecutive,
        threshold=threshold,
    )
    fence_attempted = False
    fence_exit_code: int | None = None
    if (
        decision.reason == "provider_fence_proof_missing"
        and decision.consecutive >= threshold
        and trusted_executable(fence_command)
    ):
        fence_attempted = True
        try:
            fence_result = subprocess.run(
                [str(fence_command)],
                check=False,
                timeout=240,
            )
            fence_exit_code = fence_result.returncode
        except subprocess.TimeoutExpired:
            fence_exit_code = 124
        fence_ready = valid_fence_proof(fence_path, primary_ip, int(time.time()))
        decision = decide(
            enabled=enabled,
            primary_https_ok=primary_https_ok,
            primary_ssh_ok=primary_ssh_ok,
            authoritative_addresses=addresses,
            secondary_ip=secondary_ip,
            standby_ready=standby_ready,
            fence_ready=fence_ready,
            previous_consecutive=max(decision.consecutive - 1, 0),
            threshold=threshold,
        )
    observation: dict[str, object] = {
        "checked_at": now,
        "primary_https_ok": primary_https_ok,
        "primary_ssh_ok": primary_ssh_ok,
        "authoritative_addresses": sorted(addresses),
        "standby_ready": standby_ready,
        "fence_ready": fence_ready,
        "fence_attempted": fence_attempted,
        "fence_exit_code": fence_exit_code,
        **asdict(decision),
    }
    atomic_json(state_path, observation)
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))

    if not decision.promote:
        return 0

    witness = {
        **observation,
        "primary_ip": primary_ip,
        "secondary_ip": secondary_ip,
        "expires_at": now + 300,
    }
    atomic_json(witness_path, witness)
    result = subprocess.run(
        [promote_command, "--witness-file", str(witness_path)],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
