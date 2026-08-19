# ruff: noqa
"""Public market browsing, facets, bundles, details, and creator enrichment."""
from __future__ import annotations
import logging
import sys
from typing import Any, Dict, Optional
from fastapi import Depends, HTTPException, Query
from modstore_server.market_shared import (
    LICENSE_SCOPE_LABELS,
    MATERIAL_CATEGORY_LABELS,
    _catalog_item_payload,
    _get_current_user,
    _normalize_license_scope,
    _normalize_material_category,
    _optional_current_user,
)
from modstore_server.models import (
    CatalogComplaint,
    CatalogItem,
    Favorite,
    Purchase,
    Review,
    User,
    get_session_factory,
)

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["modstore_server.market_catalog_api"]


router = _facade().router


@router.get("/market/facets")
def api_market_facets():
    from modstore_server import cache

    ck = "market:facets"
    cached = cache.get_json(ck)
    if cached is not None:
        return cached
    sf = _facade().get_session_factory()
    with sf() as session:
        pub_filters = _facade()._market_catalog_visibility_filters()
        industries = sorted(
            {
                t[0]
                for t in session.query(_facade().CatalogItem.industry)
                .filter(*pub_filters)
                .distinct()
                .all()
                if t[0]
            }
        )
        artifacts = sorted(
            {
                t[0]
                for t in session.query(_facade().CatalogItem.artifact)
                .filter(*pub_filters)
                .distinct()
                .all()
                if t[0]
            }
        )
        security_levels = sorted(
            {
                t[0]
                for t in session.query(_facade().CatalogItem.security_level)
                .filter(*pub_filters)
                .distinct()
                .all()
                if t[0]
            }
        )
        material_categories = sorted(
            {
                _normalize_material_category(cat, art)
                for (cat, art) in session.query(
                    _facade().CatalogItem.material_category, _facade().CatalogItem.artifact
                )
                .filter(*pub_filters)
                .all()
                if _normalize_material_category(cat, art)
            }
        )
        license_scopes = sorted(
            {
                _normalize_license_scope(t[0], 0)
                for t in session.query(_facade().CatalogItem.license_scope)
                .filter(*pub_filters)
                .distinct()
                .all()
                if _normalize_license_scope(t[0], 0)
            }
        )
        compliance_statuses = sorted(
            {
                t[0]
                for t in session.query(_facade().CatalogItem.compliance_status)
                .filter(*pub_filters)
                .distinct()
                .all()
                if t[0]
            }
        )
        result = {
            "industries": industries,
            "artifacts": artifacts,
            "material_categories": material_categories,
            "material_category_labels": MATERIAL_CATEGORY_LABELS,
            "license_scopes": license_scopes,
            "license_scope_labels": LICENSE_SCOPE_LABELS,
            "security_levels": security_levels,
            "compliance_statuses": compliance_statuses,
        }
    cache.set_json(ck, result, ttl_seconds=600)
    return result


