#!/usr/bin/env python3
"""Verify all assets referenced by index-*.js exist under dist/."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def main() -> int:
    dist = Path(os.environ.get("DIST_DIR", "market/dist"))
    if not dist.is_dir():
        print(f"dist not found: {dist}", file=sys.stderr)
        return 1
    assets = dist / "assets"
    index_files = sorted(assets.glob("index-*.js"))
    if not index_files:
        print("no index-*.js in assets/", file=sys.stderr)
        return 1
    idx = index_files[0]
    text = idx.read_text(encoding="utf-8", errors="ignore")
    refs = sorted(set(re.findall(r'"(assets/[^"]+)"', text)))
    missing = [r for r in refs if not (dist / r).is_file()]
    print(f"index={idx.name} refs={len(refs)} missing={len(missing)}")
    for m in missing:
        print(f"  MISSING {m}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
