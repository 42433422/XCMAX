# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


def _existing_child_file(parent: _facade().Path, name: str) -> _facade().Path | None:
    try:
        with _facade().os.scandir(parent) as entries:
            for entry in entries:
                if (
                    entry.name == name
                    and (not entry.is_symlink())
                    and entry.is_file(follow_symlinks=False)
                ):
                    return _facade().Path(entry.path)
    except OSError:
        return None
    return None


def _existing_upload_session(session_id: str) -> _facade().Path | None:
    try:
        with _facade().os.scandir(_facade()._upload_chunks_dir()) as entries:
            for entry in entries:
                if (
                    entry.name == session_id
                    and (not entry.is_symlink())
                    and entry.is_dir(follow_symlinks=False)
                ):
                    return _facade().Path(entry.path)
    except OSError:
        return None
    return None


def _catalog_suffix(raw_name: str) -> str | None:
    raw = str(raw_name or "").lower()
    suffix = raw if raw in {".zip", ".xcmod", ".xcemp"} else _facade().Path(raw).suffix.lower()
    return {".zip": ".zip", ".xcmod": ".xcmod", ".xcemp": ".xcemp"}.get(suffix)


def _new_catalog_file(suffix: str) -> tuple[_facade().Path, str]:
    safe_suffix = {".zip": ".zip", ".xcmod": ".xcmod", ".xcemp": ".xcemp"}.get(suffix)
    if safe_suffix is None:
        raise ValueError("unsupported catalog suffix")
    name = f"{_facade().uuid.uuid4().hex}{safe_suffix}"
    return (_facade()._catalog_files_dir() / name, name)


def _compute_sha256(file_path: _facade().Path) -> str:
    """计算文件 SHA256。"""
    h = _facade().hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class UploadSession(_facade().BaseModel):
    """上传会话信息"""

    session_id: str
    file_name: str
    total_size: int
    chunk_size: int
    total_chunks: int


class UploadChunk(_facade().BaseModel):
    """文件块信息"""

    session_id: str
    chunk_index: int
    chunk_data: bytes


class CompleteUpload(_facade().BaseModel):
    """完成上传请求"""

    session_id: str
    pkg_id: str
    version: str
    name: str
    description: str = ""
    price: float = 0.0
    artifact: str = "mod"
    industry: str = "通用"


class CatalogItemAdminPatchDTO(_facade().BaseModel):
    """管理员调整目录行是否进入公开 AI 市场。"""

    is_public: bool


