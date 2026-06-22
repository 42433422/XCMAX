#!/usr/bin/env python3
"""Pre-commit / CI: block newly added FHD/app/**/*_v[0-9]+.py files.

Application-layer ``*_app_service_v2.py`` files have been removed. The allowlist should
stay empty unless a real external protocol path must remain versioned.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "ci" / "v2_versioned_py_allowlist.txt"
VERSIONED_NAME = re.compile(r".*_v\d+\.py$", re.IGNORECASE)
APP_PREFIX = "FHD/app/"


def _load_allowlist() -> frozenset[str]:
    if not ALLOWLIST_PATH.is_file():
        raise SystemExit(f"Missing allowlist: {ALLOWLIST_PATH}")
    paths: set[str] = set()
    for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        paths.add(line.replace("\\", "/"))
    return frozenset(paths)


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _is_versioned_app_py(path: str) -> bool:
    p = _norm(path)
    if not p.startswith(APP_PREFIX):
        return False
    return bool(VERSIONED_NAME.match(Path(p).name))


def main(argv: list[str]) -> int:
    allowlist = _load_allowlist()
    paths = argv[1:] if len(argv) > 1 else []
    violations: list[str] = []
    for raw in paths:
        norm = _norm(raw)
        if not _is_versioned_app_py(norm):
            continue
        if norm in allowlist:
            continue
        violations.append(norm)
    if violations:
        print(
            "禁止新增 FHD/app/**/*_v[0-9]+.py。"
            " 请扩展既有无后缀模块或显式兼容层，勿复制 *_v2 文件。\n"
            "应用层 *_app_service_v2.py 已收敛删除。\n"
            + "\n".join(f"  - {v}" for v in sorted(violations))
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