@router.get("/market/catalog")
def api_market_catalog(
    q: Optional[str] = Query(None),
    artifact: Optional[str] = Query(None),
    material_category: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    license_scope: Optional[str] = Query(None),
    security_level: Optional[str] = Query(None),
    collection: Optional[str] = Query(
        None,
        description="主题集合：office_employee_pack=办公员工包（10 个表格类）；office_employee_aux_pack_1=办公员工附属包1",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: Optional[User] = Depends(_optional_current_user),
):
    from modstore_server import cache

    user_key = str(user.id) if user else "anon"
    ck = f"market:catalog:{_facade()._market_params_hash(q, artifact, material_category, industry, license_scope, security_level, collection, limit, offset)}:{user_key}"
    cached = cache.get_json(ck)
    if cached is not None:
        return cached
    sf = _facade().get_session_factory()
    with sf() as session:
        query = session.query(_facade().CatalogItem).filter(
            *_facade()._market_catalog_visibility_filters()
        )
        if q:
            ql = q.lower()
            query = query.filter(
                _facade().CatalogItem.name.ilike(f"%{ql}%")
                | _facade().CatalogItem.pkg_id.ilike(f"%{ql}%")
                | _facade().CatalogItem.description.ilike(f"%{ql}%")
            )
        if artifact:
            query = query.filter(_facade().CatalogItem.artifact == artifact)
        if material_category:
            mapped_artifacts = {
                "ai_employee": ["employee_pack"],
                "workflow_template": ["workflow_template"],
                "page_style": ["surface"],
                "mod_asset": ["mod", "bundle"],
            }.get(material_category, [])
            cond = _facade().CatalogItem.material_category == material_category
            if mapped_artifacts:
                cond = cond | (
                    _facade().CatalogItem.material_category == ""
                ) & _facade().CatalogItem.artifact.in_(mapped_artifacts)
            query = query.filter(cond)
        if industry:
            query = query.filter(_facade().CatalogItem.industry == industry)
        if license_scope:
            query = query.filter(_facade().CatalogItem.license_scope == license_scope)
        if security_level:
            query = query.filter(_facade().CatalogItem.security_level == security_level)
        if collection == "office_employee_pack":
            from modstore_server.office_employee_pack import OFFICE_EMPLOYEE_PKG_IDS

            query = query.filter(_facade().CatalogItem.pkg_id.in_(list(OFFICE_EMPLOYEE_PKG_IDS)))
        elif collection == "office_employee_aux_pack_1":
            from modstore_server.office_employee_aux_pack_1 import OFFICE_AUX_PACK_1_PKG_IDS_LIST

            query = query.filter(_facade().CatalogItem.pkg_id.in_(OFFICE_AUX_PACK_1_PKG_IDS_LIST))
        elif collection == "workflow_employee":
            from modstore_server.workflow_employee_pack import WORKFLOW_EMPLOYEE_PKG_IDS

            query = query.filter(_facade().CatalogItem.pkg_id.in_(list(WORKFLOW_EMPLOYEE_PKG_IDS)))
        elif collection == "host_foundation":
            from modstore_server.host_foundation_pack import HOST_FOUNDATION_EMPLOYEE_PACK_ID

            query = query.filter(_facade().CatalogItem.pkg_id == HOST_FOUNDATION_EMPLOYEE_PACK_ID)
        elif not collection:
            from modstore_server.host_foundation_pack import INFRASTRUCTURE_PKG_IDS

            query = query.filter(~_facade().CatalogItem.pkg_id.in_(list(INFRASTRUCTURE_PKG_IDS)))
            query = query.filter(~_facade().CatalogItem.pkg_id.like("xcagi-%-bridge"))
        total = query.count()
        rows = (
            query.order_by(
                _facade().CatalogItem.rank_score.desc(), _facade().CatalogItem.created_at.desc()
            )
            .offset(offset)
            .limit(limit)
            .all()
        )
        purchased_ids = set()
        favorited_ids = set()
        if user:
            purchased_rows = (
                session.query(_facade().Purchase.catalog_id)
                .filter(_facade().Purchase.user_id == user.id)
                .all()
            )
            purchased_ids = {r[0] for r in purchased_rows}
        complaint_counts: Dict[int, int] = {}
        favorite_counts: Dict[int, int] = {}
        if rows:
            ids = [r.id for r in rows]
            if user:
                try:
                    fav_rows = (
                        session.query(_facade().Favorite.catalog_id)
                        .filter(
                            _facade().Favorite.user_id == user.id,
                            _facade().Favorite.catalog_id.in_(ids),
                        )
                        .all()
                    )
                    favorited_ids = {int(r[0]) for r in fav_rows}
                except Exception as exc:
                    _facade().logger.warning("market catalog: favorited ids unavailable (%s)", exc)
            try:
                from sqlalchemy import func

                count_rows = (
                    session.query(_facade().Favorite.catalog_id, func.count(_facade().Favorite.id))
                    .filter(_facade().Favorite.catalog_id.in_(ids))
                    .group_by(_facade().Favorite.catalog_id)
                    .all()
                )
                favorite_counts = {int(cid): int(cnt) for (cid, cnt) in count_rows}
            except Exception as exc:
                _facade().logger.warning("market catalog: favorite counts unavailable (%s)", exc)
            try:
                counts = (
                    session.query(
                        _facade().CatalogComplaint.catalog_id, _facade().CatalogComplaint.id
                    )
                    .filter(_facade().CatalogComplaint.catalog_id.in_(ids))
                    .all()
                )
                for catalog_id, _ in counts:
                    complaint_counts[int(catalog_id)] = complaint_counts.get(int(catalog_id), 0) + 1
            except Exception as exc:
                _facade().logger.warning("market catalog: complaint counts unavailable (%s)", exc)
        result = {
            "items": [
                _catalog_item_payload(
                    r,
                    purchased=r.id in purchased_ids,
                    favorited=int(r.id) in favorited_ids,
                    favorite_count=favorite_counts.get(int(r.id), 0),
                    complaint_count=complaint_counts.get(int(r.id), 0),
                )
                for r in rows
            ],
            "total": total,
        }
    cache.set_json(ck, result, ttl_seconds=60)
    return result


@router.get("/market/catalog/office-employee-pack/bundle")
def api_office_employee_pack_bundle(user: User = Depends(_get_current_user)):
    """一键下载办公员工包：10 个表格类 AI 员工 ZIP 合集。"""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from modstore_server.office_employee_pack import (
        BUNDLE_ARCHIVE_NAME,
        build_office_employee_bundle_zip,
    )

    sf = _facade().get_session_factory()
    with sf() as session:
        data = build_office_employee_bundle_zip(session)
    buf = BytesIO(data)
    buf.seek(0)

    def generate():
        while chunk := buf.read(8192):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={BUNDLE_ARCHIVE_NAME}",
            "Content-Length": str(len(data)),
        },
    )


