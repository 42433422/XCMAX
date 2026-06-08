"""工作流模板市场 API。

模板存储在 ``catalog_items`` 表（``artifact='workflow_template'``），复用现有
catalog 的购买、评价、收藏、已购列表能力；模板特有字段：

- ``template_category`` 业务场景（客服 / 营销 / 数据分析 / HR / 电商 / 工程 / 通用）
- ``template_difficulty`` 难度（beginner / intermediate / advanced）
- ``install_count`` 累计安装次数
- ``graph_snapshot`` 工作流图 JSON 快照（与 ``WorkflowVersion.graph_snapshot`` 同结构）

一键安装 = 把 ``graph_snapshot`` clone 成当前用户的新 ``Workflow``，
跳到 v2 编辑器即可继续配置。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    CatalogItem,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])

ARTIFACT_TEMPLATE = "workflow_template"

DIFFICULTY_LABELS = {
    "beginner": "新手",
    "intermediate": "进阶",
    "advanced": "专家",
}

DEFAULT_CATEGORIES = [
    "客服",
    "营销",
    "数据分析",
    "HR",
    "电商",
    "内容创作",
    "研发工程",
    "通用",
]


class SaveAsTemplateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=4000)
    template_category: str = Field("通用", max_length=32)
    template_difficulty: str = Field("intermediate", max_length=16)
    price: float = Field(0.0, ge=0)
    is_public: bool = False
    industry: str = Field("通用", max_length=64)


def _serialize_template_summary(row: CatalogItem, *, with_graph: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": row.id,
        "pkg_id": row.pkg_id,
        "name": row.name,
        "description": row.description or "",
        "version": row.version,
        "price": float(row.price or 0.0),
        "author_id": row.author_id,
        "industry": row.industry or "通用",
        "is_public": bool(row.is_public),
        "template_category": row.template_category or "通用",
        "template_difficulty": row.template_difficulty or "intermediate",
        "difficulty_label": DIFFICULTY_LABELS.get(
            row.template_difficulty or "", row.template_difficulty or ""
        ),
        "install_count": int(row.install_count or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if with_graph:
        try:
            graph = json.loads(row.graph_snapshot or "{}")
        except json.JSONDecodeError:
            graph = {}
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        payload["graph"] = {
            "name": graph.get("name") or row.name,
            "description": graph.get("description") or row.description or "",
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
    return payload


@router.get("", summary="模板市场列表（按类别/难度/关键字过滤）")
async def list_templates(
    q: str = Query("", max_length=128),
    category: str = Query("", max_length=32),
    difficulty: str = Query("", max_length=16),
    sort: str = Query("popular", max_length=16, description="popular | newest"),
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(CatalogItem).filter(
        CatalogItem.artifact == ARTIFACT_TEMPLATE,
        CatalogItem.is_public.is_(True),
    )
    if q.strip():
        kw = f"%{q.strip()}%"
        query = query.filter(or_(CatalogItem.name.ilike(kw), CatalogItem.description.ilike(kw)))
    if category.strip():
        query = query.filter(CatalogItem.template_category == category.strip())
    if difficulty.strip():
        query = query.filter(CatalogItem.template_difficulty == difficulty.strip())

    total = query.count()
    if sort == "newest":
        query = query.order_by(desc(CatalogItem.created_at))
    else:
        query = query.order_by(desc(CatalogItem.install_count), desc(CatalogItem.created_at))
    rows = query.limit(limit).offset(offset).all()
    return {
        "total": total,
        "items": [_serialize_template_summary(r) for r in rows],
    }


@router.get("/categories", summary="模板类别清单（含计数）")
async def list_template_categories(db: Session = Depends(get_db)):
    rows = (
        db.query(CatalogItem.template_category, func.count(CatalogItem.id))
        .filter(
            CatalogItem.artifact == ARTIFACT_TEMPLATE,
            CatalogItem.is_public.is_(True),
        )
        .group_by(CatalogItem.template_category)
        .all()
    )
    counts = {(r[0] or "通用"): int(r[1] or 0) for r in rows}
    items: List[Dict[str, Any]] = []
    for c in DEFAULT_CATEGORIES:
        items.append({"name": c, "count": counts.pop(c, 0)})
    for name, n in counts.items():
        items.append({"name": name, "count": int(n)})
    return {"categories": items, "difficulties": DIFFICULTY_LABELS}


@router.get("/{template_id}", summary="模板详情（含 graph_snapshot 预览）")
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
):
    row = (
        db.query(CatalogItem)
        .filter(
            CatalogItem.id == template_id,
            CatalogItem.artifact == ARTIFACT_TEMPLATE,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "模板不存在")
    if not row.is_public:
        raise HTTPException(404, "模板不存在")
    return _serialize_template_summary(row, with_graph=True)


@router.post("/{template_id}/install", summary="一键安装：把模板克隆为当前用户的工作流")
async def install_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    row = (
        db.query(CatalogItem)
        .filter(
            CatalogItem.id == template_id,
            CatalogItem.artifact == ARTIFACT_TEMPLATE,
        )
        .first()
    )
    if not row or not row.is_public:
        raise HTTPException(404, "模板不存在")

    try:
        snapshot = json.loads(row.graph_snapshot or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"模板 graph 损坏: {exc}") from exc

    if not snapshot.get("nodes"):
        raise HTTPException(400, "该模板暂无可安装的工作流图")

    workflow = Workflow(
        user_id=user.id,
        name=f"{row.name} (来自模板)",
        description=row.description or "",
        is_active=True,
    )
    db.add(workflow)
    db.flush()

    local_to_new: Dict[int, int] = {}
    for raw in snapshot.get("nodes") or []:
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_type=str(raw.get("node_type") or "start"),
            name=str(raw.get("name") or "节点"),
            config=json.dumps(raw.get("config") or {}, ensure_ascii=False),
            position_x=float(raw.get("position_x") or 0.0),
            position_y=float(raw.get("position_y") or 0.0),
        )
        db.add(node)
        db.flush()
        local_to_new[int(raw.get("local_id") or 0)] = int(node.id)

    for raw in snapshot.get("edges") or []:
        src = local_to_new.get(int(raw.get("source_local_id") or 0))
        tgt = local_to_new.get(int(raw.get("target_local_id") or 0))
        if not src or not tgt:
            continue
        db.add(
            WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=src,
                target_node_id=tgt,
                condition=str(raw.get("condition") or ""),
            )
        )

    row.install_count = int(row.install_count or 0) + 1
    db.commit()
    db.refresh(workflow)
    return {
        "ok": True,
        "workflow_id": int(workflow.id),
        "workflow_name": workflow.name,
        "template_id": int(row.id),
        "install_count": int(row.install_count or 0),
    }


def _build_template_pkg_id(user_id: int, name: str) -> str:
    base = name.strip().lower().replace(" ", "-").replace("/", "-").replace(".", "-")
    safe = "".join(ch for ch in base if ch.isascii() and (ch.isalnum() or ch in "-_"))
    if not safe:
        safe = "template"
    ts = int(datetime.now(timezone.utc).timestamp())
    return f"tmpl-u{user_id}-{safe[:48]}-{ts}"


def _build_graph_snapshot(db: Session, workflow: Workflow) -> Dict[str, Any]:
    nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == workflow.id)
        .order_by(WorkflowNode.id.asc())
        .all()
    )
    edges = (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == workflow.id)
        .order_by(WorkflowEdge.id.asc())
        .all()
    )
    return {
        "name": workflow.name,
        "description": workflow.description,
        "nodes": [
            {
                "local_id": n.id,
                "node_type": n.node_type,
                "name": n.name,
                "config": json.loads(n.config or "{}"),
                "position_x": n.position_x,
                "position_y": n.position_y,
            }
            for n in nodes
        ],
        "edges": [
            {
                "source_local_id": e.source_node_id,
                "target_local_id": e.target_node_id,
                "condition": e.condition or "",
            }
            for e in edges
        ],
    }


# 这条路由放在 templates 路由器里仅为聚合视图，但 prefix 是 /api/templates，
# 因此实际暴露为 POST /api/templates/from-workflow/{workflow_id}。
@router.post(
    "/from-workflow/{workflow_id}",
    summary="把当前工作流另存为模板（仅本人）",
)
async def save_workflow_as_template(
    workflow_id: int,
    body: SaveAsTemplateBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    snapshot = _build_graph_snapshot(db, workflow)
    if not snapshot["nodes"]:
        raise HTTPException(400, "工作流为空，无法发布为模板")

    pkg_id = _build_template_pkg_id(user.id, body.name)
    row = CatalogItem(
        pkg_id=pkg_id,
        version="1.0.0",
        name=body.name.strip(),
        description=(body.description or "").strip(),
        price=float(body.price or 0.0),
        author_id=user.id,
        artifact=ARTIFACT_TEMPLATE,
        industry=(body.industry or "通用").strip(),
        is_public=bool(body.is_public),
        template_category=(body.template_category or "通用").strip(),
        template_difficulty=(body.template_difficulty or "intermediate").strip(),
        graph_snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_template_summary(row, with_graph=True)
