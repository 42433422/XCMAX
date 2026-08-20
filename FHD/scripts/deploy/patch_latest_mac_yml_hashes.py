#!/usr/bin/env python3
"""Overwrite sha512/size fields in latest-mac.yml with remotely measured values."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: patch_latest_mac_yml_hashes.py <yml> <sha512> <size>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    sha512 = sys.argv[2].strip()
    size = sys.argv[3].strip()
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("sha512:"):
            lines.append(f"{line.split('sha512:')[0]}sha512: {sha512}")
        elif line.strip().startswith("size:"):
            lines.append(f"{line.split('size:')[0]}size: {size}")
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
