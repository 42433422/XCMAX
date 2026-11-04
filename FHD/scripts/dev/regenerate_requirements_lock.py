#!/usr/bin/env python3
"""从本机已安装的 server-api 依赖重新生成服务端 lock。"""

from __future__ import annotations

import argparse
import re
import sys
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "requirements-server-api.txt"
LOCK = ROOT / "deploy" / "requirements-server-api.lock.txt"

PKG_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def parse_top_level(path: Path) -> list[str]:
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        base = line.split("[", 1)[0].strip()
        m = PKG_RE.match(base)
        if m:
            names.append(m.group(1))
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="只更新已安装的指定运行时包，保留其他锁定版本",
    )
    args = parser.parse_args(argv)
    installed: dict[str, str] = {}
    for dist in distributions():
        installed[normalize(dist.metadata["Name"])] = dist.version

    declared = parse_top_level(REQ)
    selected = {normalize(name) for name in args.package}
    if selected:
        if selected - {normalize(name) for name in declared} or not LOCK.is_file():
            print(
                "targeted regeneration requires declared packages and an existing lock",
                file=sys.stderr,
            )
            return 1
        lines = LOCK.read_text(encoding="utf-8").splitlines()
        locked = {
            normalize(line.split("==", 1)[0])
            for line in lines
            if "==" in line and not line.startswith("#")
        }
        if {normalize(name) for name in declared} - locked - selected:
            print(
                "existing lock is missing other runtime packages; regenerate the complete lock",
                file=sys.stderr,
            )
            return 1
        for pkg in declared:
            key = normalize(pkg)
            if key not in selected:
                continue
            ver = installed.get(key)
            if not ver:
                print(f"install missing package first: {pkg}", file=sys.stderr)
                return 1
            pin = f"{pkg}=={ver}"
            index = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if "==" in line and normalize(line.split("==", 1)[0]) == key
                ),
                None,
            )
            if index is None:
                lines.append(pin)
            else:
                lines[index] = pin
        LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"updated {LOCK} ({len(selected)} packages; other pins preserved)")
        return 0

    lines = [
        "# Top-level pins from local pip install (requirements-server-api.txt)",
        "# Regenerate: pip install -r requirements-server-api.txt && python3 scripts/dev/regenerate_requirements_lock.py",
    ]
    missing: list[str] = []
    for pkg in declared:
        ver = installed.get(normalize(pkg))
        if not ver:
            missing.append(pkg)
            continue
        lines.append(f"{pkg}=={ver}")

    if missing:
        print("install missing packages first:", ", ".join(missing), file=sys.stderr)
        print("  pip install -r requirements-server-api.txt", file=sys.stderr)
        return 1

    LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {LOCK} ({len(lines) - 2} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
