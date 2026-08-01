"""公网 Catalog 只读/上传 API（挂载在 XC AGI 服务 /v1）。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
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

from modstore_server.catalog_store import (
    append_package,
    get_package,
    list_packages,
    list_versions,
    packages_path,
    promote_draft_to_stable,
)
from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
from modstore_server.employee_config_v2 import (
    extract_or_upgrade_v2_config,
    validate_v2_config,
)
from modstore_server.duty_roster import is_planned_duty_employee_pack
from modstore_server.industry_taxonomy import get_industry_tree
from modstore_server.models import get_session_factory
from modstore_server.vector_store import insert_embedding, query_similar

router = APIRouter(prefix="/v1", tags=["catalog"])


def _is_customer_delivery_seed(row: Dict[str, Any] | None) -> bool:
    return str((row or {}).get("artifact") or "").strip().lower() == "customer_delivery_seed"


def _invalidate_catalog_list_caches(pkg_id: Any = None, version: Any = None) -> None:
    """Best-effort cache invalidation after a write.

    List/index caches use parameter-hashed keys that cannot be enumerated, so
    we rely on their short TTL (300 s / 60 s) to expire naturally.  The only
    key we can reliably delete is the per-package detail key.
    """
    from modstore_server import cache

    if pkg_id and version:
        cache.delete(f"catalog:v1:pkg:{pkg_id}:{version}")


def _upload_token() -> str:
    return (os.environ.get("MODSTORE_CATALOG_UPLOAD_TOKEN") or "").strip()


def _auto_publish_token() -> str:
    return (os.environ.get("MODSTORE_AUTO_PUBLISH_TOKEN") or "").strip()


def _authorize_upload(authorization: Optional[str]) -> str:
    supplied = (authorization or "").strip()
    upload = _upload_token()
    auto = _auto_publish_token()
    if auto and secrets.compare_digest(supplied, f"Bearer {auto}"):
        return "auto_publish"
    if upload and secrets.compare_digest(supplied, f"Bearer {upload}"):
        return "upload"
    if not upload and not auto:
        raise HTTPException(503, "未配置 Catalog 上传凭证，拒绝写入")
    raise HTTPException(401, "无效的上传凭证")


def _require_upload(authorization: Optional[str]) -> None:
    _authorize_upload(authorization)


def _validated_automation_provenance(value: Any, *, package_sha256: str) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise HTTPException(400, "自动上架必须提供 automation_provenance")
    repository = str(value.get("source_repository") or "").strip()
    expected_repository = (
        os.environ.get("MODSTORE_AUTO_PUBLISH_REPOSITORY") or "42433422/XCMAX"
    ).strip()
    source_sha = str(value.get("source_sha") or "").strip()
    workflow_run_id = str(value.get("workflow_run_id") or "").strip()
    claimed_sha = str(value.get("package_sha256") or "").strip()
    if repository != expected_repository:
        raise HTTPException(403, "自动上架来源仓库不在允许范围")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise HTTPException(400, "automation_provenance.source_sha 无效")
    if not re.fullmatch(r"[1-9][0-9]*", workflow_run_id):
        raise HTTPException(400, "automation_provenance.workflow_run_id 无效")
    if not secrets.compare_digest(claimed_sha, package_sha256):
        raise HTTPException(400, "automation_provenance.package_sha256 与上传包不一致")
    return {
        "source_repository": repository,
        "source_sha": source_sha,
        "workflow_run_id": workflow_run_id,
        "package_sha256": package_sha256,
    }


def _upsert_market_listing(saved: Dict[str, Any], *, public_listing: bool) -> None:
    from modstore_server.models import CatalogItem

    sf = get_session_factory()
    with sf() as db:
        upsert_catalog_item_from_xc_package_dict(db, saved, author_id=None)
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == str(saved.get("id"))).first()
        if row and public_listing:
            row.is_public = True
            row.compliance_status = "approved"
            row.delist_reason = ""
        db.commit()
    if public_listing:
        from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

        _invalidate_market_catalog_caches()


def _params_hash(*args: Any) -> str:
    """Stable short hash of query parameter values for use in cache keys."""
    return hashlib.sha1(json.dumps(args, sort_keys=True).encode()).hexdigest()[:12]


@router.get("/packages", summary="分页列出包")
def api_list_packages(
    artifact: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    from modstore_server import cache

    ck = f"catalog:v1:packages:list:{_params_hash(artifact, q, limit, offset)}"
    cached = cache.get_json(ck)
    if cached is not None:
        return cached
    rows, total = list_packages(artifact=artifact, q=q, limit=limit, offset=offset)
    rows = [r for r in rows if not _is_customer_delivery_seed(r)]
    if artifact and str(artifact).strip().lower() == "customer_delivery_seed":
        total = 0
    result = {"packages": rows, "total": total, "limit": limit, "offset": offset}
    cache.set_json(ck, result, ttl_seconds=300)
    return result


@router.get("/packages/{pkg_id}/{version}", summary="包详情")
def api_get_package(pkg_id: str, version: str):
    from modstore_server import cache

    ck = f"catalog:v1:pkg:{pkg_id}:{version}"
    cached = cache.get_json(ck)
    if cached is not None:
        return cached
    r = get_package(pkg_id, version)
    if not r or _is_customer_delivery_seed(r):
        raise HTTPException(404, "未找到该版本")
    cache.set_json(ck, r, ttl_seconds=600)
    return r


@router.get("/packages/by-id/{pkg_id}/versions", summary="同 id 下所有版本（含 draft/stable）")
def api_package_versions(pkg_id: str):
    pid = (pkg_id or "").strip()
    if not pid:
        raise HTTPException(400, "pkg_id 无效")
    versions = [r for r in list_versions(pid) if not _is_customer_delivery_seed(r)]
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
    ck = f"catalog:v1:index:{mtime}"
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
    if _is_customer_delivery_seed(r):
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
    requested_public_listing = rec.pop("public_listing", False)
    if not isinstance(requested_public_listing, bool):
        raise HTTPException(400, "public_listing 必须为 boolean")
    public_listing = requested_public_listing
    if public_listing and auth_mode != "auto_publish":
        raise HTTPException(403, "公开上架必须使用自动发布专用凭证")
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
    existing_review = existing.get("review") if isinstance(existing, dict) else None
    if (
        existing
        and str(existing.get("sha256") or "") == raw_sha256
        and isinstance(existing_review, dict)
        and bool((existing_review.get("summary") or {}).get("pass"))
    ):
        if automation_provenance is not None:
            existing["automation_provenance"] = automation_provenance
            existing = append_package(existing, None)
        _upsert_market_listing(existing, public_listing=public_listing)
        _invalidate_catalog_list_caches(existing.get("id"), existing.get("version"))
        return {
            "ok": True,
            "idempotent": True,
            "package": existing,
            "review": existing_review,
            "public_listing": public_listing,
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
        tmp = Path(td) / (file.filename or "upload.bin")
        tmp.write_bytes(raw_bytes)
        if str(rec.get("artifact") or "").strip().lower() == "employee_pack":
            from modstore_server.catalog_store import package_manifest_alignment_errors

            align_errs = package_manifest_alignment_errors(rec, tmp)
            if align_errs:
                raise HTTPException(
                    400,
                    "员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs),
                )
        saved = append_package(rec, tmp)

    _upsert_market_listing(saved, public_listing=public_listing)

    # Invalidate all list/index caches; individual detail keys expire on their own TTL.
    _invalidate_catalog_list_caches(saved.get("id"), saved.get("version"))

    embedding_text = f"{saved.get('name', '')} {saved.get('description', '')}"
    if embedding_text.strip():
        item_id = f"{saved.get('id')}:{saved.get('version')}"
        insert_embedding(
            item_id=item_id,
            text=embedding_text,
            metadata={
                "pkg_id": saved.get("id"),
                "version": saved.get("version"),
                "artifact": saved.get("artifact", "mod"),
                "industry": saved.get("industry", "通用"),
            },
        )

    return {
        "ok": True,
        "idempotent": False,
        "package": saved,
        "review": review,
        "public_listing": public_listing,
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
