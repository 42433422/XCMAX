#!/usr/bin/env python3
"""校验运行时依赖名；为 CI 从现有 uv.lock 读取测试工具链精确版本。"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "requirements-server-api.txt"
LOCK = ROOT / "ops" / "deploy" / "requirements-server-api.lock.txt"

PKG_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*([=<>!~]+.*)?$")


def normalize_name(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def parse_requirements(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        base = line.split("[", 1)[0].strip()
        m = PKG_RE.match(base)
        if m:
            names.add(normalize_name(m.group(1)))
    return names


def parse_lock(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " via " in line or line.startswith("    #"):
            continue
        pkg = line.split("==", 1)[0].strip()
        if pkg:
            names.add(normalize_name(pkg))
    return names


def locked_requirements(names: tuple[str, ...], lock: Path = ROOT / "uv.lock") -> list[str]:
    with lock.open("rb") as stream:
        packages = tomllib.load(stream)["package"]
    pins = []
    for name in names:
        versions = [p.get("version", "") for p in packages if p.get("name") == name]
        if len(versions) != 1 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", versions[0]):
            raise ValueError(f"uv.lock must contain exactly one stable {name} X.Y.Z version")
        pins.append(f"{name}=={versions[0]}")
    return pins


def locked_pytest_requirement(lock: Path = ROOT / "uv.lock") -> str:
    return locked_requirements(("pytest",), lock)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    pins = parser.add_mutually_exclusive_group()
    pins.add_argument("--pytest-pin", action="store_true")
    pins.add_argument("--test-toolchain-pins", action="store_true")
    args = parser.parse_args(argv)
    if args.pytest_pin or args.test_toolchain_pins:
        try:
            names = (
                ("pytest", "pytest-cov", "coverage") if args.test_toolchain_pins else ("pytest",)
            )
            print(" ".join(locked_requirements(names)))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"cannot read locked test requirements: {exc}", file=sys.stderr)
            return 1
        return 0
    if not REQ.is_file():
        print(f"missing {REQ}", file=sys.stderr)
        return 1
    if not LOCK.is_file():
        print(f"missing {LOCK}", file=sys.stderr)
        return 1

    req_names = parse_requirements(REQ)
    lock_names = parse_lock(LOCK)
    missing = sorted(req_names - lock_names)
    if missing:
        print(
            "lock file missing top-level packages from requirements-server-api.txt:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print(
            "Regenerate: pip install -r requirements-server-api.txt && pip freeze > ops/deploy/requirements-server-api.lock.txt",
            file=sys.stderr,
        )
        return 1
    print(f"requirements lock OK ({len(req_names)} top-level packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
