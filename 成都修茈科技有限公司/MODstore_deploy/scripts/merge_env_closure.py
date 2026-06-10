#!/usr/bin/env python3
"""合并 .env 片段：后者覆盖前者；跳过空值。"""
from __future__ import annotations

import sys
from pathlib import Path


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def dump(data: dict[str, str], header: str = "") -> str:
    lines = []
    if header:
        lines.append(header.rstrip())
        lines.append("")
    for k in sorted(data.keys()):
        lines.append(f"{k}={data[k]}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: merge_env_closure.py <base.env> <overlay.env> <out.env>", file=sys.stderr)
        return 2
    base = parse(Path(sys.argv[1]))
    overlay = parse(Path(sys.argv[2]))
    for k, v in overlay.items():
        if v != "":
            base[k] = v
    Path(sys.argv[3]).write_text(
        dump(base, "# merged by scripts/merge_env_closure.py — do not commit"),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
