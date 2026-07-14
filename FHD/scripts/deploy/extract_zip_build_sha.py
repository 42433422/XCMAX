#!/usr/bin/env python3
"""Print gitSha/buildSha from the first build-info.json inside a ZIP."""
from __future__ import annotations

import json
import sys
import zipfile


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: extract_zip_build_sha.py <zip-path>", file=sys.stderr)
        return 2
    path = sys.argv[1]
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith("build-info.json"):
                data = json.loads(zf.read(name).decode("utf-8"))
                sha = str(data.get("gitSha") or data.get("buildSha") or "").strip()
                if sha:
                    print(sha)
                    return 0
    print("build-info.json with gitSha/buildSha not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
