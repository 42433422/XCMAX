#!/usr/bin/env python3
"""构建太阳鸟交付种子：模板 xlsx + mod 侧库 + 主库花名册 JSON。

SSOT：FHD/delivery/sunbird-seed/
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED_ROOT = ROOT / "delivery" / "sunbird-seed"
DEFAULT_TEMPLATE_SRC = (
    ROOT.parent
    / "成都修茈科技有限公司"
    / "MODstore_deploy"
    / "examples"
    / "taiyangniao-attendance-employee"
    / "backend"
    / "templates"
    / "424"
    / "考勤-2026-3月份考勤统计表.xlsx"
)
TEMPLATE_NAME = "考勤-2026-3月份考勤统计表.xlsx"


def _ensure_template(seed_root: Path, template_src: Path | None) -> Path:
    dst_dir = seed_root / "424"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / TEMPLATE_NAME
    if dst.is_file():
        return dst
    src = template_src or DEFAULT_TEMPLATE_SRC
    if not src.is_file():
        raise FileNotFoundError(
            f"考勤模板不存在: {dst} 或 {src}\n"
            "请将太阳鸟固定模板放入 delivery/sunbird-seed/424/ 后重试。"
        )
    shutil.copy2(src, dst)
    return dst


def _build_mod_db(template: Path, db_path: Path) -> tuple[int, int, int, int]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.import_departments_employees import import_departments_and_employees

    return import_departments_and_employees(template, db_path, sync_ui_tables=True)


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
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def build_sunbird_seed(*, seed_root: Path | None = None, template_src: Path | None = None) -> dict:
    root = seed_root or SEED_ROOT
    template = _ensure_template(root, template_src)
    mod_db = root / "data" / "mod_dbs" / "taiyangniao_pro.db"
    dept_n, emp_n, prod_n, cust_n = _build_mod_db(template, mod_db)
    roster_path = root / "config" / "sunbird-roster.json"
    roster = _export_roster_json(template, roster_path)
    return {
        "seed_root": str(root),
        "template": str(template),
        "mod_db": str(mod_db),
        "roster_json": str(roster_path),
        "attendance_departments": dept_n,
        "attendance_employees": emp_n,
        "products": prod_n,
        "customers": cust_n,
        "roster_employees": len(roster.get("employees") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建太阳鸟交付种子数据")
    parser.add_argument("--seed-root", type=Path, default=SEED_ROOT)
    parser.add_argument("--template-src", type=Path, default=None)
    args = parser.parse_args()
    summary = build_sunbird_seed(seed_root=args.seed_root.resolve(), template_src=args.template_src)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
