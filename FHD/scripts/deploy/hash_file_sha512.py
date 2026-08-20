#!/usr/bin/env python3
"""Print size and base64 sha512 for a local file (used on update server)."""

from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: hash_file_sha512.py <path>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return 1
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    print(path.stat().st_size)
    print(base64.b64encode(digest.digest()).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
