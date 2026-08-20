# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.market_catalog_api")


@_facade().router.get("/market/catalog/workflow-employee-pack/bundle")
def api_workflow_employee_pack_bundle(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
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


@_facade().router.get("/market/catalog/{item_id}")
def api_market_catalog_detail(
    item_id: int,
    user: _facade().Optional[_facade().User] = _facade().Depends(_facade()._optional_current_user),
):
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
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("market catalog detail: complaint count skipped (%s)", exc)
            complaint_count = 0
        payload = _facade()._catalog_item_payload(
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


def _enrich_catalog_creator_profile(
    session, item: _facade().CatalogItem, payload: _facade().Dict[str, _facade().Any]
) -> None:
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
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("creator stats skipped for catalog %s: %s", item.id, exc)
    works_count = 0
    author_payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
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
                    _facade().CatalogItem.is_public.is_(True),
                    _facade().CatalogItem.compliance_status != "delisted",
                )
                .count()
            )
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.debug("creator author skipped for catalog %s: %s", item.id, exc)
    payload["author"] = author_payload
    payload["creator_stats"] = {
        "favorite_count": fav_count,
        "review_count": review_count,
        "average_rating": avg_rating,
        "works_count": works_count,
    }
