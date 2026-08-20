#!/usr/bin/env python3
# mypy: disable-error-code="return-value"
"""生产环境 Neuro Bus 开关验证脚本。

通过 SSH 到 CVM 读取 /root/fhd-full.env,校验 Neuro Bus 7 个可靠性开关全部启用。

用法::
    python scripts/dev/verify_neuro_bus_prod.py                    # 验证生产环境
    python scripts/dev/verify_neuro_bus_prod.py --dry-run          # 模拟验证(不实际 SSH)
    python scripts/dev/verify_neuro_bus_prod.py --json             # 输出 JSON 格式
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Dict, List

# 生产 CVM 配置(与 cicd-e2e-prompt.md / fhd-deploy.yml 一致)
DEFAULT_HOST = "119.27.178.147"
DEFAULT_USER = "root"
DEFAULT_ENV_FILE = "/root/fhd-full.env"

# Neuro Bus 7 个可靠性开关(NEURO_OPERATIONS.md 推荐)
NEURO_BUS_VARS = [
    "XCAGI_NEURO_BUS_DEDUP",
    "XCAGI_NEURO_BUS_CIRCUIT",
    "XCAGI_NEURO_BUS_RATE_LIMIT",
    "XCAGI_NEURO_BUS_TRACE",
    "XCAGI_NEURO_BUS_LIFELINE",
    "XCAGI_NEURO_BUS_DLQ_AUTO",
    "XCAGI_NEURO_BUS_SLA_LOG",
]


def ssh_read_env(host: str, user: str, env_file: str) -> Dict[str, str]:
    """通过 SSH 读取远程 env 文件并解析为 dict。"""
    cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
        f"{user}@{host}",
        f"cat {env_file}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"SSH 失败: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("SSH 超时(15s)")
    except FileNotFoundError:
        raise RuntimeError("ssh 命令不存在,请确保已安装 OpenSSH 客户端")

    # 解析 env 文件(只取简单的 KEY=VALUE 行)
    env_dict = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        env_dict[key.strip()] = value.strip().strip("\"'")

    return env_dict


def mock_read_env() -> Dict[str, str]:
    """模拟读取 env(用于 --dry-run 或无 SSH 环境)。"""
    return dict.fromkeys(NEURO_BUS_VARS, "1")


def verify_neuro_bus(env_dict: Dict[str, str]) -> List[Dict[str, str]]:
    """验证 Neuro Bus 开关,返回结果列表。"""
    results = []
    for var in NEURO_BUS_VARS:
        value = env_dict.get(var, "")
        ok = value == "1"
        results.append(
            {
                "var": var,
                "value": value,
                "ok": ok,
                "expected": "1",
            }
        )
    return results


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("FHD_PUSH_HOST", DEFAULT_HOST),
        help=f"CVM 主机地址(默认 {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("FHD_PUSH_USER", DEFAULT_USER),
        help=f"SSH 用户(默认 {DEFAULT_USER})",
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f"远程 env 文件路径(默认 {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟验证(不实际 SSH)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 格式",
    )
    args = parser.parse_args(argv)

    # 读取 env
    try:
        if args.dry_run:
            env_dict = mock_read_env()
        else:
            env_dict = ssh_read_env(args.host, args.user, args.env_file)
    except RuntimeError as e:
        if args.json:
            print(json.dumps({"error": str(e), "ok": False}, ensure_ascii=False))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # 验证
    results = verify_neuro_bus(env_dict)
    all_ok = all(r["ok"] for r in results)

    # 输出
    if args.json:
        output = {
            "host": args.host,
            "env_file": args.env_file,
            "ok": all_ok,
            "vars": results,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Neuro Bus 开关验证 (主机: {args.host}):\n")
        for r in results:
            status = "✅" if r["ok"] else "❌"
            print(f"  {status} {r['var']}: {r['value']} (期望: {r['expected']})")

        print()
        if all_ok:
            print("✅ 所有 Neuro Bus 开关已正确启用")
        else:
            print("❌ 部分开关未启用,请检查 /root/fhd-full.env")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
