"""Admin catalog listing and review; shares status predicates across filters and KPIs."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_

from modstore_server.api.deps import require_admin
from modstore_server.duty_roster import employee_partition_meta
from modstore_server.models import CatalogItem, User, get_session_factory

router = APIRouter()


class CatalogItemReviewDTO(BaseModel):
    """管理员审核商品：通过 / 限制 / 下架 / 恢复。"""

    action: str
    note: str = ""


CATALOG_REVIEW_ACTIONS = {"approve", "restrict", "delist", "restore"}


@router.get("/admin/catalog")
def api_admin_list_catalog(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str = Query("", max_length=24),
    search: str = Query("", max_length=200),
    user: User = Depends(require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        query = session.query(CatalogItem)
        state = func.coalesce(CatalogItem.compliance_status, "approved")
        predicates = {
            "pending": state == "under_review",
            "restricted": state == "restricted",
            "listed": and_(
                CatalogItem.is_public.is_(True),
                state.notin_(["under_review", "restricted", "delisted"]),
            ),
            "delisted": or_(
                state == "delisted",
                and_(
                    CatalogItem.is_public.is_not(True), state.notin_(["under_review", "restricted"])
                ),
            ),
        }
        kind = status.strip().lower()
        if kind in predicates:
            query = query.filter(predicates[kind])
        elif kind:
            raise HTTPException(422, "商品状态筛选条件无效")
        term = search.strip()
        if term:
            query = query.filter(
                or_(
                    CatalogItem.name.contains(term, autoescape=True),
                    CatalogItem.pkg_id.contains(term, autoescape=True),
                )
            )
        total = query.count()
        rows = query.order_by(CatalogItem.created_at.desc()).offset(offset).limit(limit).all()
        authors = (
            {
                int(u.id): u.username
                for u in session.query(User)
                .filter(User.id.in_([r.author_id for r in rows if r.author_id]))
                .all()
            }
            if rows
            else {}
        )
        counts = {"total": session.query(CatalogItem).count()}
        counts.update(
            {
                key: session.query(CatalogItem).filter(predicate).count()
                for key, predicate in predicates.items()
            }
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
                    "compliance_status": r.compliance_status or "approved",
                    "delist_reason": r.delist_reason or "",
                    "rank_score": r.rank_score,
                    "install_count": r.install_count,
                    "author_id": r.author_id,
                    "author_name": authors.get(int(r.author_id)) if r.author_id else "",
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    **employee_partition_meta(r.pkg_id, r.artifact),
                }
                for r in rows
            ],
            "total": total,
            "counts": counts,
        }


@router.post("/admin/catalog/{item_id}/review", summary="管理员审核并上下架商品")
def api_admin_review_catalog_item(
    item_id: int,
    body: CatalogItemReviewDTO,
    user: User = Depends(require_admin),
):
    action = (body.action or "").strip().lower()
    if action not in CATALOG_REVIEW_ACTIONS:
        raise HTTPException(400, "action 必须是 approve/restrict/delist/restore")
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        note = (body.note or "").strip()
        if action == "approve":
            item.compliance_status = "approved"
            item.is_public = True
            item.delist_reason = ""
        elif action == "restrict":
            item.compliance_status = "restricted"
            item.rank_score = max(0.0, float(item.rank_score or 100.0) - 30.0)
            item.delist_reason = note
        elif action == "delist":
            item.compliance_status = "delisted"
            item.is_public = False
            item.delist_reason = note or "管理员下架"
            item.rank_score = 0.0
        else:
            from modstore_server.catalog_store import market_item_available

            if not market_item_available(item):
                raise HTTPException(409, "商品文件或模板内容缺失，请修复发布记录后再恢复上架")
            item.compliance_status = "approved"
            item.is_public = True
            item.delist_reason = ""
            item.rank_score = max(float(item.rank_score or 0), 80.0)
        session.commit()
        result = {
            "ok": True,
            "id": item.id,
            "compliance_status": item.compliance_status,
            "is_public": bool(item.is_public),
            "delist_reason": item.delist_reason or "",
        }
    from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

    _invalidate_market_catalog_caches()
    return result
