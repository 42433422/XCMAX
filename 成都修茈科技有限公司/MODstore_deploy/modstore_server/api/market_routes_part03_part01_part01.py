# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
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
                _facade().CatalogItem.pkg_id == pkg_id,
                _facade().CatalogItem.version == version,
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
            dest_path, dest_name = _facade()._new_catalog_file(suffix)
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
    "/admin/catalog/sync-from-xc-packages",
    summary="从 XC catalog_store 同步缺失条目到市场库",
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
    dest_path, dest_name = _facade()._new_catalog_file(suffix)
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
                _facade().CatalogItem.pkg_id == pkg_id,
                _facade().CatalogItem.version == version,
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
