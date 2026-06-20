#!/usr/bin/env python3
"""XCMAX SSOT 统一 CLI。

用法:
  python scripts/dev/ssot_cli.py list                 # 列所有域
  python scripts/dev/ssot_cli.py check [domain...]    # 跑 check（默认所有 enabled 域）
  python scripts/dev/ssot_cli.py sync [domain...]     # 跑 sync（默认 dry-run）
  python scripts/dev/ssot_cli.py sync <domain> --apply  # 真写
  python scripts/dev/ssot_cli.py drift                # 全域漂移报告（JSON）
  python scripts/dev/ssot_cli.py gate                 # CI 门禁（= check-all）
  python scripts/dev/ssot_cli.py enable <domain>      # 启用某域

退出码: 0=一致 1=漂移 2=配置错误 3=脚本执行失败
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev.ssot_plugins.base import find_domain, load_registry, run_command  # noqa: E402

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2
EXIT_EXEC = 3


def _parse_check_cmd(cmd_str: str) -> list[str]:
    """将 check 命令字符串解析为 argv（用 shell 词法）。"""
    return shlex.split(cmd_str)


def _run_domain_check(domain: dict[str, Any], *, silent: bool = False) -> tuple[int, str]:
    """跑单个域的 check，返回 (exit_code, message)。silent=True 时吞掉 subprocess 输出。"""
    check_cmd = domain.get("check")
    if not check_cmd:
        return EXIT_CONFIG, f"{domain['name']}: 无 check 命令"
    argv = _parse_check_cmd(check_cmd)
    cwd = ROOT
    code = run_command(argv, cwd=cwd, silent=silent)
    if code == 0:
        return EXIT_OK, f"{domain['name']}: OK"
    return EXIT_DRIFT, f"{domain['name']}: DRIFT (exit={code})"


def cmd_list(args: argparse.Namespace) -> int:
    domains = load_registry()
    print(f"{'name':<16} {'enabled':<8} {'mode':<14} {'ssot'}")
    print("-" * 70)
    for d in domains:
        enabled = "yes" if d.get("enabled", True) else "no"
        print(f"{d['name']:<16} {enabled:<8} {d.get('mode', '-'):<14} {d.get('ssot', '-')}")
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    domains = load_registry()
    targets = args.domains
    if targets:
        # 显式指定域：校验存在且 enabled
        to_run = []
        for name in targets:
            d = find_domain(domains, name)
            if d is None:
                print(f"错误：未知域 '{name}'", file=sys.stderr)
                return EXIT_CONFIG
            if not d.get("enabled", True):
                print(f"错误：域 '{name}' 未启用（先运行: ssot enable {name}）", file=sys.stderr)
                return EXIT_CONFIG
            to_run.append(d)
    else:
        to_run = [d for d in domains if d.get("enabled", True)]

    worst = EXIT_OK
    for d in to_run:
        code, msg = _run_domain_check(d)
        print(msg)
        if code != EXIT_OK:
            worst = code if code > worst else worst
    return worst


def cmd_gate(args: argparse.Namespace) -> int:
    """CI 门禁入口，等价于 check-all。"""
    return cmd_check(args)


def cmd_sync(args: argparse.Namespace) -> int:
    domains = load_registry()
    targets = args.domains or [d["name"] for d in domains if d.get("enabled", True)]
    worst = EXIT_OK
    for name in targets:
        d = find_domain(domains, name)
        if d is None or not d.get("enabled", True):
            print(f"跳过：域 '{name}' 不存在或未启用", file=sys.stderr)
            continue
        sync_cmd = d.get("sync")
        if not sync_cmd:
            print(f"{name}: 无 sync 命令（mode={d.get('mode')}）")
            continue
        if not args.apply:
            print(f"{name}: [dry-run] {sync_cmd}")
            continue
        argv = _parse_check_cmd(sync_cmd)
        code = run_command(argv, cwd=ROOT)
        print(f"{name}: sync exit={code}")
        if code != 0:
            worst = EXIT_EXEC
    if not args.apply:
        print("\n（dry-run 模式，未写盘。加 --apply 真写。）")
    return worst


def cmd_drift(args: argparse.Namespace) -> int:
    domains = load_registry(enabled_only=True)
    report = []
    for d in domains:
        code, msg = _run_domain_check(d, silent=True)
        report.append({"domain": d["name"], "status": "ok" if code == 0 else "drift", "message": msg})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return EXIT_OK if all(r["status"] == "ok" for r in report) else EXIT_DRIFT


def cmd_enable(args: argparse.Namespace) -> int:
    """将某域 enabled 改 true（改 ssot.yaml）。"""
    import yaml

    registry_path = ROOT / "config" / "ssot.yaml"
    with registry_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    found = False
    for d in data["domains"]:
        if d["name"] == args.domain:
            d["enabled"] = True
            found = True
            break
    if not found:
        print(f"错误：未知域 '{args.domain}'", file=sys.stderr)
        return EXIT_CONFIG
    with registry_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    print(f"已启用域 '{args.domain}'")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XCMAX SSOT 统一 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列所有域")

    check_p = sub.add_parser("check", help="跑 check")
    check_p.add_argument("domains", nargs="*", help="指定域（默认所有 enabled）")

    gate_p = sub.add_parser("gate", help="CI 门禁（= check-all）")
    gate_p.add_argument("domains", nargs="*", help="指定域（默认所有 enabled）")

    sync_p = sub.add_parser("sync", help="跑 sync")
    sync_p.add_argument("domains", nargs="*", help="指定域")
    sync_p.add_argument("--apply", action="store_true", help="真写（默认 dry-run）")

    sub.add_parser("drift", help="全域漂移报告（JSON）")

    enable_p = sub.add_parser("enable", help="启用某域")
    enable_p.add_argument("domain")

    args = parser.parse_args(argv)

    handlers = {
        "list": cmd_list,
        "check": cmd_check,
        "gate": cmd_gate,
        "sync": cmd_sync,
        "drift": cmd_drift,
        "enable": cmd_enable,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