@router.get("/market/catalog/host-foundation-employee-pack/download")
def api_host_foundation_employee_pack_download(user: User = Depends(_get_current_user)):
    """下载宿主基础能力预装员工包（.xcemp）。"""
    from io import BytesIO
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse
    from modstore_server.catalog_store import files_dir
    from modstore_server.host_foundation_pack import (
        BUNDLE_ARCHIVE_NAME,
        HOST_FOUNDATION_EMPLOYEE_PACK_ID,
    )

    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem)
            .filter(
                _facade().CatalogItem.pkg_id == HOST_FOUNDATION_EMPLOYEE_PACK_ID,
                _facade().CatalogItem.is_public == True,
                _facade().CatalogItem.compliance_status != "delisted",
            )
            .order_by(_facade().CatalogItem.id.desc())
            .first()
        )
        if not item or not item.stored_filename:
            raise HTTPException(404, "宿主基础员工包尚未上架或文件缺失")
        path = files_dir() / item.stored_filename
        if not path.is_file():
            raise HTTPException(404, "宿主基础员工包文件不存在")
        data = path.read_bytes()
    buf = BytesIO(data)
    buf.seek(0)

    def generate():
        while chunk := buf.read(8192):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={BUNDLE_ARCHIVE_NAME}",
            "Content-Length": str(len(data)),
        },
    )


@router.get("/market/catalog/workflow-employee-pack/bundle")
def api_workflow_employee_pack_bundle(user: User = Depends(_get_current_user)):
    """一键下载工作流员工包：6 个独立工作流员工 Mod ZIP 合集。"""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from modstore_server.workflow_employee_pack import (
        BUNDLE_ARCHIVE_NAME,
        build_workflow_employee_bundle_zip,
    )

    sf = _facade().get_session_factory()
    with sf() as session:
        data = build_workflow_employee_bundle_zip(session)
    buf = BytesIO(data)
    buf.seek(0)

    def generate():
        while chunk := buf.read(8192):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={BUNDLE_ARCHIVE_NAME}",
            "Content-Length": str(len(data)),
        },
    )


@router.get("/market/catalog/{item_id}")
def api_market_catalog_detail(item_id: int, user: Optional[User] = Depends(_optional_current_user)):
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        _facade()._reject_internal_duty_catalog_item(item)
        purchased = False
        favorited = False
        user_has_review = False
        if user:
            purchased = (
                session.query(_facade().Purchase)
                .filter(
                    _facade().Purchase.user_id == user.id, _facade().Purchase.catalog_id == item.id
                )
                .first()
                is not None
            )
            favorited = (
                session.query(_facade().Favorite)
                .filter(
                    _facade().Favorite.user_id == user.id, _facade().Favorite.catalog_id == item.id
                )
                .first()
                is not None
            )
            user_has_review = (
                session.query(_facade().Review)
                .filter(_facade().Review.user_id == user.id, _facade().Review.catalog_id == item.id)
                .first()
                is not None
            )
        try:
            complaint_count = (
                session.query(_facade().CatalogComplaint)
                .filter(_facade().CatalogComplaint.catalog_id == item.id)
                .count()
            )
        except Exception as exc:
            _facade().logger.warning("market catalog detail: complaint count skipped (%s)", exc)
            complaint_count = 0
        payload = _catalog_item_payload(
            item,
            purchased=purchased,
            favorited=favorited,
            user_has_review=user_has_review,
            complaint_count=complaint_count,
        )
        if item.artifact == "employee_pack" and item.pkg_id:
            _facade()._enrich_payload_with_manifest(payload, item.pkg_id, session)
        _facade()._enrich_catalog_creator_profile(session, item, payload)
        return payload


def _enrich_catalog_creator_profile(session, item: CatalogItem, payload: Dict[str, Any]) -> None:
    """详情页创作者主页区：作者信息、安装/收藏/评价统计。"""
    payload["install_count"] = int(getattr(item, "install_count", 0) or 0)
    fav_count = 0
    review_count = 0
    avg_rating = 0.0
    try:
        fav_count = (
            session.query(_facade().Favorite)
            .filter(_facade().Favorite.catalog_id == item.id)
            .count()
        )
        reviews = (
            session.query(_facade().Review).filter(_facade().Review.catalog_id == item.id).all()
        )
        review_count = len(reviews)
        if reviews:
            avg_rating = round(sum((int(r.rating or 0) for r in reviews)) / len(reviews), 2)
    except Exception as exc:
        _facade().logger.debug("creator stats skipped for catalog %s: %s", item.id, exc)
    works_count = 0
    author_payload: Optional[Dict[str, Any]] = None
    if item.author_id:
        try:
            author = (
                session.query(_facade().User).filter(_facade().User.id == item.author_id).first()
            )
            if author:
                uname = str(author.username or "").strip() or f"用户{item.author_id}"
                author_payload = {
                    "id": int(author.id),
                    "username": uname,
                    "avatar_initial": (uname[0] if uname else "创").upper(),
                }
            works_count = (
                session.query(_facade().CatalogItem)
                .filter(
                    _facade().CatalogItem.author_id == item.author_id,
                    _facade().CatalogItem.is_public == True,
                    _facade().CatalogItem.compliance_status != "delisted",
                )
                .count()
            )
        except Exception as exc:
            _facade().logger.debug("creator author skipped for catalog %s: %s", item.id, exc)
    payload["author"] = author_payload
    payload["creator_stats"] = {
        "favorite_count": fav_count,
        "review_count": review_count,
        "average_rating": avg_rating,
        "works_count": works_count,
    }
