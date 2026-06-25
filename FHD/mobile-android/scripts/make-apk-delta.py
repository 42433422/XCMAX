#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


MAGIC = b"XCAGIDLT1"
CMD_COPY = 0
CMD_DATA = 1
CMD_END = 2
FORMAT = "xcagi-copy-data-v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def append_copy(commands: list[tuple[str, int, bytes | int]], offset: int, length: int) -> None:
    if not commands:
        commands.append(("copy", offset, length))
        return
    kind, prev_offset, prev_payload = commands[-1]
    if kind == "copy" and isinstance(prev_payload, int) and prev_offset + prev_payload == offset:
        commands[-1] = ("copy", prev_offset, prev_payload + length)
    else:
        commands.append(("copy", offset, length))


def append_data(commands: list[tuple[str, int, bytes | int]], data: bytes) -> None:
    if not data:
        return
    if commands and commands[-1][0] == "data" and isinstance(commands[-1][2], bytes):
        commands[-1] = ("data", 0, commands[-1][2] + data)
    else:
        commands.append(("data", 0, data))


def build_patch(old_path: Path, new_path: Path, patch_path: Path, block_size: int) -> dict[str, int]:
    old = old_path.read_bytes()
    new = new_path.read_bytes()
    old_blocks: dict[bytes, list[int]] = {}
    for offset in range(0, max(len(old) - block_size + 1, 0), block_size):
        block = old[offset : offset + block_size]
        old_blocks.setdefault(hashlib.sha256(block).digest(), []).append(offset)

    commands: list[tuple[str, int, bytes | int]] = []
    pos = 0
    copied = 0
    literal = 0
    while pos < len(new):
        remaining = len(new) - pos
        if remaining >= block_size:
            block = new[pos : pos + block_size]
            match_offset = -1
            for offset in old_blocks.get(hashlib.sha256(block).digest(), []):
                if old[offset : offset + block_size] == block:
                    match_offset = offset
                    break
            if match_offset >= 0:
                append_copy(commands, match_offset, block_size)
                copied += block_size
                pos += block_size
                continue
            append_data(commands, block)
            literal += block_size
            pos += block_size
        else:
            tail = new[pos:]
            append_data(commands, tail)
            literal += len(tail)
            pos = len(new)

    patch_path.parent.mkdir(parents=True, exist_ok=True)
    with patch_path.open("wb") as f:
        f.write(MAGIC)
        for kind, offset, payload in commands:
            if kind == "copy":
                assert isinstance(payload, int)
                f.write(struct.pack(">BqI", CMD_COPY, offset, payload))
            else:
                assert isinstance(payload, bytes)
                f.write(struct.pack(">BI", CMD_DATA, len(payload)))
                f.write(payload)
        f.write(struct.pack(">B", CMD_END))
    return {"commands": len(commands), "copied": copied, "literal": literal}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build XCAGI copy/data APK delta.")
    parser.add_argument("--old", required=True, type=Path)
    parser.add_argument("--new", required=True, type=Path)
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--base-code", required=True, type=int)
    parser.add_argument("--base-name", required=True)
    parser.add_argument("--target-code", required=True, type=int)
    parser.add_argument("--target-name", required=True)
    parser.add_argument("--patch-url", required=True)
    parser.add_argument("--sku", default="enterprise")
    parser.add_argument("--block-size", default=32768, type=int)
    args = parser.parse_args()

    stats = build_patch(args.old, args.new, args.patch, args.block_size)
    patch_size = args.patch.stat().st_size
    apk_size = args.new.stat().st_size
    manifest = {
        "format_version": 1,
        "sku": args.sku,
        "target_version_code": args.target_code,
        "target_version_name": args.target_name,
        "patches": [
            {
                "format": FORMAT,
                "base_version_code": args.base_code,
                "base_version_name": args.base_name,
                "target_version_code": args.target_code,
                "target_version_name": args.target_name,
                "patch_url": args.patch_url,
                "patch_sha256": sha256_file(args.patch),
                "base_apk_sha256": sha256_file(args.old),
                "target_apk_sha256": sha256_file(args.new),
                "patch_size": patch_size,
                "apk_size": apk_size,
                "stats": stats,
            }
        ],
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ratio = patch_size / apk_size if apk_size else 1.0
    print(
        json.dumps(
            {
                "patch": str(args.patch),
                "manifest": str(args.manifest),
                "patch_size": patch_size,
                "apk_size": apk_size,
                "ratio": round(ratio, 4),
                **stats,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
