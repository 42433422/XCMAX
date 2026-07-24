#!/usr/bin/env python3
"""L1：ssot.yaml ↔ SSOT_INDEX.md 机器注册表互校验。

要求 SSOT_INDEX.md 含「## 机器注册表（ssot.yaml）」表格，且：
  1. 每个 enabled 域（ssot.yaml）都有一行，域名与 ssot 路径一致
  2. 表中没有多余/未知域名
  3. 表中路径与 ssot.yaml 的 ssot: 字段一致

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
REGISTRY = ROOT / "config" / "ssot.yaml"
INDEX = ROOT / "docs" / "SSOT_INDEX.md"
SECTION = "## 机器注册表（ssot.yaml）"
EXIT_OK, EXIT_DRIFT, EXIT_CONFIG = 0, 1, 2

ROW_RE = re.compile(
    r"^\|\s*`?([a-z0-9][a-z0-9\-_]*)`?\s*\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|$"
)


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
    if not INDEX.is_file():
        print(f"缺少 SSOT_INDEX: {INDEX}", file=sys.stderr)
        return EXIT_CONFIG
    text = INDEX.read_text(encoding="utf-8")
    if SECTION not in text:
        print(f"SSOT_INDEX.md 缺少章节: {SECTION}", file=sys.stderr)
        return EXIT_DRIFT

    yaml_domains = load_enabled_domains()
    index_rows = parse_machine_table(text)
    if not index_rows:
        print("机器注册表为空或无法解析", file=sys.stderr)
        return EXIT_DRIFT

    missing = sorted(set(yaml_domains) - set(index_rows))
    extra = sorted(set(index_rows) - set(yaml_domains))
    path_mismatch = sorted(
        name
        for name in set(yaml_domains) & set(index_rows)
        if yaml_domains[name] != index_rows[name]
    )

    ok = True
    if missing:
        ok = False
        print("ssot.yaml 有、机器注册表缺:", ", ".join(missing), file=sys.stderr)
    if extra:
        ok = False
        print("机器注册表有、ssot.yaml 无/未启用:", ", ".join(extra), file=sys.stderr)
    if path_mismatch:
        ok = False
        for name in path_mismatch:
            print(
                f"路径不一致 {name}: yaml={yaml_domains[name]!r} index={index_rows[name]!r}",
                file=sys.stderr,
            )
    if ok:
        print(
            f"registry-crosscheck OK：{len(yaml_domains)} 个 enabled 域与机器注册表一致"
        )
        return EXIT_OK
    print(
        "修复：同步 FHD/docs/SSOT_INDEX.md「机器注册表（ssot.yaml）」与 FHD/config/ssot.yaml",
        file=sys.stderr,
    )
    return EXIT_DRIFT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ssot.yaml ↔ SSOT_INDEX 互校验")
    parser.add_argument("action", choices=["check"], help="check")
    args = parser.parse_args(argv)
    if args.action == "check":
        return check()
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
