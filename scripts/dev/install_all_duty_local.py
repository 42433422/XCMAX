#!/usr/bin/env python3
"""将编制内全部 employee_pack 从本机 MODstore catalog_data 安装到 mods/_employees/。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.mods.employee_registry import get_employee_registry
from app.mod_sdk.duty_roster import all_planned_duty_employee_ids


def _default_files_dir() -> Path:
    repo = ROOT.parent / "成都修茈科技有限公司" / "MODstore_deploy" / "modstore_server" / "catalog_data" / "files"
    return repo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files-dir",
        type=Path,
        default=_default_files_dir(),
        help="MODstore catalog_data/files 目录（含 *.xcemp）",
    )
    args = parser.parse_args()
    files_dir: Path = args.files_dir
    if not files_dir.is_dir():
        print(f"catalog files 目录不存在: {files_dir}", file=sys.stderr)
        return 1

    planned = list(all_planned_duty_employee_ids())
    reg = get_employee_registry()
    ok, fail = 0, []
    for pid in planned:
        matches = sorted(files_dir.glob(f"{pid}-*.xcemp"))
        if not matches:
            fail.append((pid, "无 xcemp"))
            continue
        success, message = reg.install_from_package(str(matches[-1]), verify_signature=False)
        if success:
            ok += 1
        else:
            fail.append((pid, message))

    local = {p.name for p in (ROOT / "mods" / "_employees").iterdir() if p.is_dir()}
    missing = sorted(set(planned) - local)
    print(f"编制 {len(planned)} · 本次成功 {ok} · 失败 {len(fail)} · 本地已装 {len(local & set(planned))}/{len(planned)}")
    for pid, msg in fail:
        print(f"  FAIL {pid}: {msg}")
    if missing:
        print("仍缺:", ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
