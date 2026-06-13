# -*- coding: utf-8 -*-
"""L2 行业中性 Mod：安装包 industry-seeds 只读池 → 选行业后单拷到 userData/mods。"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.mod_sdk.industry_baseline import load_industry_baseline_document
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in seq:
        mid = str(raw or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def open_industry_seed_mod_ids() -> list[str]:
    """onboarding_open_industry_ids 对应的中性行业 mod_id（L2 池成员）。"""
    doc = load_industry_baseline_document()
    open_ids = _dedupe([str(x) for x in (doc.get("onboarding_open_industry_ids") or []) if x])
    packages = (
        doc.get("industry_packages") if isinstance(doc.get("industry_packages"), dict) else {}
    )
    out: list[str] = []
    for iid in open_ids:
        row = packages.get(iid) if isinstance(packages.get(iid), dict) else {}
        mid = str(row.get("mod_id") or "").strip()
        if mid:
            out.append(mid)
    return _dedupe(out)


def industry_mod_id_for(industry_id: str) -> str | None:
    """行业 id → industry_packages.mod_id；未知则 None。"""
    iid = str(industry_id or "").strip()
    if not iid:
        return None
    doc = load_industry_baseline_document()
    packages = (
        doc.get("industry_packages") if isinstance(doc.get("industry_packages"), dict) else {}
    )
    row = packages.get(iid)
    if not isinstance(row, dict):
        return None
    mid = str(row.get("mod_id") or "").strip()
    return mid or None


def resolve_industry_or_mod_id(raw: str) -> tuple[str | None, str | None]:
    """
    解析请求中的 industry_id 或 mod_id。
    返回 (industry_id, mod_id)；mod_id 优先来自 industry_packages 或 open 池匹配。
    """
    key = str(raw or "").strip()
    if not key:
        return None, None
    mid = industry_mod_id_for(key)
    if mid:
        return key, mid
    open_ids = set(open_industry_seed_mod_ids())
    if key in open_ids:
        for iid in load_industry_baseline_document().get("onboarding_open_industry_ids") or []:
            if industry_mod_id_for(str(iid)) == key:
                return str(iid), key
        return None, key
    return None, None


def bundled_industry_seeds_dir() -> Path | None:
    """PyInstaller industry-seeds/、开发树或 XCAGI_INDUSTRY_SEEDS_DIR。"""
    for raw in (
        os.environ.get("XCAGI_INDUSTRY_SEEDS_DIR"),
        os.environ.get("XCAGI_STAGED_INDUSTRY_SEEDS_DIR"),
    ):
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                return p
    import sys

    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", ""))
        for name in ("industry-seeds",):
            p = base / name
            if p.is_dir():
                return p
    cwd = Path.cwd()
    for rel in ("industry-seeds", "build/staged-industry-seeds-enterprise"):
        p = (cwd / rel).resolve()
        if p.is_dir():
            return p
    here = Path(__file__).resolve()
    for parent in here.parents:
        trial = parent / "industry-seeds"
        if trial.is_dir():
            return trial
        staged = parent / "build" / "staged-industry-seeds-enterprise"
        if staged.is_dir():
            return staged
    return None


def _resolve_seed_source(mod_id: str, pool: Path) -> Path | None:
    trial = pool / mod_id
    if trial.is_dir():
        return trial
    return None


def other_open_industry_mod_ids(keep_mod_id: str) -> list[str]:
    """除 keep 外，open 行业池中的其它中性 mod_id（换行业清理用）。"""
    keep = str(keep_mod_id or "").strip()
    return [mid for mid in open_industry_seed_mod_ids() if mid and mid != keep]


def deactivate_other_open_industry_mods(
    keep_mod_id: str, *, remove_files: bool = True
) -> list[dict[str, Any]]:
    """卸载并可选删除其它 open 行业中性 Mod（不触碰 L3 legacy 定制 id）。"""
    from app.infrastructure.mods.mod_manager import get_mod_manager

    mm = get_mod_manager()
    results: list[dict[str, Any]] = []
    for mod_id in other_open_industry_mod_ids(keep_mod_id):
        try:
            mm.unload_mod(mod_id)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("unload open industry mod %s failed: %s", mod_id, exc)
        removed = False
        if remove_files:
            dest = Path(mm.mods_root) / mod_id
            if dest.is_dir():
                try:
                    shutil.rmtree(dest)
                    removed = True
                except OSError as exc:
                    logger.warning("remove industry mod dir %s failed: %s", dest, exc)
        results.append({"mod_id": mod_id, "unloaded": True, "removed_files": removed})
    return results


def seed_industry_mod(industry_id: str) -> dict[str, Any]:
    """
    从 industry-seeds 池复制单个行业 Mod 到 userData/mods 并 load_mod。
    industry_id 可为行业名或 mod_id。
    """
    iid, mod_id = resolve_industry_or_mod_id(industry_id)
    if not mod_id:
        return {
            "success": False,
            "status": "invalid",
            "industry_id": iid,
            "mod_id": None,
            "source": None,
            "message": f"无法解析行业或 Mod：{industry_id}",
        }

    from app.infrastructure.mods.mod_manager import get_mod_manager

    mm = get_mod_manager()
    dst = Path(mm.mods_root) / mod_id
    pool = bundled_industry_seeds_dir()

    if dst.is_dir():
        loaded = False
        try:
            loaded = bool(mm.load_mod(mod_id))
        except RECOVERABLE_ERRORS as exc:
            logger.warning("load_mod existing industry seed %s: %s", mod_id, exc)
        payload = {
            "success": loaded or dst.is_dir(),
            "status": "already_present",
            "industry_id": iid,
            "mod_id": mod_id,
            "source": "user_mods",
            "message": "行业 Mod 已存在",
            "loaded": loaded,
        }
        payload["deactivated"] = deactivate_other_open_industry_mods(mod_id)
        return payload

    if pool is None:
        return {
            "success": False,
            "status": "pool_missing",
            "industry_id": iid,
            "mod_id": mod_id,
            "source": None,
            "message": "安装包未包含 industry-seeds 池，请从扩展市场安装",
        }

    src = _resolve_seed_source(mod_id, pool)
    if src is None:
        return {
            "success": False,
            "status": "not_in_pool",
            "industry_id": iid,
            "mod_id": mod_id,
            "source": str(pool),
            "message": f"行业种子池中无 {mod_id}，请从扩展市场安装",
        }

    try:
        os.makedirs(mm.mods_root, exist_ok=True)
        shutil.copytree(src, dst)
    except OSError as exc:
        return {
            "success": False,
            "status": "copy_error",
            "industry_id": iid,
            "mod_id": mod_id,
            "source": str(src),
            "message": f"复制行业种子失败：{exc}",
        }

    loaded = False
    try:
        mm.invalidate_scan_cache()
        loaded = bool(mm.load_mod(mod_id))
    except RECOVERABLE_ERRORS as exc:
        logger.warning("load_mod after industry seed %s: %s", mod_id, exc)

    return {
        "success": loaded,
        "status": "seeded" if loaded else "seeded_load_failed",
        "industry_id": iid,
        "mod_id": mod_id,
        "source": str(src),
        "message": "行业 Mod 已从种子池安装" if loaded else "已复制但加载失败",
        "loaded": loaded,
        "deactivated": deactivate_other_open_industry_mods(mod_id) if loaded else [],
    }


async def install_industry_seed_with_fallback(industry_id: str) -> dict[str, Any]:
    """池内 seed 优先；失败则 Catalog 安装。"""
    result = seed_industry_mod(industry_id)
    if result.get("success"):
        keep = str(result.get("mod_id") or "")
        if keep:
            result["deactivated"] = deactivate_other_open_industry_mods(keep)
        return result

    mod_id = str(result.get("mod_id") or "").strip()
    status = str(result.get("status") or "")
    if not mod_id or status not in ("pool_missing", "not_in_pool"):
        return result

    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        catalog = await _install_from_catalog(mod_id, "", activate=True)
        if catalog.success:
            deactivate_other_open_industry_mods(mod_id)
            return {
                "success": True,
                "status": "catalog",
                "industry_id": result.get("industry_id"),
                "mod_id": mod_id,
                "source": "catalog",
                "message": catalog.message or "已从扩展市场安装行业 Mod",
                "catalog": True,
            }
        return {
            **result,
            "success": False,
            "status": "catalog_failed",
            "message": catalog.message or result.get("message"),
        }
    except RECOVERABLE_ERRORS as exc:
        return {
            **result,
            "success": False,
            "status": "catalog_failed",
            "message": str(exc),
        }


__all__ = [
    "open_industry_seed_mod_ids",
    "industry_mod_id_for",
    "resolve_industry_or_mod_id",
    "bundled_industry_seeds_dir",
    "other_open_industry_mod_ids",
    "deactivate_other_open_industry_mods",
    "seed_industry_mod",
    "install_industry_seed_with_fallback",
]
