#!/usr/bin/env python3
"""Mod SSOT：开发只改 FHD/mods，FHD/XCAGI/mods 为导出副本（打包/Docker 路径）。

用法:
  python scripts/dev/mods_ssot.py sync              # 全量同步 SSOT → XCAGI/mods
  python scripts/dev/mods_ssot.py sync --dry-run
  python scripts/dev/mods_ssot.py sync --mod xcagi-erp-domain-bridge
  python scripts/dev/mods_ssot.py check             # 检查漂移（CI / 发版前）
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSOT_ROOT = ROOT / "mods"
EXPORT_ROOT = ROOT / "XCAGI" / "mods"

SKIP_DIR_NAMES = frozenset({"__pycache__", "node_modules", ".git"})
SKIP_FILE_NAMES = frozenset({".DS_Store"})
# Binary data files ignored by XCAGI/.gitignore (*.xlsx, etc.) — skip in diff check
SKIP_SUFFIXES = frozenset({".xlsx", ".xls", ".csv.gz"})


def _skip_path(rel: Path) -> bool:
    if rel.name in SKIP_FILE_NAMES:
        return True
    if rel.suffix in (".pyc", *SKIP_SUFFIXES):
        return True
    return any(part in SKIP_DIR_NAMES for part in rel.parts)


def list_mod_ids(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if (entry / "manifest.json").is_file():
            out.append(entry.name)
    return out


def iter_relative_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _skip_path(rel):
            continue
        files[rel.as_posix()] = path
    return files


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compare_mod(mod_id: str) -> list[str]:
    src = SSOT_ROOT / mod_id
    dst = EXPORT_ROOT / mod_id
    issues: list[str] = []
    if not src.is_dir():
        issues.append(f"{mod_id}: SSOT 目录不存在")
        return issues
    if not dst.is_dir():
        issues.append(f"{mod_id}: 导出副本缺失（请运行 sync）")
        return issues

    src_files = iter_relative_files(src)
    dst_files = iter_relative_files(dst)

    for rel in sorted(set(src_files) - set(dst_files)):
        issues.append(f"{mod_id}: 导出副本缺少 {rel}")
    for rel in sorted(set(dst_files) - set(src_files)):
        issues.append(f"{mod_id}: 导出副本多余 {rel}")
    for rel in sorted(set(src_files) & set(dst_files)):
        if file_digest(src_files[rel]) != file_digest(dst_files[rel]):
            issues.append(f"{mod_id}: 内容不一致 {rel}")
    return issues


def sync_mod(mod_id: str, *, dry_run: bool, prune: bool) -> None:
    src = SSOT_ROOT / mod_id
    dst = EXPORT_ROOT / mod_id
    if not src.is_dir():
        raise SystemExit(f"SSOT 中无 Mod 目录: {src}")
    if not (src / "manifest.json").is_file():
        raise SystemExit(f"缺少 manifest.json: {src / 'manifest.json'}")

    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"[dry-run] sync {src} -> {dst}")
    else:
        dst.mkdir(parents=True, exist_ok=True)

    src_files = iter_relative_files(src)
    dst_files = iter_relative_files(dst) if dst.is_dir() else {}

    for rel, src_path in sorted(src_files.items()):
        target = dst / rel
        if dry_run:
            if rel not in dst_files:
                print(f"[dry-run] + {mod_id}/{rel}")
            elif file_digest(src_path) != file_digest(dst_files[rel]):
                print(f"[dry-run] ~ {mod_id}/{rel}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or not filecmp.cmp(src_path, target, shallow=False):
            shutil.copy2(src_path, target)

    if prune:
        for rel in sorted(set(dst_files) - set(src_files)):
            extra = dst / rel
            if dry_run:
                print(f"[dry-run] - {mod_id}/{rel}")
            elif extra.is_file():
                extra.unlink()


def cmd_check(mod_ids: list[str]) -> int:
    if not SSOT_ROOT.is_dir():
        print(f"SSOT 根目录不存在: {SSOT_ROOT}", file=sys.stderr)
        return 2
    targets = mod_ids or list_mod_ids(SSOT_ROOT)
    issues: list[str] = []
    for mod_id in targets:
        issues.extend(compare_mod(mod_id))

    export_only = sorted(set(list_mod_ids(EXPORT_ROOT)) - set(list_mod_ids(SSOT_ROOT)))
    for mod_id in export_only:
        issues.append(f"{mod_id}: 仅存在于 XCAGI/mods（SSOT 中无此 Mod，应删除或移回 mods/）")

    if issues:
        print("Mod SSOT 漂移（请改 FHD/mods 后运行 mods_ssot.py sync）：", file=sys.stderr)
        for line in issues:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"Mod SSOT 一致：{len(targets)} 个 Mod（{SSOT_ROOT.name} → {EXPORT_ROOT.relative_to(ROOT)}）")
    return 0


def cmd_sync(mod_ids: list[str], *, dry_run: bool, prune: bool) -> int:
    if not SSOT_ROOT.is_dir():
        print(f"SSOT 根目录不存在: {SSOT_ROOT}", file=sys.stderr)
        return 2
    targets = mod_ids or list_mod_ids(SSOT_ROOT)
    if not targets:
        print("SSOT 下未发现带 manifest.json 的 Mod", file=sys.stderr)
        return 2

    for mod_id in targets:
        sync_mod(mod_id, dry_run=dry_run, prune=prune)

    if dry_run:
        print(f"[dry-run] 将同步 {len(targets)} 个 Mod")
    else:
        print(f"已同步 {len(targets)} 个 Mod: {SSOT_ROOT.name} → {EXPORT_ROOT.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FHD Mod SSOT：mods/ 为唯一编辑源，XCAGI/mods 为导出副本。")
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="检查 SSOT 与导出副本是否一致")
    check_p.add_argument("--mod", action="append", dest="mods", metavar="MOD_ID", help="仅检查指定 Mod")

    sync_p = sub.add_parser("sync", help="将 FHD/mods 同步到 FHD/XCAGI/mods")
    sync_p.add_argument("--mod", action="append", dest="mods", metavar="MOD_ID", help="仅同步指定 Mod")
    sync_p.add_argument("--dry-run", action="store_true", help="只打印将变更的文件")
    sync_p.add_argument(
        "--prune",
        action="store_true",
        help="删除导出副本中 SSOT 已不存在的文件（默认只增改不删）",
    )

    args = parser.parse_args(argv)
    mod_ids = list(args.mods or [])

    if args.command == "check":
        return cmd_check(mod_ids)
    if args.command == "sync":
        return cmd_sync(mod_ids, dry_run=args.dry_run, prune=args.prune)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
