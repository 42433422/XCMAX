#!/usr/bin/env python3
"""兼容入口：ssot.yaml ↔ SSOT_INDEX.md 注册表契约校验。

正式实现位于 ``ssot_registry_contract.py``，校验所有域（不限 enabled）在
``SSOT_INDEX.md`` 的「执行注册名」列中恰好绑定一次且路径一致。保留本文件
是为了兼容已有脚本调用。

用法:
  python scripts/dev/ssot_registry_crosscheck.py check
退出码: 0=一致 1=漂移 2=配置错误
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]  # FHD/
sys.path.insert(0, str(ROOT))

from scripts.dev.ssot_registry_contract import parse_index_bindings, validate_registry_contract

REGISTRY = ROOT / "config" / "ssot.yaml"
INDEX = ROOT / "docs" / "SSOT_INDEX.md"
SECTION = "## 机器注册表（ssot.yaml）"
EXIT_OK, EXIT_DRIFT, EXIT_CONFIG = 0, 1, 2

ROW_RE = re.compile(r"^\|\s*`?([a-z0-9][a-z0-9\-_]*)`?\s*\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|$")


def load_enabled_domains() -> dict[str, str]:
    if not REGISTRY.is_file():
        print(f"缺少注册表: {REGISTRY}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for d in data.get("domains") or []:
        if not d.get("enabled", True):
            continue
        name = str(d.get("name") or "").strip()
        ssot = str(d.get("ssot") or "").strip()
        if not name or not ssot:
            print(f"无效域条目: {d!r}", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        out[name] = ssot
    return out


def parse_machine_table(text: str) -> dict[str, str]:
    lines = text.splitlines()
    in_section = False
    rows: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped == SECTION:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or re.match(r"^\|[\s\-:]+\|", stripped):
            continue
        if "域名" in stripped and "SSOT 路径" in stripped:
            continue
        m = ROW_RE.match(stripped)
        if not m:
            continue
        name, path, _gate = m.group(1), m.group(2).strip(), m.group(3)
        rows[name] = path
    return rows


def check() -> int:
    errors = validate_registry_contract()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return EXIT_DRIFT
    bindings, _ = parse_index_bindings()
    print(f"registry-crosscheck OK：{len(bindings)} 个执行域逐项一致")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ssot.yaml ↔ SSOT_INDEX 互校验")
    parser.add_argument("action", choices=["check"], help="check")
    args = parser.parse_args(argv)
    if args.action == "check":
        return check()
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
