#!/usr/bin/env python3
"""v10 全量版本收口：Mod manifest 版本与宿主/Mod 间依赖对齐 VERSION.md。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_MD = ROOT / "VERSION.md"
MOD_ROOTS = (
    ROOT / "mods",
    ROOT / "mod_templates",
    ROOT / "XCAGI" / "mods",
    ROOT / "MODstore" / "templates",
)

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
HOST_DEP_KEYS = ("xcagi",)


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = SEMVER_RE.match(text.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def read_host_version() -> str:
    text = VERSION_MD.read_text(encoding="utf-8")
    m = re.search(r"\*\*XCAGI 总版本\*\*\s*\|\s*`([^`]+)`", text)
    if not m:
        raise RuntimeError("cannot parse XCAGI 总版本 from VERSION.md")
    return m.group(1).strip()


def _bump_dep_value(value: str, want: str) -> str | None:
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r">=([\d.]+)", value.strip())
    if not m:
        return None
    cur = parse_version(m.group(1))
    tgt = parse_version(want)
    if cur is None or tgt is None or cur >= tgt:
        return None
    return f">={want}"


def _walk(obj: object, want: str, changes: list[str], path: str) -> object:
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            if k == "version" and isinstance(v, str):
                cur = parse_version(v)
                tgt = parse_version(want)
                if cur is not None and tgt is not None and cur < tgt:
                    changes.append(f"{path}.{k}: {v} -> {want}")
                    out[k] = want
                    continue
            if k in HOST_DEP_KEYS or (isinstance(k, str) and k.startswith("xcagi-")):
                if isinstance(v, str):
                    bumped = _bump_dep_value(v, want)
                    if bumped:
                        changes.append(f"{child_path}: {v} -> {bumped}")
                        out[k] = bumped
                        continue
            if k == "compat" and isinstance(v, dict):
                v = dict(v)
                mh = v.get("min_host_version")
                if isinstance(mh, str):
                    cur = parse_version(mh)
                    tgt = parse_version(want)
                    if cur is not None and tgt is not None and cur < tgt:
                        changes.append(f"{child_path}.min_host_version: {mh} -> {want}")
                        v["min_host_version"] = want
                out[k] = _walk(v, want, changes, child_path)
                continue
            out[k] = _walk(v, want, changes, child_path)
        return out
    if isinstance(obj, list):
        return [_walk(item, want, changes, f"{path}[{i}]") for i, item in enumerate(obj)]
    return obj


def sync_manifest(path: Path, want: str, *, dry_run: bool) -> list[str]:
    changes: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    updated = _walk(data, want, changes, path.relative_to(ROOT).as_posix())
    if changes and not dry_run:
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    want = read_host_version()
    all_changes: list[str] = []
    for root in MOD_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("manifest.json")):
            if "node_modules" in path.parts:
                continue
            all_changes.extend(sync_manifest(path, want, dry_run=args.dry_run))
    if not all_changes:
        print(f"v10 closure: nothing to change (target {want})")
        return 0
    prefix = "would update" if args.dry_run else "updated"
    print(f"v10 closure ({prefix}, target {want}):")
    for line in all_changes:
        print(f"  - {line}")
    print(f"total: {len(all_changes)} field(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
