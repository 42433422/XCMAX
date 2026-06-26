#!/usr/bin/env python3
"""去重 .env：同一 key 保留最后一次出现（含 managed 块覆盖旧值）。"""

from __future__ import annotations

import sys
from pathlib import Path


def dedupe(text: str) -> str:
    lines = text.splitlines()
    order: list[str] = []
    vals: dict[str, str] = {}
    comments: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            comments.append("")
            continue
        if line.startswith("#") or "=" not in line:
            comments.append(raw)
            continue
        k, v = raw.split("=", 1)
        k = k.strip()
        if k not in vals:
            order.append(k)
        vals[k] = v
    out: list[str] = []
    for raw in comments:
        if raw == "":
            out.append("")
        else:
            out.append(raw)
    for k in order:
        out.append(f"{k}={vals[k]}")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    path = Path(sys.argv[1])
    backup = Path(f"{path}.dedupe.bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(dedupe(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    print(f"deduped {path} backup {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
