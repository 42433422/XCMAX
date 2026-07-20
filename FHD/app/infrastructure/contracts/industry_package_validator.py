"""Validate *-industry mod manifests against industry_package.schema.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = _FHD_ROOT / "contracts" / "industry_package.schema.json"
_BASELINE_PATH = _FHD_ROOT / "config" / "industry_baseline.json"
# 编辑源与导出副本双路径：FHD/mods/ 为 SSOT 编辑源，FHD/XCAGI/mods/ 为运行时导出副本。
# 与 app/infrastructure/mods/mod_manager.py "开发树常见双份 mods" 双份查找一致。
# 部分 industry 包（如 attendance-industry）已迁移至 XCAGI/mods/，需双路径扫描。
_MODS_ROOTS = (_FHD_ROOT / "mods", _FHD_ROOT / "XCAGI" / "mods")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_industry_manifest(path: Path | str) -> list[str]:
    """Return human-readable validation errors (empty list = OK)."""
    manifest_path = Path(path)
    errors: list[str] = []
    if not manifest_path.is_file():
        return [f"manifest not found: {manifest_path}"]

    try:
        data = _load_json(manifest_path)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    if not isinstance(data, dict):
        return ["manifest root must be an object"]

    import importlib.util

    if importlib.util.find_spec("jsonschema") is None:
        return ["jsonschema package required for industry manifest validation"]

    from jsonschema import Draft202012Validator

    schema = _load_json(_SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = ".".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{loc}: {err.message}")

    mod_id = str(data.get("id") or "").strip()
    industry_id = str((data.get("industry") or {}).get("id") or "").strip()
    if mod_id.endswith("-industry") and _BASELINE_PATH.is_file():
        baseline = _load_json(_BASELINE_PATH)
        packages = baseline.get("industry_packages") or {}
        matched_keys = [
            key
            for key, spec in packages.items()
            if isinstance(spec, dict) and str(spec.get("mod_id") or "").strip() == mod_id
        ]
        if not matched_keys:
            errors.append(
                f"industry baseline has no industry_packages entry with mod_id={mod_id!r}"
            )
        elif industry_id and industry_id not in matched_keys:
            errors.append(
                f"industry.id {industry_id!r} must match industry_baseline key "
                f"for mod_id={mod_id!r} (expected one of {matched_keys})"
            )

    return errors


def iter_industry_package_manifests() -> list[Path]:
    """Discover neutral industry package manifests under mods/ (编辑源 + 导出副本).

    双路径扫描避免 industry 包在 FHD/mods/ → FHD/XCAGI/mods/ 迁移期间漏检。
    同名包以编辑源 (FHD/mods/) 优先，导出副本仅补齐编辑源缺失的包。
    """
    out: list[Path] = []
    seen: set[str] = set()
    for mods_root in _MODS_ROOTS:
        if not mods_root.is_dir():
            continue
        for child in sorted(mods_root.iterdir()):
            if not child.is_dir() or child.name in seen:
                continue
            manifest = child / "manifest.json"
            if not manifest.is_file():
                continue
            if child.name.endswith("-industry"):
                out.append(manifest)
                seen.add(child.name)
    return out


__all__ = ["validate_industry_manifest", "iter_industry_package_manifests"]
