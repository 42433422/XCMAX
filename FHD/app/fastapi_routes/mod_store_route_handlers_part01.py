# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mod_store_routes")


async def _install_from_catalog(
    pkg_id: str,
    version: str,
    activate: bool = True,
    *,
    authorization: str = "",
    download_path: str = "",
    expected_sha256: str = "",
    verify_signature: bool = True,
) -> _facade().ModStoreInstallResult:
    from app.mod_sdk.host_foundation import (
        install_aux_employee_pack_from_repo_seed,
        is_aux_employee_pack_mod_id,
        is_host_foundation_employee_pack,
    )

    if is_host_foundation_employee_pack(pkg_id):
        return await _facade()._install_host_foundation_internal(edition=None)
    if is_aux_employee_pack_mod_id(pkg_id):
        ok, message = install_aux_employee_pack_from_repo_seed(pkg_id, activate=activate)
        if ok:
            return _facade().ModStoreInstallResult(
                success=True, message=message, data={"id": pkg_id}
            )
        _facade().logger.info(
            "aux employee seed install failed for %s: %s; try catalog", pkg_id, message
        )
    if not pkg_id:
        raise _facade().HTTPException(status_code=400, detail="缺少 pkg_id")
    if not version and not download_path:
        headers = {"Authorization": authorization} if authorization else None
        versions = await _facade().catalog_get_json(
            f"/packages/by-id/{_facade().quote(pkg_id, safe='')}/versions", headers=headers
        )
        rows = versions.get("versions") or []
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict):
                version = _facade()._safe_text(first.get("version"))
            else:
                version = _facade()._safe_text(first)
    if not version and not download_path:
        raise _facade().HTTPException(status_code=400, detail="缺少 version")
    tmp = _facade().tempfile.NamedTemporaryFile(prefix="xcagi-mod-", suffix=".zip", delete=False)
    tmp_path = tmp.name
    tmp.close()
    normalized_path = tmp_path
    try:
        headers = {"Authorization": authorization} if authorization else None
        path = download_path or (
            f"/packages/{_facade().quote(pkg_id, safe='')}/"
            f"{_facade().quote(version, safe='')}/download"
        )
        await _facade().catalog_download_to(path, _facade().Path(tmp_path), headers=headers)
        expected = str(expected_sha256 or "").strip().lower()
        if expected:
            actual = _facade().hashlib.sha256(_facade().Path(tmp_path).read_bytes()).hexdigest()
            if actual != expected:
                raise _facade().HTTPException(
                    status_code=502,
                    detail=f"远端 Mod 包摘要不一致：expected={expected} actual={actual}",
                )
        normalized_path = _facade()._normalize_package_zip(tmp_path)
        from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
        from app.infrastructure.mods.artifact_package import peek_artifact

        if peek_artifact(normalized_path) == ARTIFACT_EMPLOYEE_PACK:
            from app.infrastructure.mods.employee_registry import get_employee_registry

            ok, message = get_employee_registry().install_from_package(
                normalized_path, verify_signature=verify_signature
            )
            return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=None)
        from app.infrastructure.mods.mod_manager import get_mod_manager

        ok, message, metadata = get_mod_manager().install_mod_package(
            normalized_path, verify_signature=verify_signature, activate=activate
        )
        data = (
            _facade().dataclasses.asdict(metadata)
            if metadata and _facade().dataclasses.is_dataclass(metadata)
            else None
        )
        return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=data)
    finally:
        for p in {tmp_path, normalized_path}:
            try:
                if p and _facade().os.path.exists(p):
                    _facade().os.unlink(p)
            except OSError:
                _facade().logger.warning("无法删除临时 Mod 包: %s", p)


@_facade().router.get("/catalog", response_model=_facade().ModStoreCatalogResponse)
async def mod_store_catalog() -> _facade().ModStoreCatalogResponse:
    rows, installed = await _facade()._combined_rows()
    return _facade().ModStoreCatalogResponse(
        data=_facade().ModStoreCatalogPayload(
            installed=installed, available=rows, indexed_count=len(rows)
        )
    )


