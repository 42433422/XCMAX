# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


@_facade().router.delete("/admin/catalog/{item_id}")
def api_admin_delete_catalog(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._require_admin)
):
    """管理员下架商品（幂等 soft-delete）。

    - 不再 hard delete 行：``Purchase`` / ``Review`` / ``Favorite`` / ``Entitlement``
      均通过 ``ForeignKey(catalog_items.id)`` 引用本表（部分 ``nullable=False``），
      硬删会破坏对账与历史，且重复点击会立即触发 404。
    - 改为打 ``compliance_status='delisted'`` + ``is_public=False``：公开目录
      （``CatalogItem.compliance_status != 'delisted'``）即不再展示，
      与前端按钮文案 “下架后 AI 市场将不再展示该商品” 语义一致。
    - 同步从 ``packages.json``（``/v1/packages`` 数据源）移除条目，删除其下
      ``catalog_data/files/`` 中的二进制；``market_files/`` 中的副本保留以便
      管理员后续 ``restore``。
    - 幂等：行不存在或已下架时返回 ``ok: True`` 且不报 404，避免前端列表因
      60s 缓存或多实例 (``upstream modstore_api``) 视图差异在重复点击时失败。
    """
    from modstore_server import catalog_store

    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            return {
                "ok": True,
                "deleted_id": item_id,
                "already_missing": True,
                "already_delisted": False,
                "removed_catalog_store": 0,
            }
        already_delisted = (item.compliance_status or "") == "delisted"
        pkg_id = item.pkg_id or ""
        if not already_delisted:
            item.is_public = False
            item.compliance_status = "delisted"
            item.delist_reason = "管理员手动下架"
            item.rank_score = 0.0
            session.commit()
    n_json = catalog_store.remove_package(pkg_id, version=None) if pkg_id else 0
    try:
        from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

        _invalidate_market_catalog_caches()
    except RECOVERABLE_ERRORS:
        pass
    return {
        "ok": True,
        "deleted_id": item_id,
        "already_missing": False,
        "already_delisted": already_delisted,
        "removed_catalog_store": n_json,
    }


@_facade().router.delete("/admin/employee-packs/{pkg_id:path}")
def api_admin_delete_employee_pack(
    pkg_id: str, user: _facade().User = _facade().Depends(_facade()._require_admin)
):
    """删除员工包：清掉本地 ``/v1`` catalog（``packages.json`` + ``files/``）中该 ``pkg_id`` 全部版本，并删除 ``catalog_items`` 中 ``artifact=employee_pack`` 的登记行。"""
    from modstore_server import catalog_store
    from modstore_server.duty_roster import all_planned_employee_ids

    pid = catalog_store.norm_pkg_id(pkg_id)
    if not pid:
        raise _facade().HTTPException(400, "pkg_id 无效")
    if pid in all_planned_employee_ids():
        raise _facade().HTTPException(
            403,
            "该员工包属于编制在岗岗位（duty_roster / 员工工作流管理矩阵），禁止删除。若确需移除，请先从 yuangon 编制与 duty_roster.py 中调整岗位列表后再操作。",
        )
    n_json = catalog_store.remove_package(pid, version=None)
    removed_db = False
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().CatalogItem)
            .filter(_facade().CatalogItem.artifact == "employee_pack")
            .all()
        )
        to_delete = [x for x in rows if catalog_store.norm_pkg_id(x.pkg_id) == pid]
        for item in to_delete:
            if item.stored_filename:
                file_path = _facade()._catalog_files_dir() / item.stored_filename
                if file_path.is_file():
                    file_path.unlink()
            session.delete(item)
        if to_delete:
            session.commit()
            removed_db = True
    return {
        "ok": True,
        "removed_catalog_store": n_json,
        "removed_db": removed_db,
        "already_absent": n_json == 0 and (not removed_db),
    }


