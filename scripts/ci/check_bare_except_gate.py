#!/usr/bin/env python3
"""门禁：关键路径禁止裸 ``except Exception: pass`` / 无日志吞错。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CRITICAL_PREFIXES = (
    "app/application/auth_app_service.py",
    "app/infrastructure/auth/",
    "app/utils/rate_limiter.py",
    "app/utils/deployment.py",
    "app/db/mod_dal.py",
)

BAD_PASS = re.compile(r"except\s+Exception\s*:\s*\n\s*pass\b", re.MULTILINE)
BAD_SILENT_RETURN = re.compile(
    r"except\s+Exception\s*:\s*\n\s*return\s+(False|None)\s*$", re.MULTILINE
)


def main() -> int:
    errors: list[str] = []
    for rel in CRITICAL_PREFIXES:
        path = ROOT / rel
        if path.is_file():
            files = [path]
        else:
            files = sorted(path.rglob("*.py")) if path.is_dir() else []
        for file in files:
            text = file.read_text(encoding="utf-8")
            if BAD_PASS.search(text):
                errors.append(f"{file.relative_to(ROOT)}: except Exception: pass")
            for m in BAD_SILENT_RETURN.finditer(text):
                errors.append(
                    f"{file.relative_to(ROOT)}: silent return {m.group(1)!r} after except Exception"
                )
    if errors:
        print("Bare except gate failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("Bare except gate OK (critical paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
