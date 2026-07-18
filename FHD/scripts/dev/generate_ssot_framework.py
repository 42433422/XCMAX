#!/usr/bin/env python3
"""Generate the SSOT domain inventory in docs/SSOT_FRAMEWORK.md from config/ssot.yaml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

FHD_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = FHD_ROOT / "config" / "ssot.yaml"
FRAMEWORK = FHD_ROOT / "docs" / "SSOT_FRAMEWORK.md"
BEGIN = "<!-- BEGIN GENERATED SSOT DOMAIN INVENTORY -->"
END = "<!-- END GENERATED SSOT DOMAIN INVENTORY -->"


def _cell(value: object) -> str:
    text = "—" if value in (None, "") else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_inventory(domains: list[dict[str, Any]]) -> str:
    enabled = sum(bool(domain.get("enabled", True)) for domain in domains)
    disabled = len(domains) - enabled
    lines = [
        BEGIN,
        "> 本段由 `scripts/dev/generate_ssot_framework.py` 从 `config/ssot.yaml` 生成；请勿手改。",
        f"> 当前共 **{len(domains)}** 个域：**{enabled}** 个启用、**{disabled}** 个禁用。",
        "",
        "| 领域 | 启用 | owner | 模式 | SSOT | 派生件数 | check | sync |",
        "|---|---:|---|---|---|---:|---|---|",
    ]
    for domain in domains:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(domain.get("name")),
                    "是" if domain.get("enabled", True) else "否",
                    _cell(domain.get("owner")),
                    _cell(domain.get("mode")),
                    _cell(domain.get("ssot")),
                    str(len(domain.get("derived") or [])),
                    f"`{_cell(domain.get('check'))}`",
                    f"`{_cell(domain.get('sync'))}`",
                )
            )
            + " |"
        )
    lines.append(END)
    return "\n".join(lines)


def replace_inventory(document: str, inventory: str) -> str:
    if BEGIN not in document or END not in document:
        raise ValueError(f"generated inventory markers missing in {FRAMEWORK}")
    prefix, remainder = document.split(BEGIN, 1)
    _, suffix = remainder.split(END, 1)
    return prefix + inventory + suffix


def load_domains() -> list[dict[str, Any]]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    return list(data.get("domains") or [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="fail if the generated inventory drifted"
    )
    mode.add_argument("--apply", action="store_true", help="rewrite the generated inventory")
    args = parser.parse_args(argv)

    current = FRAMEWORK.read_text(encoding="utf-8")
    expected = replace_inventory(current, render_inventory(load_domains()))
    if current == expected:
        print("SSOT framework inventory is up to date.")
        return 0
    if args.check:
        print(
            "SSOT framework inventory drifted; run "
            "python scripts/dev/generate_ssot_framework.py --apply",
            file=sys.stderr,
        )
        return 1
    FRAMEWORK.write_text(expected, encoding="utf-8")
    print("Updated docs/SSOT_FRAMEWORK.md from config/ssot.yaml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
