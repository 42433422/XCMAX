"""Builtin 文档模板注册表(销售合同 / 价目表默认模板)。

Phase 3B 从 ``app.legacy.document_template_service`` 吸收而来。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_DEFAULT_ROWS: list[dict[str, Any]] = [
    {
        "slug": "sales_contract_default",
        "display_name": "销售合同默认模板",
        "role": "sales_contract_docx",
        "storage_relpath": "424/document_templates/sales_cn.docx",
        "is_default": True,
        "is_active": True,
        "sort_order": 100,
    },
    {
        "slug": "price_list_default",
        "display_name": "价目表默认模板",
        "role": "price_list_docx",
        "storage_relpath": "424/document_templates/price_list_default.docx",
        "is_default": True,
        "is_active": True,
        "sort_order": 100,
    },
]


def fhd_repo_root() -> Path:
    return Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()


def list_templates(role: str | None = None) -> list[dict[str, Any]]:
    rows = [dict(x) for x in _DEFAULT_ROWS]
    if role:
        rows = [r for r in rows if r.get("role") == role]
    return rows


def _candidate_paths_for_rel(rel: str) -> list[Path]:
    """仓库相对路径 + 运行时/内置 resources 回退（开箱种子）。"""
    rel_norm = (rel or "").replace("\\", "/").strip().lstrip("/")
    candidates: list[Path] = []
    if rel_norm:
        candidates.append((fhd_repo_root() / rel_norm).resolve())
    filename = Path(rel_norm).name if rel_norm else ""
    if filename:
        try:
            from app.utils.operational_errors import RECOVERABLE_ERRORS
            from app.utils.path_utils import get_app_data_dir, get_resource_path

            candidates.append(
                (Path(get_app_data_dir()) / "424" / "document_templates" / filename).resolve()
            )
            candidates.append((Path(get_app_data_dir()) / "templates" / filename).resolve())
            candidates.append(Path(get_resource_path("templates", filename)).resolve())
        except RECOVERABLE_ERRORS:
            pass
    # 去重保序
    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def resolve_template_path_with_meta(*, role: str, slug: str | None) -> tuple[Path, str]:
    rows = list_templates(role)
    hit = None
    if slug:
        hit = next((r for r in rows if r.get("slug") == slug), None)
    if hit is None:
        hit = next((r for r in rows if r.get("is_default")), rows[0] if rows else None)
    if hit is None:
        raise FileNotFoundError(f"no template for role={role}")
    rel = str(hit.get("storage_relpath") or "").strip()
    for p in _candidate_paths_for_rel(rel):
        if p.is_file():
            return p, rel
    # 保持旧行为：返回约定路径，由调用方报 FileNotFoundError
    return (fhd_repo_root() / rel).resolve(), rel


def _relpath_parts_ok(storage_relpath: str) -> bool:
    rel = (storage_relpath or "").replace("\\", "/").strip().lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if len(parts) < 2:
        return False
    if parts[0] == "424":
        return len(parts) >= 3 and parts[1] == "document_templates"
    if parts[0] == "mods":
        return "document_templates" in parts
    return False


def _resolve_storage_to_path(storage_relpath: str) -> Path | None:
    if not _relpath_parts_ok(storage_relpath):
        return None
    rel = (storage_relpath or "").replace("\\", "/").strip().lstrip("/")
    if rel.startswith("mods/"):
        from app.shell.xcagi_mods_discover import xcagi_root

        p = (xcagi_root() / rel).resolve()
        return p
    return (fhd_repo_root() / rel).resolve()


__all__ = [
    "fhd_repo_root",
    "list_templates",
    "resolve_template_path_with_meta",
]
