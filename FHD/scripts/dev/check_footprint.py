#!/usr/bin/env python3
"""门禁 2：足迹边界检查。

读取 --files-list 指定的文件清单（每行一个相对仓库根的路径），
对每个文件检查是否命中 HIGH_RISK_PATTERNS。
命中任何高风险路径 → 退出码 1，stderr 列出违规文件。
全部通过 → 退出码 0。

Usage:
    python check_footprint.py --files-list changed_files.txt
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

HIGH_RISK_PATTERNS = [
    "*.env",
    "*.env.*",
    "secrets/*",
    ".github/workflows/*",
    "nginx/*.conf",
    "*/nginx.conf",
    "requirements*.txt",
    "Dockerfile*",
    "docker-compose*.yml",
    "modstore_server/models*.py",
    "modstore_server/api/app_factory.py",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
]


def _is_high_risk(rel_path: str) -> bool:
    rp = rel_path.replace("\\", "/").lower()
    for pat in HIGH_RISK_PATTERNS:
        p = pat.lower()
        if fnmatch.fnmatch(rp, p) or fnmatch.fnmatch(rp, "**/" + p):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-list", required=True, help="文件清单，每行一个相对路径")
    args = parser.parse_args()

    files_list = Path(args.files_list)
    if not files_list.is_file():
        print(f"ERROR: files list not found: {files_list}", file=sys.stderr)
        return 2

    violations = []
    for line in files_list.read_text(encoding="utf-8").splitlines():
        rel = line.strip()
        if not rel:
            continue
        if _is_high_risk(rel):
            violations.append(rel)

    if violations:
        print("ERROR: high-risk paths in employee_pack:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print("OK: no high-risk paths in employee_pack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
