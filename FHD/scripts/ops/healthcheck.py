#!/usr/bin/env python3
"""服务拓扑健康探针：一条命令查「该活的进程是否都活着」。

数据源 = config/topology.generated.json（由 service_topology.yaml 派生），
所以新增服务/进程会自动进探针，不会漏。

用法:
  python scripts/ops/healthcheck.py                # 探测本机声明的端口 + must_run 进程
  python scripts/ops/healthcheck.py --host 1.2.3.4 # 探测远端端口
  python scripts/ops/healthcheck.py --json         # 机器可读输出

退出码: 0=所有 must_run 进程/端口在线  1=有 must_run 缺失  2=拓扑数据缺失

说明: 进程检测用 pgrep -f <name> 为启发式（modstore-scheduler 等无监听端口的后台进程）；
端口检测为 TCP 连通性（authoritative）。两者都列出，便于人工判断。
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # FHD/
TOPOLOGY = ROOT / "config" / "topology.generated.json"

OK = "✓"
BAD = "✗"


def load_topology() -> dict:
    if not TOPOLOGY.is_file():
        print(
            f"拓扑数据缺失: {TOPOLOGY}（先运行 service_topology_ssot.py generate --apply）",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return json.loads(TOPOLOGY.read_text(encoding="utf-8"))


def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def process_running(pattern: str) -> bool:
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


def run(host: str, *, as_json: bool) -> int:
    topo = load_topology()
    services = topo.get("services") or {}
    processes = topo.get("processes") or []

    results: list[dict] = []
    failed_must_run = 0

    # 1) 端口连通性（声明 listen_port 的服务）
    for sid in sorted(services):
        svc = services[sid] or {}
        port = svc.get("listen_port")
        if port is None:
            continue
        alive = port_open(host, int(port))
        results.append({"kind": "port", "name": sid, "detail": f"{host}:{port}", "alive": alive})

    # 2) must_run 进程（启发式 pgrep）
    for proc in processes:
        name = str(proc.get("name") or "")
        if not name:
            continue
        pattern = str(proc.get("detect") or name)
        alive = process_running(pattern)
        must = bool(proc.get("must_run"))
        if must and not alive:
            failed_must_run += 1
        results.append(
            {
                "kind": "process",
                "name": name,
                "detail": proc.get("note") or "",
                "alive": alive,
                "must_run": must,
            }
        )

    if as_json:
        print(
            json.dumps(
                {"host": host, "results": results, "failed_must_run": failed_must_run},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"服务拓扑健康探针 @ {host}")
        for r in results:
            mark = OK if r["alive"] else BAD
            extra = f"  {r['detail']}" if r["detail"] else ""
            flag = " [must_run]" if r.get("must_run") else ""
            print(f"  {mark} {r['kind']:<7} {r['name']}{flag}{extra}")
        if failed_must_run:
            print(
                f"\n{BAD} {failed_must_run} 个 must_run 项缺失——可能是 scheduler 没起/服务没拉起。"
            )
        else:
            print(f"\n{OK} 所有 must_run 项在线。")

    return 1 if failed_must_run else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="服务拓扑健康探针")
    parser.add_argument("--host", default="127.0.0.1", help="探测目标主机（默认本机）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)
    return run(args.host, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
