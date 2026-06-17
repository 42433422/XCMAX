#!/usr/bin/env python3
"""构建时生成 mods-index.json，运行时 scan_mods 可跳过全量 listdir。"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _target_mods_root() -> Path:
    for key in ("XCAGI_STAGED_MODS_DIR", "XCAGI_MODS_ROOT", "XCAGI_MODS_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            return path
        raise SystemExit(f"{key} is set but not a directory: {path}")
    return (ROOT / "mods").resolve()


def _mods_scan_fingerprint(mods_root: Path) -> str:
    parts: list[str] = [str(mods_root)]
    for entry in sorted(mods_root.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("_") or not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if manifest_path.is_file():
            parts.append(f"{entry.name}:{manifest_path.stat().st_mtime:.6f}")
    return "|".join(parts)


def _read_mod_id(mod_path: Path) -> str | None:
    manifest_path = mod_path / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: skip invalid manifest {manifest_path}: {exc}")
        return None
    mod_id = str(data.get("id") or "").strip()
    return mod_id or None


def main() -> int:
    mods_root = _target_mods_root()
    seen: set[str] = set()
    rows = []
    for entry in sorted(mods_root.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("_") or not entry.is_dir():
            continue
        mod_id = _read_mod_id(entry)
        if not mod_id or mod_id in seen:
            continue
        seen.add(mod_id)
        mod_path = str(entry)
        manifest = os.path.join(mod_path, "manifest.json")
        mtime = os.path.getmtime(manifest) if os.path.isfile(manifest) else 0
        rows.append(
            {
                "id": mod_id,
                "mod_path": mod_path,
                "manifest_mtime": mtime,
            }
        )
    payload = {
        "version": 1,
        "fingerprint": _mods_scan_fingerprint(mods_root),
        "mods_root": str(mods_root),
        "mods": rows,
    }
    out = mods_root / "mods-index.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(rows)} mods)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