@_facade().router.post("/admin/employee-packs/align-llm-from-deepseek")
async def api_admin_align_employee_llm_from_deepseek(
    dry_run: bool = _facade().Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """把仍为 ``provider=deepseek`` 的员工包批量改为当前环境下首个可用 LLM（平台密钥或作者 BYOK），并执行与 employee-save 相同的落盘。"""
    from modstore_server.employee_pack_deepseek_align import (
        align_catalog_employee_packs_llm_from_deepseek,
    )

    return await align_catalog_employee_packs_llm_from_deepseek(user, dry_run=dry_run)


@_facade().router.post("/admin/employee-packs/align-llm-to-auto")
async def api_admin_align_employee_llm_to_auto(
    dry_run: bool = _facade().Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """把仍为 ``provider=deepseek`` 的员工包改为 manifest 内 ``provider=model_name=auto``（工作台「自动」），与 employee-save 相同落盘。"""
    from modstore_server.employee_pack_deepseek_align import (
        align_catalog_employee_packs_llm_to_auto_sentinel,
    )

    return await align_catalog_employee_packs_llm_to_auto_sentinel(user, dry_run=dry_run)


@_facade().router.post("/admin/employee-packs/{pkg_id}/align-llm-to-auto-single")
async def api_admin_align_single_employee_llm_to_auto(
    pkg_id: str,
    dry_run: bool = _facade().Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """单个员工包的 LLM 绑定改为 ``provider=model_name=auto``，不再受 provider==deepseek 过滤。

    用于「无密钥」修复路径：管理员在 dg-stats 上直接点单条「改为自动」时调用。
    """
    from modstore_server.employee_pack_deepseek_align import (
        align_single_employee_pack_llm_to_auto,
    )

    result = await align_single_employee_pack_llm_to_auto(user, pkg_id, dry_run=dry_run)
    if not result.get("ok"):
        raise _facade().HTTPException(400, str(result.get("error") or "对齐失败"))
    return result


@_facade().router.post("/admin/employee-packs/purge-all")
def api_admin_purge_all_employee_packs(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """一键清空商店员工包，保留管理端上岗员工。

    上岗员工由 ``duty_roster.py``/编制矩阵管理；商店清理不得删除这些岗位包。"""
    from modstore_server import catalog_store

    removed_packages = 0
    removed_files = 0
    preserved_duty_packages = 0
    with catalog_store._lock:
        data = catalog_store.load_store()
        kept = []
        for r in data.get("packages") or []:
            if str((r or {}).get("artifact") or "") == "employee_pack":
                pid = str((r or {}).get("id") or (r or {}).get("pkg_id") or "").strip()
                if _facade().is_planned_duty_employee_pack(pid, "employee_pack"):
                    preserved_duty_packages += 1
                    kept.append(r)
                    continue
                fn = str((r or {}).get("stored_filename") or "").strip()
                if fn:
                    p = catalog_store.files_dir() / fn
                    if p.is_file():
                        try:
                            p.unlink()
                            removed_files += 1
                        except OSError:
                            pass
                removed_packages += 1
                continue
            kept.append(r)
        data["packages"] = kept
        catalog_store.save_store(data)
    removed_db = 0
    preserved_duty_db_rows = 0
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().CatalogItem)
            .filter(_facade().CatalogItem.artifact == "employee_pack")
            .all()
        )
        for item in rows:
            if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
                preserved_duty_db_rows += 1
                continue
            stored = (item.stored_filename or "").strip()
            if stored:
                p = _facade()._catalog_files_dir() / stored
                if p.is_file():
                    try:
                        p.unlink()
                        removed_files += 1
                    except OSError:
                        pass
            session.delete(item)
        if rows:
            session.commit()
            removed_db = len(rows)
    return {
        "ok": True,
        "removed_packages_json": removed_packages,
        "removed_db_rows": removed_db,
        "removed_files": removed_files,
        "preserved_duty_packages_json": preserved_duty_packages,
        "preserved_duty_db_rows": preserved_duty_db_rows,
    }


@_facade().router.post("/admin/mods/purge-all")
def api_admin_purge_all_mods(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """一键清空 mod 源码库：删除 ``library/`` 下所有 mod 目录（仅限带 manifest.json
    的子目录），并截断 ``user_mods`` 关联表。

    用于「重置仓库」语义——前端列表合并了多个数据源，逐条删除容易因 list 缓存、
    norm 不一致、user_mods 关联残留导致「老是删不完」。这里一次性原子清空。"""
    from modman.repo_config import load_config, resolved_library
    from modman.store import iter_mod_dirs
    from modstore_server.models import UserMod

    lib = resolved_library(load_config())
    removed_dirs: _facade().List[str] = []
    if lib.is_dir():
        for d in list(iter_mod_dirs(lib)):
            try:
                _facade().shutil.rmtree(d, ignore_errors=False)
                removed_dirs.append(d.name)
            except OSError:
                pass
    sf = _facade().get_session_factory()
    with sf() as session:
        removed_user_mod_rows = session.query(UserMod).delete()
        session.commit()
    return {
        "ok": True,
        "removed_dirs": removed_dirs,
        "removed_dir_count": len(removed_dirs),
        "removed_user_mod_rows": int(removed_user_mod_rows or 0),
    }
