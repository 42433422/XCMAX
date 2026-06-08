"""Mod 库内 manifest 快照（.modstore/snapshots），用于历史与回退。"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modman.manifest_util import read_manifest, save_manifest_validated

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _snapshots_dir(mod_root: Path) -> Path:
    d = mod_root / ".modstore" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def capture_manifest_snapshot(mod_root: Path, label: str = "") -> Dict[str, Any]:
    data, err = read_manifest(mod_root)
    if not data or err:
        raise ValueError(err or "无法读取 manifest")
    sid = uuid.uuid4().hex[:12]
    snap_path = _snapshots_dir(mod_root) / f"{sid}.json"
    payload: Dict[str, Any] = {
        "snap_id": sid,
        "created_at": int(time.time()),
        "label": (label or "").strip()[:240],
        "manifest": data,
    }
    snap_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"snap_id": sid, "created_at": payload["created_at"], "label": payload["label"]}


def list_manifest_snapshots(mod_root: Path) -> List[Dict[str, Any]]:
    d = mod_root / ".modstore" / "snapshots"
    if not d.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            o = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(o, dict) and o.get("snap_id"):
                out.append(
                    {
                        "snap_id": str(o.get("snap_id")),
                        "created_at": o.get("created_at"),
                        "label": str(o.get("label") or ""),
                    }
                )
        except (OSError, json.JSONDecodeError):
            continue
    return out


def restore_manifest_snapshot(mod_root: Path, snap_id: str) -> Tuple[Dict[str, Any], List[str]]:
    sid = (snap_id or "").strip()
    if not re.match(r"^[a-f0-9]{12}$", sid):
        raise ValueError("snap_id 无效")
    p = _snapshots_dir(mod_root) / f"{sid}.json"
    if not p.is_file():
        raise ValueError("快照不存在")
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"快照损坏: {e}") from e
    man = payload.get("manifest")
    if not isinstance(man, dict):
        raise ValueError("快照内 manifest 无效")
    warnings = save_manifest_validated(mod_root, man)
    return man, warnings


def bump_manifest_patch_version(mod_root: Path) -> Tuple[Dict[str, Any], List[str]]:
    """将 manifest.version 的 semver patch +1（非法则置为 1.0.0）。"""
    data, err = read_manifest(mod_root)
    if not data or err:
        raise ValueError(err or "无法读取 manifest")
    v = str(data.get("version") or "0.0.0").strip()
    m = _SEMVER.match(v)
    if m:
        data["version"] = f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}"
    else:
        data["version"] = "1.0.0"
    warnings = save_manifest_validated(mod_root, data)
    return data, warnings
