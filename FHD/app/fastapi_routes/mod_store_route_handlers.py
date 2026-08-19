# ruff: noqa
# mypy: ignore-errors
"""Install, lifecycle, and catalog route handlers for the MOD store."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.mod_store_routes')

async def _install_from_catalog(pkg_id: str, version: str, activate: bool=True) -> _facade().ModStoreInstallResult:
    from app.mod_sdk.host_foundation import install_aux_employee_pack_from_repo_seed, is_aux_employee_pack_mod_id, is_host_foundation_employee_pack
    if is_host_foundation_employee_pack(pkg_id):
        return await _facade()._install_host_foundation_internal(edition=None)
    if is_aux_employee_pack_mod_id(pkg_id):
        (ok, message) = install_aux_employee_pack_from_repo_seed(pkg_id, activate=activate)
        if ok:
            return _facade().ModStoreInstallResult(success=True, message=message, data={'id': pkg_id})
        _facade().logger.info('aux employee seed install failed for %s: %s; try catalog', pkg_id, message)
    if not pkg_id:
        raise _facade().HTTPException(status_code=400, detail='缺少 pkg_id')
    if not version:
        versions = await _facade().catalog_get_json(f"/packages/by-id/{_facade().quote(pkg_id, safe='')}/versions")
        rows = versions.get('versions') or []
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict):
                version = _facade()._safe_text(first.get('version'))
            else:
                version = _facade()._safe_text(first)
    if not version:
        raise _facade().HTTPException(status_code=400, detail='缺少 version')
    tmp = _facade().tempfile.NamedTemporaryFile(prefix='xcagi-mod-', suffix='.zip', delete=False)
    tmp_path = tmp.name
    tmp.close()
    normalized_path = tmp_path
    try:
        await _facade().catalog_download_to(f"/packages/{_facade().quote(pkg_id, safe='')}/{_facade().quote(version, safe='')}/download", _facade().Path(tmp_path))
        normalized_path = _facade()._normalize_package_zip(tmp_path)
        from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
        from app.infrastructure.mods.artifact_package import peek_artifact
        if peek_artifact(normalized_path) == ARTIFACT_EMPLOYEE_PACK:
            from app.infrastructure.mods.employee_registry import get_employee_registry
            (ok, message) = get_employee_registry().install_from_package(normalized_path, verify_signature=True)
            return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=None)
        from app.infrastructure.mods.mod_manager import get_mod_manager
        (ok, message, metadata) = get_mod_manager().install_mod_package(normalized_path, verify_signature=True, activate=activate)
        data = _facade().dataclasses.asdict(metadata) if metadata and _facade().dataclasses.is_dataclass(metadata) else None
        return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=data)
    finally:
        for p in {tmp_path, normalized_path}:
            try:
                if p and _facade().os.path.exists(p):
                    _facade().os.unlink(p)
            except OSError:
                _facade().logger.warning('无法删除临时 Mod 包: %s', p)

@_facade().router.get('/catalog', response_model=_facade().ModStoreCatalogResponse)
async def mod_store_catalog() -> _facade().ModStoreCatalogResponse:
    (rows, installed) = await _facade()._combined_rows()
    return _facade().ModStoreCatalogResponse(data=_facade().ModStoreCatalogPayload(installed=installed, available=rows, indexed_count=len(rows)))

@_facade().router.get('/market-catalog', response_model=_facade().ModStoreMarketCatalogResponse)
async def mod_store_market_catalog(q: str | None=_facade().Query(None), collection: str | None=_facade().Query(None), artifact: str | None=_facade().Query(None), material_category: str | None=_facade().Query(None), license_scope: str | None=_facade().Query(None), industry: str | None=_facade().Query(None), security_level: str | None=_facade().Query(None), limit: int=_facade().Query(80, ge=1, le=200), offset: int=_facade().Query(0, ge=0)) -> _facade().ModStoreMarketCatalogResponse:
    """代理修茈 AI 市场 /api/market/catalog，合并本机安装态。"""
    data = await _facade().fetch_market_catalog_page(q=q, collection=collection, artifact=artifact, material_category=material_category, license_scope=license_scope, industry=industry, security_level=security_level, limit=limit, offset=offset)
    (items, total) = await _facade()._map_market_catalog_page(data, collection_hint=str(collection or '').strip())
    return _facade().ModStoreMarketCatalogResponse(data=_facade().ModStoreMarketCatalogPayload(items=items, total=total, collection=str(collection or '').strip()))

@_facade().router.get('/search', response_model=_facade().ModStoreListResponse)
async def mod_store_search(q: str | None=_facade().Query(None), author: str | None=_facade().Query(None), installed: bool | None=_facade().Query(None), limit: int=_facade().Query(50, ge=1, le=200)) -> _facade().ModStoreListResponse:
    (rows, _installed) = await _facade()._combined_rows()
    out = _facade()._filter_rows(rows, q=q, author=author, installed=installed)
    return _facade().ModStoreListResponse(data=out[:limit])

@_facade().router.get('/popular', response_model=_facade().ModStoreListResponse)
async def mod_store_popular(limit: int=_facade().Query(10, ge=1, le=200)) -> _facade().ModStoreListResponse:
    (rows, _installed) = await _facade()._combined_rows()
    rows.sort(key=lambda r: r.get('total_downloads') or r.get('download_count') or 0, reverse=True)
    return _facade().ModStoreListResponse(data=rows[:limit])

@_facade().router.get('/recent', response_model=_facade().ModStoreListResponse)
async def mod_store_recent(limit: int=_facade().Query(10, ge=1, le=200)) -> _facade().ModStoreListResponse:
    (rows, _installed) = await _facade()._combined_rows()
    rows.sort(key=lambda r: str(r.get('created_at') or ''), reverse=True)
    return _facade().ModStoreListResponse(data=rows[:limit])

@_facade().router.get('/mod/{mod_id}/details', response_model=_facade().ModStoreDetailResponse)
async def mod_store_details(mod_id: str) -> _facade().ModStoreDetailResponse:
    mid = (mod_id or '').strip()
    try:
        versions = await _facade().catalog_get_json(f"/packages/by-id/{_facade().quote(mid, safe='')}/versions")
        rows = versions.get('versions') or []
        if isinstance(rows, list) and rows:
            latest = rows[0] if isinstance(rows[0], dict) else {'version': rows[0]}
            version = _facade()._safe_text(latest.get('version')) or '1.0.0'
            detail = await _facade().catalog_get_json(f"/packages/{_facade().quote(mid, safe='')}/{_facade().quote(version, safe='')}")
            return _facade().ModStoreDetailResponse(data=_facade().ModStoreDetailData(id=str(detail.get('id') or mid), name=str(detail.get('name') or mid), version=str(detail.get('version') or version), author=str(detail.get('author') or detail.get('publisher') or '—'), description=str(detail.get('description') or ''), statistics=None, ratings=[], rating_count=0, source='remote', catalog_base_url=_facade().catalog_base_url()))
    except _facade().HTTPException as exc:
        _facade().logger.info('remote catalog detail fallback for %s: %s', mid, exc.detail)
    (rows, _installed) = await _facade()._combined_rows()
    for r in rows:
        if str(r.get('id')) == mid:
            return _facade().ModStoreDetailResponse(data=_facade().ModStoreDetailData(id=str(r['id']), name=str(r['name']), version=str(r['version']), author=str(r['author']), description=str(r['description']), statistics=None, ratings=[], rating_count=0, source=str(r.get('source') or 'local'), catalog_base_url=str(r.get('catalog_base_url') or _facade().catalog_base_url())))
    raise _facade().HTTPException(status_code=404, detail='未找到该 MOD')

@_facade().router.post('/upload', response_model=_facade().ModStoreInstallResult)
async def mod_store_upload(file: _facade().UploadFile=_facade().File(..., description='Mod 包文件 (.xcemp 或 .zip)'), activate: bool=_facade().Query(True, description='安装后是否立即激活')) -> _facade().ModStoreInstallResult:
    """上传 Mod 包到本机并自动安装。

    进化状态闭环（2026-07-20）：
      - 接受 multipart/form-data 文件上传（最大 100MB）
      - 校验文件扩展名（.xcemp / .zip）
      - 落地到临时文件后调用 ``mod_manager.install_mod_package``
      - 返回安装结果（含 manifest 元数据）
    """
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024
    filename = (file.filename or '').lower()
    if not (filename.endswith('.xcemp') or filename.endswith('.zip')):
        raise _facade().HTTPException(status_code=400, detail='仅支持 .xcemp 或 .zip 格式的 Mod 包')
    tmp = _facade().tempfile.NamedTemporaryFile(prefix='xcagi-upload-', suffix='.zip', delete=False)
    tmp_path = tmp.name
    tmp.close()
    total_size = 0
    try:
        with open(tmp_path, 'wb') as out:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    raise _facade().HTTPException(status_code=413, detail=f'文件过大（>{MAX_UPLOAD_SIZE // (1024 * 1024)}MB）')
                out.write(chunk)
        if total_size == 0:
            raise _facade().HTTPException(status_code=400, detail='上传文件为空')
        normalized_path = _facade().normalize_package_zip_path(tmp_path)
        from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
        from app.infrastructure.mods.artifact_package import peek_artifact
        if peek_artifact(normalized_path) == ARTIFACT_EMPLOYEE_PACK:
            from app.infrastructure.mods.employee_registry import get_employee_registry
            (ok, message) = get_employee_registry().install_from_package(normalized_path, verify_signature=True)
            return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=None)
        from app.infrastructure.mods.mod_manager import get_mod_manager
        (ok, message, metadata) = get_mod_manager().install_mod_package(normalized_path, verify_signature=True, activate=activate)
        data = _facade().dataclasses.asdict(metadata) if metadata and _facade().dataclasses.is_dataclass(metadata) else None
        return _facade().ModStoreInstallResult(success=bool(ok), message=message, data=data)
    finally:
        for p in {tmp_path}:
            try:
                if p and _facade().os.path.exists(p):
                    _facade().os.unlink(p)
            except OSError:
                _facade().logger.warning('无法删除上传临时文件: %s', p)

@_facade().router.post('/install', response_model=_facade().ModStoreInstallResult)
async def mod_store_install(request: _facade().Request) -> _facade().ModStoreInstallResult:
    payload = await _facade()._request_payload(request)
    pkg_id = _facade()._safe_text(payload.get('pkg_id') or payload.get('mod_id'))
    version = _facade()._safe_text(payload.get('version'))
    if not pkg_id:
        (pkg_id, parsed_version) = _facade()._split_package_file(payload.get('package_file') or '')
        version = version or parsed_version
    activate = str(payload.get('activate') or 'true').lower() not in {'0', 'false', 'no'}
    return await _facade()._install_from_catalog(pkg_id, version, activate=activate)

@_facade().router.post('/install-industry-seed', response_model=_facade().ModStoreInstallResult)
async def mod_store_install_industry_seed(request: _facade().Request) -> _facade().ModStoreInstallResult:
    """L2：从 industry-seeds 池安装所选行业中性 Mod；池缺失时 Catalog 兜底。"""
    payload = await _facade()._request_payload(request)
    raw = _facade()._safe_text(payload.get('industry_id') or payload.get('mod_id') or payload.get('industryId'))
    if not raw:
        raise _facade().HTTPException(status_code=400, detail='缺少 industry_id 或 mod_id')
    from app.mod_sdk.industry_seed import install_industry_seed_with_fallback
    data = await install_industry_seed_with_fallback(raw)
    return _facade().ModStoreInstallResult(success=bool(data.get('success')), message=str(data.get('message') or ''), data=data)

@_facade().router.post('/install-customer-delivery-seed', response_model=_facade().ModStoreInstallResult)
async def mod_store_install_customer_delivery_seed(request: _facade().Request) -> _facade().ModStoreInstallResult:
    """账号定制交付：从服务器下载客户种子包并导入本地业务数据。"""
    payload = await _facade()._request_payload(request)
    mod_id = _facade()._safe_text(payload.get('mod_id') or payload.get('pkg_id'))
    industry_id = _facade()._safe_text(payload.get('industry_id') or payload.get('industryId'))
    if not mod_id:
        raise _facade().HTTPException(status_code=400, detail='缺少 mod_id')
    try:
        from app.enterprise.mod_entitlements import enterprise_mod_filter_active, get_cached_entitled_client_mod_ids, sync_entitlements_from_request
        if enterprise_mod_filter_active():
            await sync_entitlements_from_request(request)
            entitled = get_cached_entitled_client_mod_ids() or set()
            if mod_id not in entitled:
                raise _facade().HTTPException(status_code=403, detail='当前账号未授权该客户交付包')
    except _facade().HTTPException:
        raise
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning('customer delivery seed entitlement check skipped', exc_info=True)
    market_token = ''
    try:
        from app.fastapi_routes.market_account import resolve_valid_market_access_token
        from app.infrastructure.auth.dependencies import session_id_from_request
        sid = session_id_from_request(request)
        if sid:
            market_token = await resolve_valid_market_access_token(sid) or ''
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning('customer delivery seed token resolve skipped', exc_info=True)
    from app.mod_sdk.customer_delivery_seed import install_customer_delivery_seed_package
    data = await install_customer_delivery_seed_package(mod_id=mod_id, industry_id=industry_id, market_token=market_token)
    return _facade().ModStoreInstallResult(success=bool(data.get('success')), message=str(data.get('message') or ''), data=data)

@_facade().router.post('/reload-employees')
async def mod_store_reload_employees(request: _facade().Request) -> _facade().ModStoreSimpleResponse:
    """显式刷新 employee_pack HTTP 路由与 Planner 工具注册表（装包后双保险）。"""
    payload = await _facade()._request_payload(request)
    pack_id = _facade()._safe_text(payload.get('pack_id') or payload.get('pkg_id'))
    from app.mod_sdk.employee_runtime import refresh_employee_pack_runtime
    data = refresh_employee_pack_runtime(pack_id or None)
    return _facade().ModStoreSimpleResponse(success=True, message='员工包 Planner 注册表已刷新', data=data)

@_facade().router.post('/uninstall', response_model=_facade().ModStoreSimpleResponse)
async def mod_store_uninstall(request: _facade().Request) -> _facade().ModStoreSimpleResponse:
    mod_id = await _facade()._body_value(request, 'mod_id')
    if not mod_id:
        raise _facade().HTTPException(status_code=400, detail='缺少 mod_id')
    from app.infrastructure.mods.mod_manager import get_mod_manager
    (ok, message) = get_mod_manager().uninstall_mod(mod_id, remove_files=True)
    return _facade().ModStoreSimpleResponse(success=bool(ok), message=message, data={'id': mod_id})

@_facade().router.post('/update', response_model=_facade().ModStoreInstallResult)
async def mod_store_update(request: _facade().Request) -> _facade().ModStoreInstallResult:
    payload = await _facade()._request_payload(request)
    pkg_id = _facade()._safe_text(payload.get('pkg_id') or payload.get('mod_id'))
    version = _facade()._safe_text(payload.get('version'))
    if not pkg_id:
        (pkg_id, parsed_version) = _facade()._split_package_file(payload.get('package_file') or '')
        version = version or parsed_version
    return await _facade()._install_from_catalog(pkg_id, version, activate=True)

@_facade().router.get('/validate', response_model=_facade().ModStoreSimpleResponse)
async def mod_store_validate() -> _facade().ModStoreSimpleResponse:
    return _facade().ModStoreSimpleResponse(success=False, message='未实现', data=None)

@_facade().router.get('/updates', response_model=_facade().ModStoreUpdatesResponse)
async def mod_store_updates() -> _facade().ModStoreUpdatesResponse:
    return _facade().ModStoreUpdatesResponse(data={'updates_available': [], 'count': 0})

@_facade().router.get('/dependencies', response_model=_facade().ModStoreDependenciesResponse)
async def mod_store_dependencies() -> _facade().ModStoreDependenciesResponse:
    return _facade().ModStoreDependenciesResponse(data={'mod_id': '', 'dependencies': [], 'satisfied': [], 'missing': [], 'can_install': True})

@_facade().router.post('/mod/{mod_id}/rate', response_model=_facade().ModStoreNotImplementedResponse)
async def mod_store_rate(mod_id: str) -> _facade().ModStoreNotImplementedResponse:
    return _facade().ModStoreNotImplementedResponse(detail='评分 尚未在本后端实现；请将 Mod 包放入 XCAGI/mods 或通过 MODstore 工具链。')

@_facade().router.get('/package/{package_file:path}/download')
async def mod_store_download(package_file: str) -> None:
    raise _facade().HTTPException(status_code=404, detail='包下载未实现')

@_facade().router.delete('/package/{package_file:path}', response_model=_facade().ModStoreNotImplementedResponse)
async def mod_store_delete_package(package_file: str) -> _facade().ModStoreNotImplementedResponse:
    return _facade().ModStoreNotImplementedResponse(detail='删除包 尚未在本后端实现；请将 Mod 包放入 XCAGI/mods 或通过 MODstore 工具链。')

@_facade().router.post('/index/rebuild', response_model=_facade().ModStoreRebuildResponse)
async def mod_store_rebuild_index() -> _facade().ModStoreRebuildResponse:
    return _facade().ModStoreRebuildResponse(data={'indexed': 0, 'failed': 0}, message='索引由磁盘 manifest 实时生成，无需重建。')

async def _ensure_host_foundation_employee_on_disk() -> tuple[bool, str]:
    """将内置 _employees/xcagi-host-foundation-employee 复制到用户 mods 目录（若尚未存在）。"""
    import shutil
    import sys
    from app.infrastructure.mods.employee_registry import employees_root, get_employee_registry
    from app.mod_sdk.host_foundation import HOST_FOUNDATION_EMPLOYEE_PACK_ID
    mm_root = get_employee_registry().mods_root
    dest = _facade().os.path.join(employees_root(mm_root), HOST_FOUNDATION_EMPLOYEE_PACK_ID)
    if _facade().os.path.isdir(dest):
        return (True, 'employee pack present')
    candidates = [_facade().Path(mm_root) / '_employees' / HOST_FOUNDATION_EMPLOYEE_PACK_ID]
    if getattr(sys, 'frozen', False) or _facade().os.environ.get('XCAGI_BUNDLED_MODS_DIR') or _facade().os.environ.get('XCAGI_SEED_MODS_DIR'):
        from app.mod_sdk.edition_policy import bundled_mods_dir
        bundled = bundled_mods_dir()
        if bundled is not None:
            candidates.append(_facade().Path(bundled) / '_employees' / HOST_FOUNDATION_EMPLOYEE_PACK_ID)
    src = next((p for p in candidates if _facade().os.path.isdir(str(p))), None)
    if src is None:
        checked = '；'.join((str(p) for p in candidates))
        return (False, f'内置员工包目录缺失：{checked}')
    _facade().os.makedirs(_facade().os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest)
    return (True, 'employee pack seeded')

def _can_materialize_host_foundation_without_employee_marker() -> bool:
    """Packaged builds can seed host bridges without the employee marker pack."""
    import sys
    return bool(getattr(sys, 'frozen', False) or _facade().os.environ.get('XCAGI_BUNDLED_MODS_DIR') or _facade().os.environ.get('XCAGI_SEED_MODS_DIR'))

async def _install_host_foundation_internal(edition: str | None) -> _facade().ModStoreInstallResult:
    from app.mod_sdk.edition_policy import resolve_edition
    from app.mod_sdk.host_foundation import materialize_host_foundation_bridges
    (ok, msg) = await _facade()._ensure_host_foundation_employee_on_disk()
    employee_seed_warning = ''
    if not ok:
        if not _facade()._can_materialize_host_foundation_without_employee_marker():
            return _facade().ModStoreInstallResult(success=False, message=msg, data=None)
        employee_seed_warning = msg
    ed = (edition or resolve_edition() or 'generic').strip().lower()
    if ed not in ('minimal', 'generic', 'full'):
        ed = 'generic'
    try:
        data = materialize_host_foundation_bridges(ed)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('materialize_host_foundation_bridges failed (edition=%s)', ed)
        return _facade().ModStoreInstallResult(success=False, message=f'展开宿主 bridge 失败：{exc}', data={'edition': ed, 'missing_mod_ids': [], 'ready': False})
    if employee_seed_warning and isinstance(data, dict):
        data = {**data, 'employee_seed_warning': employee_seed_warning}
    if data.get('ready'):
        message = f"宿主基础能力员工包已就绪（bridge {data.get('installed_count')}/{data.get('expected_count')}）"
        if employee_seed_warning:
            message += f'；员工包标记未复制（{employee_seed_warning}）'
        success = True
    else:
        missing = data.get('missing_mod_ids') or []
        message = f"宿主 bridge 未齐（{data.get('installed_count')}/{data.get('expected_count')}）：{'、'.join(missing[:8])}"
        success = False
    return _facade().ModStoreInstallResult(success=success, message=message, data=data)

@_facade().router.post('/install-host-foundation', response_model=_facade().ModStoreSimpleResponse)
async def mod_store_install_host_foundation(edition: str | None=_facade().Query(None, description='minimal | generic | full')) -> _facade().ModStoreSimpleResponse:
    """安装「宿主基础能力·预装员工」并 materialize 全部 bridge（非逐项 Mod 上架）。"""
    try:
        result = await _facade()._install_host_foundation_internal(edition)
        return _facade().ModStoreSimpleResponse(success=result.success, message=result.message, data=result.data)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('install-host-foundation failed')
        return _facade().ModStoreSimpleResponse(success=False, message=f'装包失败：{exc}', data=None)

@_facade().router.post('/bootstrap-edition-pack', response_model=_facade().ModStoreSimpleResponse)
async def mod_store_bootstrap_edition_pack(edition: str | None=_facade().Query(None, description='minimal | generic | full')) -> _facade().ModStoreSimpleResponse:
    """装齐当前 edition 所需 Mod：先复制安装包内置 mods/，再对缺失项尝试 Catalog。"""
    from app.mod_sdk.edition_bootstrap import bootstrap_edition_pack
    from app.mod_sdk.edition_policy import resolve_edition
    ed = (edition or resolve_edition() or 'generic').strip().lower()
    if ed not in ('minimal', 'generic', 'full'):
        raise _facade().HTTPException(status_code=400, detail='edition 须为 minimal、generic 或 full')
    try:
        from app.mod_sdk.product_skus import assert_bootstrap_edition_allowed
        assert_bootstrap_edition_allowed(edition)
    except PermissionError as exc:
        raise _facade().HTTPException(status_code=400, detail=str(exc)) from exc
    data = await bootstrap_edition_pack(_facade().cast("Literal['minimal', 'generic', 'full']", ed))
    if data.get('ready'):
        msg = '通用宿主包已装齐'
    else:
        installed = int(data.get('installed_count') or 0)
        expected = int(data.get('expected_count') or 0)
        failed_ids: list[str] = []
        for row in data.get('catalog') or []:
            if not isinstance(row, dict):
                continue
            if row.get('status') in ('catalog_failed', 'missing'):
                mid = str(row.get('mod_id') or '').strip()
                if mid:
                    failed_ids.append(mid)
        for row in data.get('seed') or []:
            if not isinstance(row, dict):
                continue
            if row.get('status') in ('missing', 'error'):
                mid = str(row.get('mod_id') or '').strip()
                if mid and mid not in failed_ids:
                    failed_ids.append(mid)
        hint = '、'.join(failed_ids[:8])
        msg = f'宿主包未装齐（{installed}/{expected}）'
        if hint:
            msg += f'：{hint}'
    return _facade().ModStoreSimpleResponse(success=bool(data.get('ready')), message=msg, data=data)

@_facade().router.post('/sync-modstore-library', response_model=_facade().ModStoreSimpleResponse)
async def mod_store_sync_modstore_library(request: _facade().Request) -> _facade().ModStoreSimpleResponse:
    """使用修茈 PAT（须含 ``mod:sync``）从线上 ``/v1/mod-sync`` 拉 zip 并安装到本机 ``mods/``。"""
    try:
        body = await request.json()
    except _facade().RECOVERABLE_ERRORS:
        raise _facade().HTTPException(status_code=400, detail='需要 JSON 请求体') from None
    if not isinstance(body, dict):
        raise _facade().HTTPException(status_code=400, detail='JSON 须为对象')
    base = str(body.get('base_url') or body.get('baseUrl') or '').strip().rstrip('/') or 'https://xiu-ci.com'
    token = str(body.get('token') or '').strip()
    if not token:
        raise _facade().HTTPException(status_code=400, detail='缺少 token（修茈 Developer PAT，需含 mod:sync）')
    sync_all = bool(body.get('all'))
    raw_ids = body.get('mod_ids')
    mod_ids: list[str] | None = None
    if isinstance(raw_ids, list):
        mod_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
    elif isinstance(raw_ids, str) and raw_ids.strip():
        mod_ids = [x.strip() for x in raw_ids.split(',') if x.strip()]
    if not sync_all and (not mod_ids or len(mod_ids) == 0):
        raise _facade().HTTPException(status_code=400, detail='请指定 mod_ids（数组或逗号分隔字符串）或设置 all: true')
    try:
        raw = await _facade().sync_modstore_library_to_local(base_url=base, token=token, mod_ids=mod_ids, sync_all_ok=sync_all)
        return _facade().ModStoreSimpleResponse(success=bool(raw.get('success')), message=str(raw.get('message') or ''), data=raw.get('data') if isinstance(raw.get('data'), dict) else None)
    except ValueError as e:
        raise _facade().HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise _facade().HTTPException(status_code=502, detail=str(e)) from e