@_facade().router.get("/market-catalog", response_model=_facade().ModStoreMarketCatalogResponse)
async def mod_store_market_catalog(
    q: str | None = _facade().Query(None),
    collection: str | None = _facade().Query(None),
    artifact: str | None = _facade().Query(None),
    material_category: str | None = _facade().Query(None),
    license_scope: str | None = _facade().Query(None),
    industry: str | None = _facade().Query(None),
    security_level: str | None = _facade().Query(None),
    limit: int = _facade().Query(80, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
) -> _facade().ModStoreMarketCatalogResponse:
    """代理修茈 AI 市场 /api/market/catalog，合并本机安装态。"""
    data = await _facade().fetch_market_catalog_page(
        q=q,
        collection=collection,
        artifact=artifact,
        material_category=material_category,
        license_scope=license_scope,
        industry=industry,
        security_level=security_level,
        limit=limit,
        offset=offset,
    )
    items, total = await _facade()._map_market_catalog_page(
        data, collection_hint=str(collection or "").strip()
    )
    return _facade().ModStoreMarketCatalogResponse(
        data=_facade().ModStoreMarketCatalogPayload(
            items=items, total=total, collection=str(collection or "").strip()
        )
    )


@_facade().router.get("/search", response_model=_facade().ModStoreListResponse)
async def mod_store_search(
    q: str | None = _facade().Query(None),
    author: str | None = _facade().Query(None),
    installed: bool | None = _facade().Query(None),
    limit: int = _facade().Query(50, ge=1, le=200),
) -> _facade().ModStoreListResponse:
    rows, _installed = await _facade()._combined_rows()
    out = _facade()._filter_rows(rows, q=q, author=author, installed=installed)
    return _facade().ModStoreListResponse(data=out[:limit])


@_facade().router.get("/popular", response_model=_facade().ModStoreListResponse)
async def mod_store_popular(
    limit: int = _facade().Query(10, ge=1, le=200),
) -> _facade().ModStoreListResponse:
    rows, _installed = await _facade()._combined_rows()
    rows.sort(key=lambda r: r.get("total_downloads") or r.get("download_count") or 0, reverse=True)
    return _facade().ModStoreListResponse(data=rows[:limit])


@_facade().router.get("/recent", response_model=_facade().ModStoreListResponse)
async def mod_store_recent(
    limit: int = _facade().Query(10, ge=1, le=200),
) -> _facade().ModStoreListResponse:
    rows, _installed = await _facade()._combined_rows()
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return _facade().ModStoreListResponse(data=rows[:limit])


@_facade().router.get("/mod/{mod_id}/details", response_model=_facade().ModStoreDetailResponse)
async def mod_store_details(mod_id: str) -> _facade().ModStoreDetailResponse:
    mid = (mod_id or "").strip()
    try:
        versions = await _facade().catalog_get_json(
            f"/packages/by-id/{_facade().quote(mid, safe='')}/versions"
        )
        rows = versions.get("versions") or []
        if isinstance(rows, list) and rows:
            latest = rows[0] if isinstance(rows[0], dict) else {"version": rows[0]}
            version = _facade()._safe_text(latest.get("version")) or "1.0.0"
            detail = await _facade().catalog_get_json(
                f"/packages/{_facade().quote(mid, safe='')}/{_facade().quote(version, safe='')}"
            )
            return _facade().ModStoreDetailResponse(
                data=_facade().ModStoreDetailData(
                    id=str(detail.get("id") or mid),
                    name=str(detail.get("name") or mid),
                    version=str(detail.get("version") or version),
                    author=str(detail.get("author") or detail.get("publisher") or "—"),
                    description=str(detail.get("description") or ""),
                    statistics=None,
                    ratings=[],
                    rating_count=0,
                    source="remote",
                    catalog_base_url=_facade().catalog_base_url(),
                )
            )
    except _facade().HTTPException as exc:
        _facade().logger.info("remote catalog detail fallback for %s: %s", mid, exc.detail)
    rows, _installed = await _facade()._combined_rows()
    for r in rows:
        if str(r.get("id")) == mid:
            return _facade().ModStoreDetailResponse(
                data=_facade().ModStoreDetailData(
                    id=str(r["id"]),
                    name=str(r["name"]),
                    version=str(r["version"]),
                    author=str(r["author"]),
                    description=str(r["description"]),
                    statistics=None,
                    ratings=[],
                    rating_count=0,
                    source=str(r.get("source") or "local"),
                    catalog_base_url=str(r.get("catalog_base_url") or _facade().catalog_base_url()),
                )
            )
    raise _facade().HTTPException(status_code=404, detail="未找到该 MOD")


@_facade().router.post("/upload", response_model=_facade().ModStoreInstallResult)
async def mod_store_upload(
    file: _facade().UploadFile = _facade().File(..., description="Mod 包文件 (.xcemp 或 .zip)"),
    activate: bool = _facade().Query(True, description="安装后是否立即激活"),
) -> _facade().ModStoreInstallResult:
    """上传 Mod 包到本机并自动安装。

    进化状态闭环（2026-07-20）：
      - 接受 multipart/form-data 文件上传（最大 100MB）
      - 校验文件扩展名（.xcemp / .zip）
      - 落地到临时文件后调用 ``mod_manager.install_mod_package``
      - 返回安装结果（含 manifest 元数据）
    """
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024
    filename = (file.filename or "").lower()
    if not (filename.endswith(".xcemp") or filename.endswith(".zip")):
        raise _facade().HTTPException(status_code=400, detail="仅支持 .xcemp 或 .zip 格式的 Mod 包")
    tmp = _facade().tempfile.NamedTemporaryFile(prefix="xcagi-upload-", suffix=".zip", delete=False)
    tmp_path = tmp.name
    tmp.close()
    total_size = 0
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    raise _facade().HTTPException(
                        status_code=413, detail=f"文件过大（>{MAX_UPLOAD_SIZE // (1024 * 1024)}MB）"
                    )
                out.write(chunk)
        if total_size == 0:
            raise _facade().HTTPException(status_code=400, detail="上传文件为空")
        normalized_path = _facade().normalize_package_zip_path(tmp_path)
        from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
        from app.infrastructure.mods.artifact_package import peek_artifact

        if peek_artifact(normalized_path) == ARTIFACT_EMPLOYEE_PACK:
            from app.infrastructure.mods.employee_registry import get_employee_registry

            ok, message = get_employee_registry().install_from_package(
                normalized_path, verify_signature=True
            )
            return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=None)
        from app.infrastructure.mods.mod_manager import get_mod_manager

        ok, message, metadata = get_mod_manager().install_mod_package(
            normalized_path, verify_signature=True, activate=activate
        )
        data = (
            _facade().dataclasses.asdict(metadata)
            if metadata and _facade().dataclasses.is_dataclass(metadata)
            else None
        )
        return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=data)
    finally:
        for p in {tmp_path}:
            try:
                if p and _facade().os.path.exists(p):
                    _facade().os.unlink(p)
            except OSError:
                _facade().logger.warning("无法删除上传临时文件: %s", p)