@_facade().router.post("/admin/catalog", summary="管理员上传 MOD 到市场（支持文件上传）")
async def api_admin_upload_catalog(
    pkg_id: str = _facade().Form(..., min_length=1, max_length=128),
    version: str = _facade().Form(..., min_length=1, max_length=32),
    name: str = _facade().Form(..., min_length=1, max_length=256),
    description: str = _facade().Form(""),
    price: float = _facade().Form(0, ge=0),
    artifact: str = _facade().Form("mod"),
    industry: str = _facade().Form("通用"),
    is_public: bool = _facade().Form(False),
    file: _facade().UploadFile = _facade().File(None),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = (
            session.query(_facade().CatalogItem)
            .filter(
                _facade().CatalogItem.pkg_id == pkg_id, _facade().CatalogItem.version == version
            )
            .first()
        )
        if existing:
            raise _facade().HTTPException(409, f"pkg_id '{pkg_id}' + version '{version}' 已存在")
        stored_filename = ""
        sha256 = ""
        if file and file.filename:
            suffix = _facade()._catalog_suffix(file.filename)
            if suffix is None:
                raise _facade().HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")
            (dest_path, dest_name) = _facade()._new_catalog_file(suffix)
            content = await file.read()
            if len(content) > 100 * 1024 * 1024:
                raise _facade().HTTPException(400, "文件过大（>100MB）")
            dest_path.write_bytes(content)
            stored_filename = dest_name
            sha256 = _facade()._compute_sha256(dest_path)
        ind = (industry or "").strip() or "通用"
        item = _facade().CatalogItem(
            pkg_id=pkg_id,
            version=version,
            name=name,
            description=description,
            price=price,
            author_id=user.id,
            artifact=artifact,
            industry=ind,
            stored_filename=stored_filename,
            sha256=sha256,
            is_public=bool(is_public),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {
            "ok": True,
            "id": item.id,
            "pkg_id": item.pkg_id,
            "stored_filename": item.stored_filename,
        }


@_facade().router.patch("/admin/catalog/{item_id}", summary="更新商品是否对 AI 市场公开展示")
def api_admin_patch_catalog_item(
    item_id: int,
    body: CatalogItemAdminPatchDTO,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """入库默认不公开展示；需要上架时 ``PATCH {"is_public": true}``。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        item.is_public = bool(body.is_public)
        session.commit()
    from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

    _invalidate_market_catalog_caches()
    return {"ok": True, "id": item_id, "is_public": bool(body.is_public)}


@_facade().router.post(
    "/admin/catalog/sync-from-xc-packages", summary="从 XC catalog_store 同步缺失条目到市场库"
)
def api_admin_sync_xc_catalog_packages(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """将 ``packages.json`` 中尚未出现在 ``catalog_items`` 的包插入数据库（可选复制文件）。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        out = _facade().catalog_sync.sync_packages_json_to_catalog_items(
            session, admin_user_id=user.id
        )
        session.commit()
    return {"ok": True, **out}


@_facade().router.get("/admin/catalog")
def api_admin_list_catalog(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = session.query(_facade().CatalogItem).count()
        rows = (
            session.query(_facade().CatalogItem)
            .order_by(_facade().CatalogItem.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": r.id,
                    "pkg_id": r.pkg_id,
                    "version": r.version,
                    "name": r.name,
                    "description": r.description,
                    "price": r.price,
                    "artifact": r.artifact,
                    "industry": getattr(r, "industry", None) or "通用",
                    "stored_filename": r.stored_filename,
                    "sha256": r.sha256,
                    "is_public": r.is_public,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    **_facade().employee_partition_meta(r.pkg_id, r.artifact),
                }
                for r in rows
            ],
            "total": total,
        }


@_facade().router.post("/admin/upload/initiate", summary="初始化分块上传")
def api_initiate_upload(
    file_name: str = _facade().Form(...),
    total_size: int = _facade().Form(...),
    chunk_size: int = _facade().Form(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """初始化分块上传会话"""
    session_id = str(_facade().uuid.uuid4())
    suffix = _facade()._catalog_suffix(file_name)
    if suffix is None:
        raise _facade().HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")
    if total_size <= 0 or chunk_size <= 0:
        raise _facade().HTTPException(400, "上传大小参数无效")
    total_chunks = (total_size + chunk_size - 1) // chunk_size
    if total_chunks > 10000:
        raise _facade().HTTPException(400, "文件分块过多")
    session_dir = _facade()._upload_chunks_dir() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    session_info = {
        "session_id": session_id,
        "suffix": suffix,
        "total_size": total_size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "created_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
    }
    with open(session_dir / "session.json", "w", encoding="utf-8") as f:
        _facade().json.dump(session_info, f)
    return {"ok": True, "session_id": session_id, "total_chunks": total_chunks}


@_facade().router.post("/admin/upload/chunk", summary="上传文件块")
async def api_upload_chunk(
    session_id: str = _facade().Form(...),
    chunk_index: int = _facade().Form(...),
    file: _facade().UploadFile = _facade().File(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """上传单个文件块"""
    session_dir = _facade()._existing_upload_session(session_id)
    if session_dir is None:
        raise _facade().HTTPException(404, "上传会话不存在")
    with open(session_dir / "session.json", "r", encoding="utf-8") as f:
        session_info = _facade().json.load(f)
    total_chunks = int(session_info["total_chunks"])
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise _facade().HTTPException(400, "无效的块索引")
    chunk_name = tuple((f"chunk_{i}" for i in range(total_chunks)))[chunk_index]
    chunk_path = session_dir / chunk_name
    content = await file.read()
    with open(chunk_path, "wb") as f:
        f.write(content)
    return {"ok": True, "chunk_index": chunk_index}


@_facade().router.post("/admin/upload/complete", summary="完成分块上传")
def api_complete_upload(
    session_id: str = _facade().Form(...),
    pkg_id: str = _facade().Form(...),
    version: str = _facade().Form(...),
    name: str = _facade().Form(...),
    description: str = _facade().Form(""),
    price: float = _facade().Form(0.0),
    artifact: str = _facade().Form("mod"),
    industry: str = _facade().Form("通用"),
    is_public: bool = _facade().Form(False),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """完成分块上传并合并文件"""
    session_dir = _facade()._existing_upload_session(session_id)
    if session_dir is None:
        raise _facade().HTTPException(404, "上传会话不存在")
    with open(session_dir / "session.json", "r", encoding="utf-8") as f:
        session_info = _facade().json.load(f)
    missing_chunks = []
    for i in range(session_info["total_chunks"]):
        chunk_path = session_dir / f"chunk_{i}"
        if not chunk_path.exists():
            missing_chunks.append(i)
    if missing_chunks:
        raise _facade().HTTPException(400, f"缺少文件块: {missing_chunks}")
    suffix = _facade()._catalog_suffix(str(session_info.get("suffix") or ""))
    if suffix is None:
        raise _facade().HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")
    (dest_path, dest_name) = _facade()._new_catalog_file(suffix)
    with open(dest_path, "wb") as out_file:
        for i in range(session_info["total_chunks"]):
            chunk_path = session_dir / f"chunk_{i}"
            with open(chunk_path, "rb") as in_file:
                out_file.write(in_file.read())
    sha256 = _facade()._compute_sha256(dest_path)
    import shutil

    shutil.rmtree(session_dir)
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = (
            session.query(_facade().CatalogItem)
            .filter(
                _facade().CatalogItem.pkg_id == pkg_id, _facade().CatalogItem.version == version
            )
            .first()
        )
        if existing:
            raise _facade().HTTPException(409, f"pkg_id '{pkg_id}' + version '{version}' 已存在")
        ind = (industry or "").strip() or "通用"
        item = _facade().CatalogItem(
            pkg_id=pkg_id,
            version=version,
            name=name,
            description=description,
            price=price,
            author_id=user.id,
            artifact=artifact,
            industry=ind,
            stored_filename=dest_name,
            sha256=sha256,
            is_public=bool(is_public),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {
            "ok": True,
            "id": item.id,
            "pkg_id": item.pkg_id,
            "stored_filename": item.stored_filename,
            "file_size": session_info["total_size"],
        }


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
    except Exception:
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
    from modstore_server.employee_pack_deepseek_align import align_single_employee_pack_llm_to_auto

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
def api_admin_purge_all_mods(user: _facade().User = _facade().Depends(_facade()._require_admin)):
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
