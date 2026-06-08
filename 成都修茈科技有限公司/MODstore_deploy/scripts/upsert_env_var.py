#!/usr/bin/env python3
"""Upsert KEY=value in a dotenv-style file (one line per key). Replaces first matching KEY= or # KEY= line, else appends."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: upsert_env_var.py <env_file> <VAR_NAME> <VAR_VALUE>", file=sys.stderr)
        return 2
    path, name, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if not name or "=" in name:
        print("bad VAR_NAME", file=sys.stderr)
        return 2
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    pat = re.compile(rf"^#?\s*{re.escape(name)}\s*=")
    out: list[str] = []
    done = False
    for line in lines:
        if pat.match(line):
            if not done:
                out.append(f"{name}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"OK: set {name} in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
