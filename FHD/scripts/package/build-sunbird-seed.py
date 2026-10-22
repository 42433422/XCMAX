#!/usr/bin/env python3
"""构建账号私有交付种子：模板 xlsx + 花名册 JSON。

输入和输出必须位于版本库之外的私有目录；源码中不保存客户数据。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.package.private_delivery_paths import private_path

TEMPLATE_NAME = "考勤-2026-3月份考勤统计表.xlsx"


def _ensure_template(seed_root: Path, template_src: Path | None) -> Path:
    dst_dir = seed_root / "424"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / TEMPLATE_NAME
    if template_src is None and dst.is_file():
        return dst
    src = private_path(template_src, "template_src")
    if not src.is_file():
        raise FileNotFoundError(f"private attendance template does not exist: {src}")
    if src != dst.resolve():
        shutil.copy2(src, dst)
    return dst


def _export_roster_json(template: Path, out_path: Path) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.import_departments_employees import _parse_workbook

    departments, employees, sheet_kind = _parse_workbook(template)
    payload = {
        "schema_version": 1,
        "source_template": f"424/{TEMPLATE_NAME}",
        "sheet_kind": sheet_kind,
        "departments": departments,
        "employees": employees,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def build_sunbird_seed(
    *, seed_root: Path | None = None, template_src: Path | None = None
) -> dict:
    root = private_path(seed_root, "seed_root")
    template = _ensure_template(root, template_src)
    roster_path = root / "config" / "sunbird-roster.json"
    roster = _export_roster_json(template, roster_path)
    return {
        "seed_root": str(root),
        "template": str(template),
        "roster_json": str(roster_path),
        "roster_employees": len(roster.get("employees") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建太阳鸟交付种子数据")
    parser.add_argument("--seed-root", type=Path, required=True)
    parser.add_argument("--template-src", type=Path, default=None)
    args = parser.parse_args()
    summary = build_sunbird_seed(
        seed_root=args.seed_root.resolve(), template_src=args.template_src
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
