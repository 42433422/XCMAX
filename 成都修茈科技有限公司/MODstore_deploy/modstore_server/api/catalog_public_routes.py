"""公网 Catalog 只读/上传 API（挂载在 XC AGI 服务 /v1）。"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    Body,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, Field

from modstore_server.api.catalog_public_helpers import authorize_upload as _authorize_upload
from modstore_server.api.catalog_public_helpers import catalog_cache_scope as _catalog_cache_scope
from modstore_server.api.catalog_public_helpers import (
    invalidate_catalog_list_caches as _invalidate_catalog_list_caches,
)
from modstore_server.api.catalog_public_helpers import params_hash as _params_hash
from modstore_server.api.catalog_public_helpers import require_upload as _require_upload
from modstore_server.api.catalog_public_helpers import (
    try_index_catalog_item as _try_index_catalog_item,
)
from modstore_server.api.catalog_public_helpers import (
    upsert_market_listing as _upsert_market_listing,
)
from modstore_server.api.catalog_public_helpers import (
    validated_automation_provenance as _validated_automation_provenance,
)
from modstore_server.catalog_publication_policy import is_private_package, require_public_manifest
from modstore_server.catalog_store import (
    PackageConflictError,
    append_package,
    get_package,
    list_packages,
    list_versions,
    packages_path,
    promote_draft_to_stable,
    read_package_manifest_from_zip,
    sha256_file,
)
from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
from modstore_server.duty_roster import is_planned_duty_employee_pack
from modstore_server.employee_config_v2 import (
    extract_or_upgrade_v2_config,
    validate_v2_config,
)
from modstore_server.industry_taxonomy import get_industry_tree
from modstore_server.models import get_session_factory
from modstore_server.vector_store import insert_embedding as insert_embedding
from modstore_server.vector_store import (
    query_similar,
)

router = APIRouter(prefix="/v1", tags=["catalog"])


@router.get("/packages", summary="分页列出包")
def api_list_packages(
    artifact: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    from modstore_server import cache

    ck = (
        f"catalog:v1:{_catalog_cache_scope()}:packages:list:"
        f"{_params_hash(artifact, q, limit, offset)}"
    )
    cached = cache.get_json(ck)
    if cached is not None:
        return cached
    rows, total = list_packages(artifact=artifact, q=q, limit=limit, offset=offset)
    rows = [r for r in rows if not is_private_package(r)]
    if artifact and str(artifact).strip().lower() == "customer_delivery_seed":
        total = 0
    result = {"packages": rows, "total": total, "limit": limit, "offset": offset}
    cache.set_json(ck, result, ttl_seconds=300)
    return result


@router.get("/packages/{pkg_id}/{version}", summary="包详情")
def api_get_package(pkg_id: str, version: str):
    from modstore_server import cache

    ck = f"catalog:v1:{_catalog_cache_scope()}:pkg:{pkg_id}:{version}"
    cached = cache.get_json(ck)
    if cached is not None:
        return cached
    r = get_package(pkg_id, version)
    if not r or is_private_package(r):
        raise HTTPException(404, "未找到该版本")
    cache.set_json(ck, r, ttl_seconds=600)
    return r


@router.get("/packages/by-id/{pkg_id}/versions", summary="同 id 下所有版本（含 draft/stable）")
def api_package_versions(pkg_id: str):
    pid = (pkg_id or "").strip()
    if not pid:
        raise HTTPException(400, "pkg_id 无效")
    versions = [r for r in list_versions(pid) if not is_private_package(r)]
    return {"pkg_id": pid, "versions": versions}


class PromoteBody(BaseModel):
    from_version: str = Field(..., min_length=1, description="要晋升的 draft 版本号")


@router.post(
    "/packages/{pkg_id}/promote",
    summary="将 draft 版本复制为新的 stable（semver patch+1）",
)
def api_promote_package(
    pkg_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    body: PromoteBody = Body(...),
):
    _require_upload(authorization)
    pid = (pkg_id or "").strip()
    if not pid:
        raise HTTPException(400, "pkg_id 无效")
    try:
        saved = promote_draft_to_stable(pid, body.from_version.strip())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if str(saved.get("artifact") or "").strip().lower() == "employee_pack":
        sf = get_session_factory()
        with sf() as db:
            upsert_catalog_item_from_xc_package_dict(db, saved, author_id=None)
            db.commit()
    _invalidate_catalog_list_caches(saved.get("id"), saved.get("version"))
    return {"ok": True, "package": saved}


@router.get("/index.json", summary="轻量全量索引")
def api_index_json():
    from modstore_server import cache

    p = packages_path()
    # Key includes file mtime so a new upload naturally produces a new cache key;
    # old key expires in 60 s, effectively rate-limiting filesystem reads.
    mtime = int(p.stat().st_mtime) if p.is_file() else 0
    ck = f"catalog:v1:{_catalog_cache_scope()}:index:{mtime}"
    cached = cache.get_json(ck)
    if cached is not None:
        return cached
    from modstore_server.catalog_public_index import build_public_index_packages

    result = {"packages": build_public_index_packages()}
    cache.set_json(ck, result, ttl_seconds=60)
    return result


@router.get("/packages/{pkg_id}/{version}/download", summary="下载已上传包文件")
def api_download(pkg_id: str, version: str):
    from modstore_server.catalog_store import files_dir

    r = get_package(pkg_id, version)
    if not r:
        raise HTTPException(404, "未找到")
    if is_private_package(r):
        raise HTTPException(404, "客户交付种子包需授权下载")
    name = r.get("stored_filename")
    if not name:
        raise HTTPException(404, "该记录无本地文件")
    path = files_dir() / str(name)
    if not path.is_file():
        raise HTTPException(404, "文件缺失")
    from fastapi.responses import FileResponse

    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/packages", summary="登记新包（multipart：metadata JSON + file）")
async def api_upload_package(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    metadata: str = Form(..., description="JSON 字符串，字段与 PackageRecord 一致"),
    file: UploadFile = File(...),
):
    auth_mode = _authorize_upload(authorization)
    import json

    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        raise HTTPException(400, "metadata 须为 JSON")
    if not isinstance(meta, dict):
        raise HTTPException(400, "metadata 须为对象")
    if not (str(meta.get("id") or "").strip() and str(meta.get("version") or "").strip()):
        raise HTTPException(400, "metadata 须含 id 与 version")
    rec: Dict[str, Any] = dict(meta)
    requested_public_listing = rec.get("public_listing", False)
    if not isinstance(requested_public_listing, bool):
        raise HTTPException(400, "public_listing 必须为 boolean")
    public_listing = requested_public_listing
    if not public_listing:
        rec.pop("public_listing", None)
    if public_listing and auth_mode != "auto_publish":
        raise HTTPException(403, "公开上架必须使用自动发布专用凭证")
    if is_private_package(rec):
        raise HTTPException(403, "客户私包须走已绑定 owner 的工单生产中心，禁止通用 Catalog 上传")
    artifact = str(rec.get("artifact") or "").strip().lower()
    pkg_id = str(rec.get("id") or "").strip()
    version = str(rec.get("version") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", pkg_id):
        raise HTTPException(400, "metadata.id 格式无效")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,31}", version):
        raise HTTPException(400, "metadata.version 格式无效")
    if public_listing and is_planned_duty_employee_pack(pkg_id, artifact):
        raise HTTPException(403, "编制内运维员工禁止公开上架")
    has_explicit_v2 = isinstance(rec.get("employee_config_v2"), dict)
    is_employee_upload = artifact == "employee_pack" or has_explicit_v2
    v2cfg = extract_or_upgrade_v2_config(rec) if is_employee_upload else {}
    sf = get_session_factory()
    if is_employee_upload:
        with sf() as db:
            errs = validate_v2_config(
                v2cfg,
                db=db,
                user_id=None,
                require_workflow_heart=True,
                require_workflow_sandbox=True,
            )
        if errs:
            raise HTTPException(400, "V2 配置校验失败: " + "; ".join(errs))
        rec["employee_config_v2"] = v2cfg
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xcmod", ".xcemp", ".zip"}:
        raise HTTPException(400, "file 须为 .xcmod / .xcemp / .zip")

    raw_bytes = await file.read()
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    automation_provenance: Dict[str, str] | None = None
    if public_listing:
        automation_provenance = _validated_automation_provenance(
            rec.get("automation_provenance"), package_sha256=raw_sha256
        )
    audit_meta: Dict[str, Any] = {}
    art = str(rec.get("artifact") or "").strip().lower()
    if art in ("mod", "employee_pack"):
        audit_meta["artifact"] = art
    if is_employee_upload and v2cfg:
        audit_meta["employee_config_v2"] = v2cfg
    probe = str(rec.get("probe_mod_id") or "").strip()
    if probe:
        audit_meta["probe_mod_id"] = probe

    from modstore_server.package_sandbox_audit import run_package_audit_async

    existing = get_package(str(rec.get("id")), str(rec.get("version")))
    if existing and public_listing and is_private_package(existing):
        raise HTTPException(403, "已有客户/内部包不能通过通用重试改为公开")
    if existing and str(existing.get("sha256") or "") != raw_sha256:
        raise HTTPException(409, "已发布 version 不可覆盖；源码变更须提升 manifest.version")
    # Inspect the actual archive as well as caller metadata: public metadata must
    # not disguise a private/customer manifest, including idempotent retries.
    with tempfile.TemporaryDirectory() as td:
        manifest_path = Path(td) / "upload.zip"
        manifest_path.write_bytes(raw_bytes)
        manifest = read_package_manifest_from_zip(manifest_path)
    if not manifest:
        raise HTTPException(400, "包内缺少有效 manifest.json")
    if is_private_package(manifest):
        raise HTTPException(403, "客户私包须走已绑定 owner 的工单生产中心")
    if public_listing:
        try:
            require_public_manifest(manifest)
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
    if str(manifest.get("id") or "") != pkg_id or str(manifest.get("version") or "") != version:
        raise HTTPException(400, "metadata 与包内 manifest id/version 不一致")
    if public_listing:
        from modstore_server.customer_delivery_package import verify_delivery_package
        from modstore_server.operational_errors import BOUNDARY_ERRORS

        try:
            verified = verify_delivery_package(raw_bytes)
        except BOUNDARY_ERRORS as exc:
            raise HTTPException(400, "公开发布包必须通过宿主受信 Ed25519 验签") from exc
        if verified.get("manifest") != manifest or verified.get("package_sha256") != raw_sha256:
            raise HTTPException(400, "受信签名包身份与发布 metadata 不一致")
    existing_review = existing.get("review") if isinstance(existing, dict) else None
    if (
        existing
        and str(existing.get("sha256") or "") == raw_sha256
        and isinstance(existing_review, dict)
        and bool((existing_review.get("summary") or {}).get("pass"))
    ):
        _upsert_market_listing(existing, public_listing=public_listing)
        _invalidate_catalog_list_caches(existing.get("id"), existing.get("version"))
        semantic_indexed = await _try_index_catalog_item(existing)
        return {
            "ok": True,
            "idempotent": True,
            "package": existing,
            "review": existing_review,
            "public_listing": public_listing,
            "semantic_indexed": semantic_indexed,
        }

    rep = await run_package_audit_async(raw_bytes, audit_meta if audit_meta else None)
    if not rep.get("ok"):
        raise HTTPException(400, str(rep.get("error") or "包审核失败"))
    summary = rep.get("summary") or {}
    if not summary.get("pass"):
        raise HTTPException(400, "五维审核未通过，禁止上架")
    review = {
        "summary": summary,
        "dimensions": rep.get("dimensions") or {},
        "functional_tests": rep.get("functional_tests") or [],
    }
    rec["review"] = review
    if automation_provenance is not None:
        rec["automation_provenance"] = automation_provenance

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / Path(file.filename or "upload.bin").name
        tmp.write_bytes(raw_bytes)
        if str(rec.get("artifact") or "").strip().lower() == "employee_pack":
            from modstore_server.catalog_store import package_manifest_alignment_errors

            align_errs = package_manifest_alignment_errors(rec, tmp)
            if align_errs:
                raise HTTPException(
                    400,
                    "员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs),
                )
        if public_listing and sha256_file(tmp) != raw_sha256:
            raise HTTPException(400, "审核后的包摘要与来源证明不一致；修正源码后重新打包")
        try:
            saved = append_package(rec, tmp)
        except PackageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    _upsert_market_listing(saved, public_listing=public_listing)

    # Invalidate all list/index caches; individual detail keys expire on their own TTL.
    _invalidate_catalog_list_caches(saved.get("id"), saved.get("version"))

    semantic_indexed = await _try_index_catalog_item(saved)

    return {
        "ok": True,
        "idempotent": False,
        "package": saved,
        "review": review,
        "public_listing": public_listing,
        "semantic_indexed": semantic_indexed,
    }


@router.get("/catalog/industries", summary="获取标准化行业分类树")
def api_get_industries():
    return {"industries": get_industry_tree()}


@router.get("/catalog/search-semantic", summary="语义搜索商品")
def api_search_semantic(
    q: str = Query(..., description="搜索查询文本"),
    artifact: Optional[str] = Query(None, description="按类型过滤"),
    industry: Optional[str] = Query(None, description="按行业过滤"),
    limit: int = Query(20, ge=1, le=100),
):
    filter_meta = {}
    if artifact:
        filter_meta["artifact"] = artifact
    if industry:
        filter_meta["industry"] = industry

    results = query_similar(q, limit=limit, filter_meta=filter_meta if filter_meta else None)
    return {"results": results, "total": len(results)}


@router.get("/catalog/recommend-similar", summary="相似商品推荐")
def api_recommend_similar(
    id: str = Query(..., description="商品 ID"),
    limit: int = Query(10, ge=1, le=50),
):
    item_id = (id or "").strip()
    if not item_id:
        raise HTTPException(400, "id 参数不能为空")

    pkg = get_package(item_id, "")
    if not pkg:
        rows, _ = list_packages(limit=500, offset=0)
        pkg = next((r for r in rows if r.get("id") == item_id), None)

    if not pkg:
        raise HTTPException(404, "未找到商品")

    text = f"{pkg.get('name', '')} {pkg.get('description', '')}"
    results = query_similar(text, limit=limit + 1)

    current_id = pkg.get("id")
    filtered = [r for r in results if r.get("metadata", {}).get("pkg_id") != current_id]
    return {"results": filtered[:limit], "total": len(filtered[:limit])}
