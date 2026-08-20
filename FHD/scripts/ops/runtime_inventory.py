#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""运行时真相清单：desired（拓扑 SSOT）× actual（端口/进程/systemd/health）。

用法:
  python scripts/ops/runtime_inventory.py check          # 静态：拓扑声明完整（CI）
  python scripts/ops/runtime_inventory.py probe           # 活探针（本机）
  python scripts/ops/runtime_inventory.py probe --json
  python scripts/ops/runtime_inventory.py probe --write   # 写出公开投影 JSON

退出码:
  check: 0 完整 / 1 声明缺失 / 2 配置错误
  probe: 0 全部 must_run 在线 / 1 有 must_run 缺失 / 2 配置错误
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # FHD/
TOPOLOGY_JSON = ROOT / "config" / "topology.generated.json"
TOPOLOGY_YAML = ROOT / "config" / "service_topology.yaml"
SCHEMA = "xcagi.runtime_inventory/v1"

EXIT_OK, EXIT_FAIL, EXIT_CONFIG = 0, 1, 2


def _repo_root() -> Path:
    env = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if env:
        return Path(env)
    return ROOT.parent


def load_topology() -> dict[str, Any]:
    if TOPOLOGY_JSON.is_file():
        return json.loads(TOPOLOGY_JSON.read_text(encoding="utf-8"))
    if not TOPOLOGY_YAML.is_file():
        print(f"拓扑缺失: {TOPOLOGY_JSON} / {TOPOLOGY_YAML}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    try:
        import yaml
    except ImportError as exc:
        print(f"缺少 pyyaml 且无 generated json: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG) from exc
    data = yaml.safe_load(TOPOLOGY_YAML.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(EXIT_CONFIG)
    return data


def port_open(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def process_running(pattern: str) -> bool:
    if not pattern:
        return False
    try:
        res = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res.returncode == 0 and bool(res.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def systemd_active(unit: str) -> bool | None:
    """True/False if systemctl answers; None if systemctl unavailable."""
    if not unit:
        return None
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            capture_output=True,
            timeout=5,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def http_health(url: str, timeout: float = 2.0) -> bool | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return 200 <= int(resp.status) < 400
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def check_static() -> int:
    """CI：拓扑必须声明 must_run 服务/进程，且 generated json 与 yaml 同源字段齐全。"""
    if not TOPOLOGY_YAML.is_file():
        print(f"缺少 {TOPOLOGY_YAML}", file=sys.stderr)
        return EXIT_CONFIG
    if not TOPOLOGY_JSON.is_file():
        print(
            f"缺少 {TOPOLOGY_JSON}（先 service_topology_ssot.py generate --apply）",
            file=sys.stderr,
        )
        return EXIT_FAIL

    topo = load_topology()
    services = topo.get("services") or {}
    processes = topo.get("processes") or []
    units = topo.get("systemd_units") or []
    errors: list[str] = []

    must_services = [sid for sid, svc in services.items() if (svc or {}).get("must_run")]
    if not must_services:
        errors.append("services 中无 must_run: true")
    must_procs = [p for p in processes if (p or {}).get("must_run")]
    if not must_procs:
        errors.append("processes 中无 must_run: true")
    for p in must_procs:
        if not (p.get("detect") or p.get("name")):
            errors.append(f"must_run 进程缺 detect/name: {p}")
    for u in units:
        if not u.get("name"):
            errors.append(f"systemd_units 缺 name: {u}")

    # generated json 必须能驱动探针
    if "services" not in topo or "processes" not in topo:
        errors.append("topology.generated.json 缺 services/processes")

    if errors:
        for e in errors:
            print(f"runtime-inventory check FAIL: {e}", file=sys.stderr)
        return EXIT_FAIL
    print(
        "runtime-inventory check OK："
        f"must_run services={len(must_services)} processes={len(must_procs)} "
        f"systemd_units={len(units)}"
    )
    return EXIT_OK


def build_inventory(*, host: str = "127.0.0.1") -> dict[str, Any]:
    topo = load_topology()
    services = topo.get("services") or {}
    processes = topo.get("processes") or []
    units = topo.get("systemd_units") or []

    items: list[dict[str, Any]] = []
    failed_must_run = 0

    for sid in sorted(services):
        svc = services[sid] or {}
        port = svc.get("listen_port")
        must = bool(svc.get("must_run"))
        alive_port: bool | None = None
        if port is not None:
            alive_port = port_open(host, int(port))
        health_path = str(svc.get("health") or "").strip()
        health_ok: bool | None = None
        if health_path and port is not None:
            health_ok = http_health(f"http://{host}:{int(port)}{health_path}")
        desired = "running" if must else "optional"
        # 端口权威；无端口则看 health
        if alive_port is True or health_ok is True:
            actual = "running"
        elif alive_port is False or health_ok is False:
            actual = "stopped"
        else:
            actual = "unknown"
        if must and actual != "running":
            failed_must_run += 1
        items.append(
            {
                "kind": "service",
                "id": sid,
                "desired": desired,
                "actual": actual,
                "must_run": must,
                "listen_port": port,
                "port_open": alive_port,
                "health": health_ok,
                "runner": svc.get("runner"),
                "detail": f"{host}:{port}" if port is not None else "",
            }
        )

    for proc in processes:
        name = str(proc.get("name") or "")
        if not name:
            continue
        pattern = str(proc.get("detect") or name)
        alive = process_running(pattern)
        must = bool(proc.get("must_run"))
        actual = "running" if alive else "stopped"
        if must and not alive:
            failed_must_run += 1
        items.append(
            {
                "kind": "process",
                "id": name,
                "desired": "running" if must else "optional",
                "actual": actual,
                "must_run": must,
                "detect": pattern,
                "service": proc.get("service"),
                "detail": proc.get("note") or "",
            }
        )

    for unit in units:
        name = str(unit.get("name") or "")
        if not name:
            continue
        active = systemd_active(name)
        must = bool(unit.get("must_run"))
        if active is True:
            actual = "running"
        elif active is False:
            actual = "stopped"
        else:
            actual = "unknown"
        if must and actual != "running":
            # unknown（无 systemctl）不计入失败，避免 macOS/dev 假红
            if actual == "stopped":
                failed_must_run += 1
        items.append(
            {
                "kind": "systemd",
                "id": name,
                "desired": "running" if must else "optional",
                "actual": actual,
                "must_run": must,
                "service": unit.get("service"),
                "detail": unit.get("note") or "",
            }
        )

    running = sum(1 for i in items if i.get("actual") == "running")
    stopped = sum(1 for i in items if i.get("actual") == "stopped")
    unknown = sum(1 for i in items if i.get("actual") == "unknown")
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "host": host,
        "source": {
            "topology": (
                str(TOPOLOGY_JSON.relative_to(ROOT))
                if TOPOLOGY_JSON.is_file()
                else str(TOPOLOGY_YAML.relative_to(ROOT))
            ),
            "public_host": topo.get("host") or (topo.get("public") or {}).get("host"),
        },
        "ok": failed_must_run == 0,
        "failed_must_run": failed_must_run,
        "counts": {
            "total": len(items),
            "running": running,
            "stopped": stopped,
            "unknown": unknown,
            "must_run_failed": failed_must_run,
        },
        "items": items,
        "note": "desired 来自 service_topology.yaml；actual 来自本机端口/pgrep/systemctl/HTTP health。",
    }


def projection_targets() -> list[Path]:
    root = _repo_root()
    targets = [
        root / "成都修茈科技有限公司" / "download-runtime-inventory.json",
        root
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "market"
        / "public"
        / "download-runtime-inventory.json",
        ROOT / "config" / "runtime_inventory.generated.json",
    ]
    for raw in (
        "/root/成都修茈科技有限公司",
        "/opt/xcmax/current/成都修茈科技有限公司",
    ):
        try:
            live = Path(raw)
            if live.is_dir():
                targets.append(live.resolve() / "download-runtime-inventory.json")
        except OSError:
            pass
    return targets


def write_projection(payload: dict[str, Any]) -> dict[str, Any]:
    written: list[str] = []
    errors: list[str] = []
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for tgt in projection_targets():
        try:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tmp = tgt.with_suffix(tgt.suffix + ".tmp")
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(tgt)
            written.append(str(tgt))
        except OSError as exc:
            errors.append(f"{tgt}: {exc}")
    return {"ok": not errors, "written": written, "errors": errors}


def cmd_probe(*, host: str, as_json: bool, write: bool) -> int:
    payload = build_inventory(host=host)
    publication = None
    if write:
        publication = write_projection(payload)
        payload = {**payload, "publication": publication}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        mark = "✓" if payload["ok"] else "✗"
        print(f"runtime inventory @ {host}  {mark} failed_must_run={payload['failed_must_run']}")
        for it in payload["items"]:
            m = "✓" if it["actual"] == "running" else ("?" if it["actual"] == "unknown" else "✗")
            flag = " [must_run]" if it.get("must_run") else ""
            detail = f"  {it.get('detail')}" if it.get("detail") else ""
            print(f"  {m} {it['kind']:<8} {it['id']:<28} {it['actual']}{flag}{detail}")
        if publication is not None:
            print(
                f"written={len(publication.get('written') or [])} errors={publication.get('errors')}"
            )
    return EXIT_OK if payload["ok"] else EXIT_FAIL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行时真相清单")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="静态声明完整性（CI）")
    probe = sub.add_parser("probe", help="本机活探针")
    probe.add_argument("--host", default="127.0.0.1")
    probe.add_argument("--json", action="store_true")
    probe.add_argument("--write", action="store_true", help="写出公开投影 JSON")
    args = parser.parse_args(argv)
    if args.cmd == "check":
        return check_static()
    if args.cmd == "probe":
        return cmd_probe(host=args.host, as_json=args.json, write=args.write)
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
