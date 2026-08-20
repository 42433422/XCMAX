# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.market_catalog_api")


@_facade().router.get("/market/facets")
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
                _facade()._normalize_material_category(cat, art)
                for cat, art in session.query(
                    _facade().CatalogItem.material_category, _facade().CatalogItem.artifact
                )
                .filter(*pub_filters)
                .all()
                if _facade()._normalize_material_category(cat, art)
            }
        )
        license_scopes = sorted(
            {
                _facade()._normalize_license_scope(t[0], 0)
                for t in session.query(_facade().CatalogItem.license_scope)
                .filter(*pub_filters)
                .distinct()
                .all()
                if _facade()._normalize_license_scope(t[0], 0)
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
            "material_category_labels": _facade().MATERIAL_CATEGORY_LABELS,
            "license_scopes": license_scopes,
            "license_scope_labels": _facade().LICENSE_SCOPE_LABELS,
            "security_levels": security_levels,
            "compliance_statuses": compliance_statuses,
        }
    cache.set_json(ck, result, ttl_seconds=600)
    return result


@_facade().router.get("/market/catalog")
def api_market_catalog(
    q: _facade().Optional[str] = _facade().Query(None),
    artifact: _facade().Optional[str] = _facade().Query(None),
    material_category: _facade().Optional[str] = _facade().Query(None),
    industry: _facade().Optional[str] = _facade().Query(None),
    license_scope: _facade().Optional[str] = _facade().Query(None),
    security_level: _facade().Optional[str] = _facade().Query(None),
    collection: _facade()
    .Optional[str] = _facade()
    .Query(
        None,
        description="主题集合：office_employee_pack=办公员工包（10 个表格类）；office_employee_aux_pack_1=办公员工附属包1",
    ),
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().Optional[_facade().User] = _facade().Depends(_facade()._optional_current_user),
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
        complaint_counts: _facade().Dict[int, int] = {}
        favorite_counts: _facade().Dict[int, int] = {}
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
                except _facade().RECOVERABLE_ERRORS as exc:
                    _facade().logger.warning("market catalog: favorited ids unavailable (%s)", exc)
            try:
                from sqlalchemy import func

                count_rows = (
                    session.query(_facade().Favorite.catalog_id, func.count(_facade().Favorite.id))
                    .filter(_facade().Favorite.catalog_id.in_(ids))
                    .group_by(_facade().Favorite.catalog_id)
                    .all()
                )
                favorite_counts = {int(cid): int(cnt) for cid, cnt in count_rows}
            except _facade().RECOVERABLE_ERRORS as exc:
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
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.warning("market catalog: complaint counts unavailable (%s)", exc)
        result = {
            "items": [
                _facade()._catalog_item_payload(
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


@_facade().router.get("/market/catalog/office-employee-pack/bundle")
def api_office_employee_pack_bundle(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
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


@_facade().router.get("/market/catalog/host-foundation-employee-pack/download")
def api_host_foundation_employee_pack_download(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """下载宿主基础能力预装员工包（.xcemp）。"""
    from io import BytesIO

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
                _facade().CatalogItem.is_public.is_(True),
                _facade().CatalogItem.compliance_status != "delisted",
            )
            .order_by(_facade().CatalogItem.id.desc())
            .first()
        )
        if not item or not item.stored_filename:
            raise _facade().HTTPException(404, "宿主基础员工包尚未上架或文件缺失")
        path = files_dir() / item.stored_filename
        if not path.is_file():
            raise _facade().HTTPException(404, "宿主基础员工包文件不存在")
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