@_facade().router.post("/install", response_model=_facade().ModStoreInstallResult)
async def mod_store_install(request: _facade().Request) -> _facade().ModStoreInstallResult:
    payload = await _facade()._request_payload(request)
    pkg_id = _facade()._safe_text(payload.get("pkg_id") or payload.get("mod_id"))
    version = _facade()._safe_text(payload.get("version"))
    if not pkg_id:
        pkg_id, parsed_version = _facade()._split_package_file(payload.get("package_file") or "")
        version = version or parsed_version
    activate = str(payload.get("activate") or "true").lower() not in {"0", "false", "no"}
    return await _facade()._install_from_catalog(pkg_id, version, activate=activate)


@_facade().router.post("/install-industry-seed", response_model=_facade().ModStoreInstallResult)
async def mod_store_install_industry_seed(
    request: _facade().Request,
) -> _facade().ModStoreInstallResult:
    """L2：从 industry-seeds 池安装所选行业中性 Mod；池缺失时 Catalog 兜底。"""
    payload = await _facade()._request_payload(request)
    raw = _facade()._safe_text(
        payload.get("industry_id") or payload.get("mod_id") or payload.get("industryId")
    )
    if not raw:
        raise _facade().HTTPException(status_code=400, detail="缺少 industry_id 或 mod_id")
    from app.mod_sdk.industry_seed import install_industry_seed_with_fallback

    data = await install_industry_seed_with_fallback(raw)
    return _facade().ModStoreInstallResult(
        success=bool(data.get("success")), message=str(data.get("message") or ""), data=data
    )


@_facade().router.post(
    "/install-customer-delivery-seed", response_model=_facade().ModStoreInstallResult
)
async def mod_store_install_customer_delivery_seed(
    request: _facade().Request,
) -> _facade().ModStoreInstallResult:
    """账号定制交付：从服务器下载客户种子包并导入本地业务数据。"""
    payload = await _facade()._request_payload(request)
    mod_id = _facade()._safe_text(payload.get("mod_id") or payload.get("pkg_id"))
    industry_id = _facade()._safe_text(payload.get("industry_id") or payload.get("industryId"))
    if not mod_id:
        raise _facade().HTTPException(status_code=400, detail="缺少 mod_id")
    try:
        from app.enterprise.mod_entitlements import (
            enterprise_mod_filter_active,
            get_cached_entitled_client_mod_ids,
            sync_entitlements_from_request,
        )

        if enterprise_mod_filter_active():
            await sync_entitlements_from_request(request)
            entitled = get_cached_entitled_client_mod_ids() or set()
            from app.mod_sdk.industry_mod_aliases import canonical_mod_id

            entitled_canonical = {canonical_mod_id(value) for value in entitled}
            if canonical_mod_id(mod_id) not in entitled_canonical:
                raise _facade().HTTPException(status_code=403, detail="当前账号未授权该客户交付包")
    except _facade().HTTPException:
        raise
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("customer delivery seed entitlement check skipped", exc_info=True)
    market_token = ""
    account_username = ""
    try:
        from app.fastapi_routes.market_account import resolve_valid_market_access_token
        from app.infrastructure.auth.dependencies import (
            resolve_session_user,
            session_id_from_request,
        )

        sid = session_id_from_request(request)
        if sid:
            market_token = await resolve_valid_market_access_token(sid) or ""
        user = resolve_session_user(request)
        if user is not None:
            account_username = (
                str(user.get("username") or "").strip()
                if isinstance(user, dict)
                else str(getattr(user, "username", "") or "").strip()
            )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("customer delivery seed token resolve skipped", exc_info=True)
    from app.mod_sdk.customer_delivery_seed import install_customer_delivery_seed_package

    data = await install_customer_delivery_seed_package(
        mod_id=mod_id,
        industry_id=industry_id,
        market_token=market_token,
        account_username=account_username,
    )
    return _facade().ModStoreInstallResult(
        success=bool(data.get("success")), message=str(data.get("message") or ""), data=data
    )
