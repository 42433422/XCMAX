"""Emit sorted ``modstore_server`` module names that fail ``mypy -p modstore_server``.

Usage::
    python scripts/export_mypy_ignore_modules.py [--toml-fragment]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def collect_modules(root: Path) -> tuple[list[str], int]:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "-p", "modstore_server"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    text = proc.stdout + "\n" + (proc.stderr or "")
    mods: set[str] = set()
    pattern = re.compile(r"^(modstore_server/[^:]+\.py):")
    for line in text.splitlines():
        norm = line.replace("\\", "/")
        m = pattern.match(norm)
        if not m:
            continue
        rel = Path(m.group(1))
        suffix = rel.as_posix().removeprefix("modstore_server/")
        mod = "modstore_server." + suffix.replace("/", ".")[:-3]
        mods.add(mod)
    return sorted(mods), proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--toml-fragment",
        action="store_true",
        help="Print a ``[[tool.mypy.overrides]]`` block for legacy ignore_errors modules",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    mods, rc = collect_modules(root)
    if args.toml_fragment:
        lines = ["[[tool.mypy.overrides]]", "module = ["]
        lines.extend([f'    "{m}",' for m in mods])
        lines.append("]")
        lines.append("ignore_errors = true")
        print("\n".join(lines))
        return 0
    print(json.dumps(mods, indent=2, ensure_ascii=False))
    print(f"# count={len(mods)} mypy_exit={rc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
