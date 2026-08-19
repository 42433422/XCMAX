"""XC AGI 在线市场 API：目录浏览、搜索、评价、收藏、投诉。"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server.duty_roster import is_planned_duty_employee_pack
from modstore_server.market_shared import (
    _get_current_user,
    _optional_current_user,
    _require_admin,
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

router = APIRouter(tags=["market"])


def _enrich_payload_with_manifest(payload: Dict[str, Any], pkg_id: str, session) -> None:
    try:
        from modstore_server.employee_runtime import load_employee_pack

        pack = load_employee_pack(session, pkg_id)
        if not pack or not isinstance(pack.get("manifest"), dict):
            return
        manifest = pack["manifest"]
        emp = manifest.get("employee")
        if isinstance(emp, dict) and isinstance(emp.get("capabilities"), list):
            raw_caps = emp["capabilities"]
            formatted: list[dict[str, str]] = []
            for cap in raw_caps[:8]:
                if isinstance(cap, dict) and cap.get("label"):
                    formatted.append(
                        {
                            "label": str(cap["label"]),
                            "description": str(cap.get("description") or ""),
                        }
                    )
                elif isinstance(cap, str) and cap.strip():
                    formatted.append({"label": cap.strip(), "description": ""})
            if formatted:
                payload["capabilities"] = formatted
        raw_examples = manifest.get("examples")
        if isinstance(raw_examples, list) and raw_examples:
            ex_list: list[dict[str, Any]] = []
            for ex in raw_examples[:6]:
                if isinstance(ex, dict) and ex.get("title"):
                    ex_list.append(
                        {
                            "title": str(ex["title"]),
                            "description": str(ex.get("description") or ""),
                            "input": ex.get("input") if isinstance(ex.get("input"), dict) else {},
                        }
                    )
            if ex_list:
                payload["examples"] = ex_list
    except Exception as exc:  # noqa: BLE001
        logger.debug("catalog detail manifest enrichment skipped for %s: %s", pkg_id, exc)


def _market_catalog_visibility_filters():
    """公开市场列表：排除编制内运维 employee_pack（仅管理端 / 调度使用）。"""
    from sqlalchemy import and_

    from modstore_server.duty_roster import all_planned_employee_ids

    duty = list(all_planned_employee_ids())
    parts = [
        CatalogItem.is_public == True,  # noqa: E712
        CatalogItem.compliance_status != "delisted",
    ]
    if duty:
        parts.append(
            ~and_(
                CatalogItem.artifact == "employee_pack",
                CatalogItem.pkg_id.in_(duty),
            )
        )
    return parts


def _reject_internal_duty_catalog_item(item: CatalogItem) -> None:
    """用户侧市场路由：编制内运维包视为不存在（404）。"""
    if is_planned_duty_employee_pack(item.pkg_id, item.artifact):
        raise HTTPException(404, "商品不存在")


def _market_params_hash(*args: Any) -> str:
    return hashlib.sha1(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _invalidate_market_catalog_caches() -> None:
    """Invalidate market catalog list + facets caches after catalog writes."""
    from modstore_server import cache

    cache.delete("market:facets")
    client = cache._redis_client()  # noqa: SLF001 — shared infra helper
    if client is not None:
        try:
            for key in client.scan_iter(match="market:catalog:*", count=200):
                client.delete(key)
        except Exception:
            pass
    mem = getattr(cache, "_memory_cache", None)
    if isinstance(mem, dict):
        for key in list(mem.keys()):
            if str(key).startswith("market:catalog:") or key == "market:facets":
                mem.pop(key, None)


class ReviewSubmitDTO(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    content: str = Field(default="", max_length=4000)


class CatalogComplaintSubmitDTO(BaseModel):
    complaint_type: str = Field(default="other", max_length=32)
    reason: str = Field(..., min_length=4, max_length=4000)
    evidence: Dict[str, Any] = Field(default_factory=dict)


class CatalogComplaintReviewDTO(BaseModel):
    action: str = Field(..., description="resolve/reject/downrank/delist/restore")
    admin_note: str = Field(default="", max_length=4000)
    rank_delta: float = Field(default=0.0)
    delist_reason: str = Field(default="", max_length=1000)


_browse_routes = importlib.import_module("modstore_server.market_catalog_browse_routes")
api_market_facets = _browse_routes.api_market_facets
api_market_catalog = _browse_routes.api_market_catalog
api_office_employee_pack_bundle = _browse_routes.api_office_employee_pack_bundle
api_host_foundation_employee_pack_download = (
    _browse_routes.api_host_foundation_employee_pack_download
)
api_workflow_employee_pack_bundle = _browse_routes.api_workflow_employee_pack_bundle
api_market_catalog_detail = _browse_routes.api_market_catalog_detail
_enrich_catalog_creator_profile = _browse_routes._enrich_catalog_creator_profile


@router.get("/market/catalog/{item_id}/quality")
async def api_market_catalog_quality(
    item_id: int,
    refresh: bool = Query(False, description="忽略缓存并重新检测"),
    llm: bool = Query(False, description="调用六维质检员工（hex-quality-assessor）做 LLM 深度评估"),
    user: Optional[User] = Depends(_optional_current_user),
):
    """员工包六维质量报告（懒加载；优先 graph_snapshot / 进程缓存；llm=1 走真实 LLM）。"""
    from modstore_server.catalog_quality import quality_report_for_catalog_item
    from modstore_server.services.llm import resolve_platform_bench_llm

    if llm:
        prov, mdl = resolve_platform_bench_llm()
        if not prov or not mdl:
            raise HTTPException(
                503,
                "LLM 六维评估需要平台 LLM 密钥，当前未配置。"
                "请设置 MODSTORE_EMPLOYEE_BENCH_PROVIDER + MODSTORE_EMPLOYEE_BENCH_MODEL。",
            )

    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        _reject_internal_duty_catalog_item(item)
        if not item.is_public:
            is_author = user and item.author_id and int(item.author_id) == int(user.id)
            is_admin = bool(user and getattr(user, "is_admin", False))
            if not is_author and not is_admin:
                raise HTTPException(404, "商品不存在")
        if item.artifact != "employee_pack":
            raise HTTPException(400, "仅 AI 员工包支持质量评估")
        write_back = bool(
            refresh
            and user
            and (
                getattr(user, "is_admin", False)
                or (item.author_id and int(item.author_id) == int(user.id))
            )
        )
        report = await quality_report_for_catalog_item(
            item,
            force_refresh=bool(refresh or llm),
            write_snapshot=write_back and not llm,
            session=session if write_back and not llm else None,
            use_llm=bool(llm),
            user_id=int(user.id) if user else 0,
        )
        return report


@router.post("/market/catalog/{item_id}/review")
def api_submit_review(
    item_id: int,
    body: ReviewSubmitDTO,
    user: User = Depends(_get_current_user),
):
    from modstore_server.models import Entitlement

    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        _reject_internal_duty_catalog_item(item)
        ent = (
            session.query(Entitlement)
            .filter(
                Entitlement.user_id == user.id,
                Entitlement.catalog_id == item_id,
                Entitlement.is_active,
            )
            .first()
        )
        purchase = (
            session.query(Purchase)
            .filter(Purchase.user_id == user.id, Purchase.catalog_id == item_id)
            .first()
        )
        if not ent and not purchase:
            raise HTTPException(403, "购买后方可评价")
        exists = (
            session.query(Review)
            .filter(Review.user_id == user.id, Review.catalog_id == item_id)
            .first()
        )
        if exists:
            raise HTTPException(400, "已评价过")
        session.add(
            Review(
                user_id=user.id,
                catalog_id=item_id,
                rating=int(body.rating),
                content=(body.content or "").strip(),
            )
        )
        session.commit()
    return {"ok": True}


@router.get("/market/catalog/{item_id}/reviews")
def api_catalog_reviews(item_id: int):
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(Review, User)
            .join(User, Review.user_id == User.id)
            .filter(Review.catalog_id == item_id)
            .order_by(Review.created_at.desc())
            .limit(50)
            .all()
        )
        revs = [
            {
                "id": r.id,
                "user_name": u.username,
                "rating": r.rating,
                "content": r.content or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r, u in rows
        ]
        avg = sum(x[0].rating for x in rows) / len(rows) if rows else 0.0
        return {"reviews": revs, "average_rating": round(avg, 2), "total": len(revs)}


@router.post("/market/catalog/{item_id}/favorite")
def api_toggle_favorite(item_id: int, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        _reject_internal_duty_catalog_item(item)
        existing = (
            session.query(Favorite)
            .filter(Favorite.user_id == user.id, Favorite.catalog_id == item_id)
            .first()
        )
        if existing:
            session.delete(existing)
            session.commit()
            return {"ok": True, "favorited": False}
        session.add(Favorite(user_id=user.id, catalog_id=item_id))
        session.commit()
        return {"ok": True, "favorited": True}


@router.post("/market/catalog/{item_id}/complaints")
def api_submit_catalog_complaint(
    item_id: int,
    body: CatalogComplaintSubmitDTO,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        _reject_internal_duty_catalog_item(item)
        complaint_type = (body.complaint_type or "other").strip() or "other"
        row = CatalogComplaint(
            catalog_id=item.id,
            user_id=user.id,
            complaint_type=complaint_type,
            reason=(body.reason or "").strip(),
            evidence_json=json.dumps(body.evidence or {}, ensure_ascii=False),
            status="pending",
        )
        session.add(row)
        item.rank_score = max(0.0, float(getattr(item, "rank_score", 100.0) or 100.0) - 5.0)
        if (getattr(item, "compliance_status", "") or "approved") == "approved":
            item.compliance_status = "under_review"
        session.commit()
        session.refresh(row)
        _invalidate_market_catalog_caches()
        return {
            "ok": True,
            "id": row.id,
            "status": row.status,
            "message": "投诉/申诉已提交，客服助手会继续引导补充材料",
        }


@router.get("/admin/catalog/complaints")
def api_admin_list_catalog_complaints(
    status: str = Query("", max_length=24),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        query = (
            session.query(CatalogComplaint, CatalogItem, User)
            .join(CatalogItem, CatalogComplaint.catalog_id == CatalogItem.id)
            .join(User, CatalogComplaint.user_id == User.id)
        )
        if status:
            query = query.filter(CatalogComplaint.status == status)
        total = query.count()
        rows = query.order_by(CatalogComplaint.created_at.desc()).offset(offset).limit(limit).all()
        return {
            "items": [
                {
                    "id": c.id,
                    "catalog_id": c.catalog_id,
                    "catalog_name": item.name,
                    "pkg_id": item.pkg_id,
                    "user_id": c.user_id,
                    "user_name": reporter.username,
                    "complaint_type": c.complaint_type,
                    "reason": c.reason,
                    "evidence": json.loads(c.evidence_json or "{}"),
                    "status": c.status,
                    "resolution": c.resolution,
                    "admin_note": c.admin_note,
                    "created_at": c.created_at.isoformat() if c.created_at else "",
                    "updated_at": c.updated_at.isoformat() if c.updated_at else "",
                }
                for c, item, reporter in rows
            ],
            "total": total,
        }


@router.post("/admin/catalog/complaints/{complaint_id}/review")
def api_admin_review_catalog_complaint(
    complaint_id: int,
    body: CatalogComplaintReviewDTO,
    user: User = Depends(_require_admin),
):
    action = (body.action or "").strip().lower()
    if action not in {"resolve", "reject", "downrank", "delist", "restore"}:
        raise HTTPException(400, "action 必须是 resolve/reject/downrank/delist/restore")
    sf = get_session_factory()
    with sf() as session:
        complaint = (
            session.query(CatalogComplaint).filter(CatalogComplaint.id == complaint_id).first()
        )
        if not complaint:
            raise HTTPException(404, "投诉/申诉不存在")
        item = session.query(CatalogItem).filter(CatalogItem.id == complaint.catalog_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")

        now = datetime.now(timezone.utc)
        complaint.admin_id = user.id
        complaint.admin_note = (body.admin_note or "").strip()
        complaint.resolution = action
        complaint.updated_at = now

        if action == "reject":
            complaint.status = "rejected"
            item.compliance_status = "approved"
        elif action == "restore":
            complaint.status = "resolved"
            item.is_public = True
            item.compliance_status = "approved"
            item.delist_reason = ""
            item.rank_score = max(float(getattr(item, "rank_score", 100.0) or 0), 80.0)
        elif action == "delist":
            complaint.status = "resolved"
            item.is_public = False
            item.compliance_status = "delisted"
            item.delist_reason = (body.delist_reason or body.admin_note or "投诉处理下架").strip()
            item.rank_score = 0.0
        elif action == "downrank":
            complaint.status = "resolved"
            item.compliance_status = "restricted"
            delta = body.rank_delta if body.rank_delta > 0 else 30.0
            item.rank_score = max(
                0.0, float(getattr(item, "rank_score", 100.0) or 100.0) - float(delta)
            )
        else:
            complaint.status = "resolved"
            if item.compliance_status == "under_review":
                item.compliance_status = "approved"
        session.commit()
        return {
            "ok": True,
            "id": complaint.id,
            "status": complaint.status,
            "resolution": complaint.resolution,
        }
