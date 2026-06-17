# -*- coding: utf-8 -*-
"""客户交付种子包安装。"""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.application.mod_store_catalog_app import catalog_download_to, catalog_get_json
from app.desktop_runtime.paths import get_desktop_data_dir
from app.mod_sdk.customer_delivery import (
    delivery_for_account_custom_mod,
    delivery_seed_package_for_mod,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_ALLOWED_TOP_LEVELS = {"424", "config", "data", "delivery-manifest.json"}


def _safe_member_relpath(name: str) -> Path | None:
    raw = str(name or "").replace("\\", "/").strip("/")
    if not raw:
        return None
    rel = PurePosixPath(raw)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"交付包包含非法路径: {name}")
    if rel.parts[0] not in _ALLOWED_TOP_LEVELS:
        raise ValueError(f"交付包包含未允许目录: {name}")
    if rel.parts[0] == "data" and len(rel.parts) >= 2 and rel.parts[1] != "mod_dbs":
        raise ValueError(f"交付包 data/ 下只允许 mod_dbs: {name}")
    return Path(*rel.parts)


def extract_customer_delivery_seed(zip_path: Path, data_root: Path) -> list[str]:
    """安全解压交付种子到桌面数据目录。"""
    root = data_root.resolve()
    extracted: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = _safe_member_relpath(info.filename)
            if rel is None:
                continue
            dest = (root / rel).resolve()
            if root not in dest.parents and dest != root:
                raise ValueError(f"交付包路径越界: {info.filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dest.open("wb") as out:
                out.write(src.read())
            extracted.append(rel.as_posix())
    return extracted


async def _resolve_version(pkg_id: str, version: str) -> str:
    ver = str(version or "").strip()
    if ver:
        return ver
    versions = await catalog_get_json(f"/packages/by-id/{pkg_id}/versions")
    rows = versions.get("versions") or []
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict):
            ver = str(first.get("version") or "").strip()
        else:
            ver = str(first or "").strip()
    return ver


async def install_customer_delivery_seed_package(
    *,
    mod_id: str,
    industry_id: str = "",
) -> dict[str, Any]:
    """按账号定制 Mod 下载并应用客户交付种子包。"""
    mid = str(mod_id or "").strip()
    iid = str(industry_id or "").strip()
    if not mid:
        return {"success": False, "message": "缺少 mod_id"}

    delivery = delivery_for_account_custom_mod(mid, iid)
    pkg = delivery_seed_package_for_mod(mid, iid)
    if not delivery or not pkg:
        return {
            "success": True,
            "message": "该账号定制 Mod 未配置交付种子包",
            "mod_id": mid,
            "applied": False,
            "skipped": True,
        }

    pkg_id = str(pkg.get("pkg_id") or "").strip()
    version = await _resolve_version(pkg_id, str(pkg.get("version") or "").strip())
    if not pkg_id or not version:
        return {"success": False, "message": "交付种子包缺少 pkg_id/version", "mod_id": mid}

    tmp = tempfile.NamedTemporaryFile(prefix="xcagi-delivery-seed-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        await catalog_download_to(f"/packages/{pkg_id}/{version}/download", tmp_path)
        data_root = Path(get_desktop_data_dir()).resolve()
        extracted = extract_customer_delivery_seed(tmp_path, data_root)

        applied = False
        apply_kind = str(pkg.get("apply") or "").strip()
        if apply_kind == "sunbird_roster":
            from app.desktop_runtime.sunbird_delivery_seed import apply_sunbird_roster_seed_if_needed

            applied = bool(apply_sunbird_roster_seed_if_needed(data_root))

        return {
            "success": True,
            "message": "客户交付种子包已下载并应用",
            "mod_id": mid,
            "delivery_id": str((delivery or {}).get("delivery_id") or ""),
            "package": {"pkg_id": pkg_id, "version": version, "artifact": pkg.get("artifact")},
            "data_root": str(data_root),
            "extracted_files": extracted,
            "applied": applied,
        }
    except RECOVERABLE_ERRORS as exc:
        return {
            "success": False,
            "message": f"客户交付种子包安装失败：{exc}",
            "mod_id": mid,
        }
    finally:
        try:
            if tmp_path.exists():
                os.unlink(tmp_path)
        except OSError:
            pass


__all__ = [
    "extract_customer_delivery_seed",
    "install_customer_delivery_seed_package",
]
