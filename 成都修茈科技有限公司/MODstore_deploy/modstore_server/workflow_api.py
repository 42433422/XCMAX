"""工作流API模块，提供工作流的CRUD操作和执行监控功能。"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modman.manifest_util import read_manifest
from modman.repo_config import load_config, resolved_library
from modman.store import iter_mod_dirs
from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowSandboxRun,
    WorkflowTrigger,
    WorkflowVersion,
    get_session_factory,
    get_user_mod_ids,
)
from modstore_server.quota_middleware import consume_llm_credit, require_llm_credit
from modstore_server.workflow_event_runner import run_workflow_for_trigger
from modstore_server.workflow_sandbox_state import (
    record_workflow_sandbox_run,
    sandbox_status_for_workflow,
    workflow_graph_fingerprint,
)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


def _guess_employee_id_from_empty_workflow(workflow: Workflow) -> str:
    """Best-effort extraction for old empty employee workflows.

    New employee workflows are fixed at creation time.  This fallback only helps
    already-created rows whose canvas is empty.  It is deliberately conservative
    and returns "" if no clear employee id is present.
    """
    text = f"{workflow.name or ''}\n{workflow.description or ''}"
    import re

    # Prefer explicit employee_id / pack_id markers when present in generated
    # descriptions or debugging notes.
    for pat in (r"employee_id[=:：]\s*([a-z0-9._-]+)", r"pack_id[=:：]\s*([a-z0-9._-]+)"):
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1).strip()
    # Fall back to a slug-like token in names such as "seo-file-maintainer 工作流".
    m = re.search(r"\b([a-z0-9][a-z0-9._-]{2,})\b", text, flags=re.I)
    return m.group(1).strip() if m else ""


def _repair_empty_employee_workflow_graph(db: Session, workflow: Workflow) -> bool:
    """Create start → employee → end for old empty employee workflow rows."""
    existing = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).count()
    if existing:
        return False
    marker = f"{workflow.name or ''} {workflow.description or ''}"
    if "员工" not in marker and "employee" not in marker.lower():
        return False
    employee_id = _guess_employee_id_from_empty_workflow(workflow)
    if not employee_id:
        return False
    start = WorkflowNode(
        workflow_id=workflow.id,
        node_type="start",
        name="开始",
        config=json.dumps({}, ensure_ascii=False),
        position_x=80,
        position_y=140,
    )
    emp = WorkflowNode(
        workflow_id=workflow.id,
        node_type="employee",
        name=workflow.name or "执行员工",
        config=json.dumps(
            {
                "employee_id": employee_id,
                "task": (workflow.description or "根据工作流输入完成员工任务")[:400],
            },
            ensure_ascii=False,
        ),
        position_x=340,
        position_y=140,
    )
    end_node = WorkflowNode(
        workflow_id=workflow.id,
        node_type="end",
        name="结束",
        config=json.dumps({}, ensure_ascii=False),
        position_x=620,
        position_y=140,
    )
    db.add_all([start, emp, end_node])
    db.flush()
    db.add_all(
        [
            WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=start.id,
                target_node_id=emp.id,
                condition="",
            ),
            WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=emp.id,
                target_node_id=end_node.id,
                condition="",
            ),
        ]
    )
    db.commit()
    return True


workflow_hooks_router = APIRouter(prefix="/api/workflow-hooks", tags=["workflow-hooks"])


class CreateWorkflowBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=2000)


class WorkflowExecuteBody(BaseModel):
    input_data: Dict[str, Any] = Field(default_factory=dict)


class SandboxRunBody(BaseModel):
    """沙盒运行：默认 Mock 员工，全链路变量快照与边条件分支记录。"""

    input_data: Dict[str, Any] = Field(default_factory=dict)
    mock_employees: bool = True
    validate_only: bool = False


class UpdateWorkflowBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AddWorkflowNodeBody(BaseModel):
    node_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    config: Dict[str, Any] = Field(default_factory=dict)
    position_x: float = 0.0
    position_y: float = 0.0


class AddWorkflowEdgeBody(BaseModel):
    source_node_id: int
    target_node_id: int
    condition: str = ""


class PatchWorkflowNodeBody(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None


class WorkflowTriggerBody(BaseModel):
    trigger_type: str = Field(..., min_length=1, max_length=32)
    trigger_key: str = Field("", max_length=128)
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class PublishVersionBody(BaseModel):
    note: str = Field("", max_length=2000)


def _serialize_workflow_snapshot(db: Session, workflow: Workflow) -> Dict[str, Any]:
    """把当前 workflow 的图与触发器序列化为版本 snapshot。"""
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
    triggers = (
        db.query(WorkflowTrigger)
        .filter(WorkflowTrigger.workflow_id == workflow.id)
        .order_by(WorkflowTrigger.id.asc())
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
        "triggers": [
            {
                "trigger_type": t.trigger_type,
                "trigger_key": t.trigger_key or "",
                "config": json.loads(t.config_json or "{}"),
                "is_active": bool(t.is_active),
            }
            for t in triggers
        ],
    }


def _restore_workflow_from_snapshot(
    db: Session, workflow: Workflow, snapshot: Dict[str, Any]
) -> None:
    """用 snapshot 替换当前 workflow 的 nodes/edges 与 name/description。

    刻意不动 ``WorkflowTrigger`` 表 —— 避免回滚时把用户对外暴露的
    webhook URL/cron 调度悄悄停掉。
    """
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).delete()
    db.flush()

    local_to_new: Dict[int, int] = {}
    for raw in snapshot.get("nodes") or []:
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_type=str(raw.get("node_type") or "").strip() or "start",
            name=str(raw.get("name") or "节点"),
            config=json.dumps(raw.get("config") or {}),
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
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=src,
            target_node_id=tgt,
            condition=str(raw.get("condition") or ""),
        )
        db.add(edge)

    name = snapshot.get("name")
    if isinstance(name, str) and name.strip():
        workflow.name = name
    desc = snapshot.get("description")
    if isinstance(desc, str):
        workflow.description = desc
    workflow.updated_at = datetime.now(timezone.utc)


def _parse_positive_int(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _workflow_summary(db: Session, workflow: Workflow, user_id: int) -> Dict[str, Any]:
    sandbox_status = sandbox_status_for_workflow(db, workflow, user_id=user_id)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "graph_fingerprint": sandbox_status["graph_fingerprint"],
        "sandbox_status": sandbox_status,
        "sandbox_passed_for_current_graph": sandbox_status["sandbox_passed_for_current_graph"],
    }


def _employee_id_matches(candidate_id: str, target_employee_id: str) -> bool:
    """
    兼容 employee_id 命名差异：
    - 完全相等
    - 带 mod 前缀（如 sz-qsm-pro-wechat_phone）与裸 id（wechat_phone）互相匹配
    """
    c = str(candidate_id or "").strip()
    t = str(target_employee_id or "").strip()
    if not c or not t:
        return False
    if c == t:
        return True
    return c.endswith(f"-{t}") or c.endswith(f"_{t}") or t.endswith(f"-{c}") or t.endswith(f"_{c}")


def _employee_matches_manifest_entry(entry: Dict[str, Any], employee_id: str) -> bool:
    if not isinstance(entry, dict):
        return False
    eid = str(entry.get("id") or "").strip()
    if eid and _employee_id_matches(eid, employee_id):
        return True
    # 历史声明中也可能将 id 写在 label/panel_title，做兼容匹配。
    label = str(entry.get("label") or "").strip()
    panel_title = str(entry.get("panel_title") or "").strip()
    return _employee_id_matches(label, employee_id) or _employee_id_matches(
        panel_title, employee_id
    )


@router.post("/", summary="创建工作流")
async def create_workflow(
    body: CreateWorkflowBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """创建新的工作流（JSON body：name, description）。"""
    workflow = Workflow(
        user_id=user.id,
        name=body.name.strip(),
        description=(body.description or "").strip(),
        is_active=True,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return {"id": workflow.id, "name": workflow.name, "description": workflow.description}


@router.get("/", summary="获取工作流列表")
async def list_workflows(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """获取用户的工作流列表"""
    query = db.query(Workflow).filter(Workflow.user_id == user.id)
    if is_active is not None:
        query = query.filter(Workflow.is_active == is_active)
    workflows = query.all()
    return [_workflow_summary(db, w, user.id) for w in workflows]


@router.get("/employee-eligible", summary="获取员工可绑定的工作流")
async def list_employee_eligible_workflows(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user.id, Workflow.is_active == True)  # noqa: E712
        .order_by(Workflow.updated_at.desc(), Workflow.id.desc())
        .all()
    )
    rows = [_workflow_summary(db, w, user.id) for w in workflows]
    eligible = [r for r in rows if r.get("sandbox_passed_for_current_graph")]
    return {"workflows": eligible, "all_workflows": rows, "total": len(eligible)}


@router.get("/by-employee", summary="按员工查询关联工作流")
async def list_workflows_by_employee(
    employee_id: str = Query(..., min_length=1, max_length=256),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """
    关联规则：
    1) workflow 节点中 employee 节点 config.employee_id 精确匹配；
    2) 兜底读取用户可见 Mod 的 manifest.workflow_employees[*].workflow_id/workflowId。
    """
    eid = (employee_id or "").strip()
    if not eid:
        raise HTTPException(400, "employee_id 不能为空")

    workflows = db.query(Workflow).filter(Workflow.user_id == user.id).all()
    workflow_by_id = {int(w.id): w for w in workflows}
    result_by_id: Dict[int, Dict[str, Any]] = {}
    node_hit_ids: set[int] = set()
    manifest_hit_ids: set[int] = set()
    errors: List[str] = []

    emp_nodes = (
        db.query(WorkflowNode)
        .join(Workflow)
        .filter(
            Workflow.user_id == user.id,
            WorkflowNode.node_type == "employee",
        )
        .all()
    )
    for n in emp_nodes:
        try:
            cfg = json.loads(n.config or "{}")
        except json.JSONDecodeError:
            errors.append(f"workflow_node[{n.id}] config 不是合法 JSON")
            continue
        hit = _employee_id_matches(str((cfg or {}).get("employee_id") or "").strip(), eid)
        if not hit:
            continue
        wid = int(n.workflow_id)
        w = workflow_by_id.get(wid)
        if not w:
            continue
        node_hit_ids.add(wid)
        result_by_id[wid] = {"id": wid, "name": w.name or f"工作流 {wid}", "source": "node"}

    try:
        try:
            from modstore_server import app as app_module  # 避免与 app 的库路径解析分叉

            lib = app_module._lib()
        except Exception:
            cfg = load_config()
            lib = resolved_library(cfg)
        allow_mod_ids: Optional[set[str]] = (
            None if user.is_admin else set(get_user_mod_ids(user.id))
        )
        for d in iter_mod_dirs(lib):
            mid = d.name
            if allow_mod_ids is not None and mid not in allow_mod_ids:
                continue
            data, err = read_manifest(d)
            if err or not isinstance(data, dict):
                errors.append(f"mod[{mid}] manifest 读取失败: {err or 'invalid'}")
                continue
            wf_rows = data.get("workflow_employees")
            if not isinstance(wf_rows, list):
                continue
            for row in wf_rows:
                if not _employee_matches_manifest_entry(row, eid):
                    continue
                wid = _parse_positive_int(row.get("workflow_id") or row.get("workflowId"))
                if wid <= 0 or wid in node_hit_ids or wid in manifest_hit_ids:
                    continue
                w = workflow_by_id.get(wid)
                if not w:
                    continue
                manifest_hit_ids.add(wid)
                result_by_id[wid] = {
                    "id": wid,
                    "name": w.name or f"工作流 {wid}",
                    "source": "manifest",
                }
    except Exception as e:
        errors.append(f"manifest 扫描失败: {e}")

    rows = sorted(result_by_id.values(), key=lambda x: int(x.get("id") or 0))
    return {
        "workflows": rows,
        "node_hits": len(node_hit_ids),
        "manifest_hits": len(manifest_hit_ids),
        "errors": errors,
    }


@router.get("/{workflow_id}", summary="获取工作流详情")
async def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """获取工作流的详细信息，包括节点和边"""
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
    if not nodes and _repair_empty_employee_workflow_graph(db, workflow):
        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()

    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()

    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "graph_fingerprint": workflow_graph_fingerprint(db, workflow_id),
        "sandbox_status": sandbox_status_for_workflow(db, workflow, user_id=user.id),
        "nodes": [
            {
                "id": n.id,
                "node_type": n.node_type,
                "name": n.name,
                "config": json.loads(n.config),
                "position_x": n.position_x,
                "position_y": n.position_y,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source_node_id": e.source_node_id,
                "target_node_id": e.target_node_id,
                "condition": e.condition,
            }
            for e in edges
        ],
    }


@router.put("/{workflow_id}", summary="更新工作流")
async def update_workflow(
    workflow_id: int,
    body: UpdateWorkflowBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """更新工作流信息（JSON body：name, description, is_active）。"""
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.is_active is not None:
        workflow.is_active = body.is_active
    workflow.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(workflow)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "updated_at": workflow.updated_at.isoformat(),
    }


@router.delete("/{workflow_id}", summary="删除工作流")
async def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """删除工作流"""
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    # 删除相关的节点和边
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).delete()
    # 删除工作流执行记录
    db.query(WorkflowExecution).filter(WorkflowExecution.workflow_id == workflow_id).delete()
    db.query(WorkflowSandboxRun).filter(WorkflowSandboxRun.workflow_id == workflow_id).delete()
    # 删除工作流
    db.delete(workflow)
    db.commit()
    return {"message": "工作流已删除"}


@router.post("/{workflow_id}/nodes", summary="添加工作流节点")
async def add_workflow_node(
    workflow_id: int,
    body: AddWorkflowNodeBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """添加工作流节点（JSON body）。"""
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    node = WorkflowNode(
        workflow_id=workflow_id,
        node_type=body.node_type.strip(),
        name=body.name.strip(),
        config=json.dumps(body.config or {}),
        position_x=body.position_x,
        position_y=body.position_y,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return {
        "id": node.id,
        "node_type": node.node_type,
        "name": node.name,
        "config": json.loads(node.config),
        "position_x": node.position_x,
        "position_y": node.position_y,
    }


@router.put("/nodes/{node_id}", summary="更新工作流节点")
async def update_workflow_node(
    node_id: int,
    body: PatchWorkflowNodeBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """更新工作流节点（JSON body）。"""
    node = (
        db.query(WorkflowNode)
        .join(Workflow)
        .filter(
            WorkflowNode.id == node_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not node:
        raise HTTPException(404, "节点不存在")

    if body.name is not None:
        node.name = body.name
    if body.config is not None:
        node.config = json.dumps(body.config)
    if body.position_x is not None:
        node.position_x = body.position_x
    if body.position_y is not None:
        node.position_y = body.position_y

    db.commit()
    db.refresh(node)
    return {
        "id": node.id,
        "name": node.name,
        "config": json.loads(node.config),
        "position_x": node.position_x,
        "position_y": node.position_y,
    }


@router.delete("/nodes/{node_id}", summary="删除工作流节点")
async def delete_workflow_node(
    node_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """删除工作流节点"""
    node = (
        db.query(WorkflowNode)
        .join(Workflow)
        .filter(
            WorkflowNode.id == node_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not node:
        raise HTTPException(404, "节点不存在")

    # 删除相关的边
    db.query(WorkflowEdge).filter(
        (WorkflowEdge.source_node_id == node_id) | (WorkflowEdge.target_node_id == node_id)
    ).delete()
    # 删除节点
    db.delete(node)
    db.commit()
    return {"message": "节点已删除"}


@router.post("/{workflow_id}/edges", summary="添加工作流边")
async def add_workflow_edge(
    workflow_id: int,
    body: AddWorkflowEdgeBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """添加工作流边（JSON body）。"""
    # 验证工作流所有权
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    # 验证源节点和目标节点属于该工作流
    source_node = (
        db.query(WorkflowNode)
        .filter(
            WorkflowNode.id == body.source_node_id,
            WorkflowNode.workflow_id == workflow_id,
        )
        .first()
    )
    target_node = (
        db.query(WorkflowNode)
        .filter(
            WorkflowNode.id == body.target_node_id,
            WorkflowNode.workflow_id == workflow_id,
        )
        .first()
    )
    if not source_node or not target_node:
        raise HTTPException(400, "源节点或目标节点不存在")

    edge = WorkflowEdge(
        workflow_id=workflow_id,
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
        condition=body.condition or "",
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "condition": edge.condition,
    }


@router.delete("/edges/{edge_id}", summary="删除工作流边")
async def delete_workflow_edge(
    edge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """删除工作流边"""
    edge = (
        db.query(WorkflowEdge)
        .join(Workflow)
        .filter(
            WorkflowEdge.id == edge_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not edge:
        raise HTTPException(404, "边不存在")

    db.delete(edge)
    db.commit()
    return {"message": "边已删除"}


@router.get("/{workflow_id}/validate", summary="校验工作流（静态 + 拓扑提示）")
async def validate_workflow_endpoint(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    from modstore_server.workflow_engine import run_workflow_sandbox

    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    report = run_workflow_sandbox(workflow_id, {}, validate_only=True, user_id=user.id)
    return report


@router.post(
    "/{workflow_id}/sandbox-run",
    summary="[已弃用] 节点图沙盒运行；新工作流请用 /api/script-workflows/{id}/sandbox-run",
    deprecated=True,
)
async def sandbox_run_workflow(
    workflow_id: int,
    body: SandboxRunBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """
    [已弃用] 节点图工作流沙箱测试。

    新生工作流请走"脚本即工作流"路径：``POST /api/script-workflows/sessions``
    启动 agent loop，自动验收通过后再 ``POST .../sandbox-run`` 用真实数据手动跑。

    此端点仍支持已存在节点图工作流的临时调试，但不再演进。
    """
    from modstore_server.workflow_engine import run_workflow_sandbox

    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    report = run_workflow_sandbox(
        workflow_id,
        body.input_data,
        mock_employees=body.mock_employees,
        validate_only=body.validate_only,
        user_id=user.id,
    )
    if not body.validate_only:
        row = record_workflow_sandbox_run(
            db,
            workflow_id=workflow_id,
            user_id=user.id,
            report=report,
            validate_only=body.validate_only,
            mock_employees=body.mock_employees,
        )
        status = sandbox_status_for_workflow(db, workflow, user_id=user.id)
        report = {
            **report,
            "sandbox_run_id": int(row.id),
            "graph_fingerprint": row.graph_fingerprint,
            "sandbox_status": status,
            "sandbox_passed_for_current_graph": status["sandbox_passed_for_current_graph"],
        }
    if not report.get("ok") and not body.validate_only:
        raise HTTPException(
            400,
            detail={
                "errors": report.get("errors"),
                "warnings": report.get("warnings"),
                "mode": "real" if not body.mock_employees else "mock",
                "sandbox_status": report.get("sandbox_status"),
            },
        )
    return report


@router.post("/{workflow_id}/execute", summary="执行工作流")
async def execute_workflow(
    workflow_id: int,
    body: WorkflowExecuteBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """生产执行：结果写入 workflow_executions（引擎内不落重复执行行）。"""
    from modstore_server.workflow_engine import execute_workflow as engine_execute

    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    if not workflow.is_active:
        raise HTTPException(400, "工作流未激活")

    execution = WorkflowExecution(
        workflow_id=workflow_id,
        user_id=user.id,
        status="running",
        input_data=json.dumps(body.input_data or {}),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    sf = get_session_factory()
    with sf() as qdb:
        require_llm_credit(qdb, user.id, 1)
    failure_message: Optional[str] = None
    try:
        output_data = engine_execute(workflow_id, body.input_data or {}, user_id=user.id)
        execution.status = "completed"
        execution.output_data = json.dumps(output_data)
        execution.completed_at = datetime.now(timezone.utc)
        try:
            with sf() as qdb2:
                consume_llm_credit(qdb2, user.id, 1)
        except Exception:
            pass
    except Exception as e:
        failure_message = str(e)
        execution.status = "failed"
        execution.error_message = failure_message
        execution.completed_at = datetime.now(timezone.utc)
    db.commit()

    try:
        from modstore_server import webhook_dispatcher
        from modstore_server.eventing.contracts import (
            WORKFLOW_EXECUTION_COMPLETED,
            WORKFLOW_EXECUTION_FAILED,
        )

        event_name = WORKFLOW_EXECUTION_FAILED if failure_message else WORKFLOW_EXECUTION_COMPLETED
        webhook_dispatcher.publish_event(
            event_name,
            aggregate_id=str(execution.id),
            data={
                "workflow_id": int(workflow_id),
                "execution_id": int(execution.id),
                "user_id": int(user.id),
                "status": execution.status,
                "error": failure_message or "",
                "started_at": execution.started_at.isoformat(),
                "completed_at": (
                    execution.completed_at.isoformat() if execution.completed_at else ""
                ),
            },
            source="modstore-workflow-api",
        )
    except Exception:
        pass

    if failure_message is not None:
        raise HTTPException(500, failure_message)

    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": json.loads(execution.input_data),
        "output_data": json.loads(execution.output_data or "{}"),
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


@router.get("/{workflow_id}/executions", summary="获取工作流执行记录")
async def get_workflow_executions(
    workflow_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """获取工作流的执行记录"""
    # 验证工作流所有权
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    executions = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    return [
        {
            "id": e.id,
            "status": e.status,
            "input_data": json.loads(e.input_data or "{}"),
            "output_data": json.loads(e.output_data or "{}"),
            "error_message": e.error_message,
            "started_at": e.started_at.isoformat(),
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
        }
        for e in executions
    ]


@router.get("/{workflow_id}/triggers", summary="获取工作流触发器")
async def list_workflow_triggers(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    rows = db.query(WorkflowTrigger).filter(WorkflowTrigger.workflow_id == workflow_id).all()
    return [
        {
            "id": r.id,
            "trigger_type": r.trigger_type,
            "trigger_key": r.trigger_key,
            "config": json.loads(r.config_json or "{}"),
            "is_active": r.is_active,
        }
        for r in rows
    ]


@router.post("/{workflow_id}/triggers", summary="新增工作流触发器")
async def create_workflow_trigger(
    workflow_id: int,
    body: WorkflowTriggerBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    row = WorkflowTrigger(
        workflow_id=workflow_id,
        user_id=user.id,
        trigger_type=body.trigger_type.strip().lower(),
        trigger_key=(body.trigger_key or "").strip(),
        config_json=json.dumps(body.config or {}),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if (row.trigger_type or "").strip().lower() == "cron":
        from modstore_server.workflow_scheduler import refresh_cron_trigger

        refresh_cron_trigger(row.id)
    return {"id": row.id, "ok": True}


@router.delete("/{workflow_id}/triggers/{trigger_id}", summary="删除或停用工作流触发器")
async def delete_workflow_trigger(
    workflow_id: int,
    trigger_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    row = (
        db.query(WorkflowTrigger)
        .filter(
            WorkflowTrigger.id == trigger_id,
            WorkflowTrigger.workflow_id == workflow_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "触发器不存在")
    row.is_active = False
    db.commit()
    from modstore_server.workflow_scheduler import unregister_cron_trigger

    unregister_cron_trigger(trigger_id)
    return {"ok": True}


@router.post(
    "/{workflow_id}/webhook-run", summary="Webhook 方式触发执行工作流（需已配置 webhook 触发器）"
)
async def webhook_run_workflow(
    workflow_id: int,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    trig = (
        db.query(WorkflowTrigger)
        .filter(
            WorkflowTrigger.workflow_id == workflow_id,
            WorkflowTrigger.trigger_type == "webhook",
            WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise HTTPException(400, "该工作流未配置激活的 webhook 触发器")
    try:
        return run_workflow_for_trigger(
            workflow_id=workflow_id,
            user_id=user.id,
            input_data=body or {},
        )
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.post("/{workflow_id}/versions/publish", summary="发布工作流版本（快照当前图）")
async def publish_workflow_version(
    workflow_id: int,
    body: PublishVersionBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    snapshot = _serialize_workflow_snapshot(db, workflow)
    if not snapshot["nodes"]:
        raise HTTPException(400, "当前图为空，无法发布版本")

    last = (
        db.query(WorkflowVersion)
        .filter(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_no.desc())
        .first()
    )
    next_no = int(last.version_no) + 1 if last else 1

    db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.is_current.is_(True),
    ).update({WorkflowVersion.is_current: False})

    row = WorkflowVersion(
        workflow_id=workflow_id,
        user_id=user.id,
        version_no=next_no,
        note=(body.note or "").strip(),
        graph_snapshot=json.dumps(snapshot, ensure_ascii=False),
        is_current=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "version_no": row.version_no,
        "note": row.note,
        "is_current": row.is_current,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/{workflow_id}/versions", summary="工作流版本列表（按 version_no 倒序）")
async def list_workflow_versions(
    workflow_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    rows = (
        db.query(WorkflowVersion)
        .filter(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_no.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [
        {
            "id": r.id,
            "version_no": r.version_no,
            "note": r.note or "",
            "is_current": bool(r.is_current),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get(
    "/{workflow_id}/versions/{version_id}",
    summary="工作流版本详情（含 graph_snapshot）",
)
async def get_workflow_version(
    workflow_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    row = (
        db.query(WorkflowVersion)
        .filter(
            WorkflowVersion.id == version_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "版本不存在")
    try:
        snapshot = json.loads(row.graph_snapshot or "{}")
    except json.JSONDecodeError:
        snapshot = {}
    return {
        "id": row.id,
        "version_no": row.version_no,
        "note": row.note or "",
        "is_current": bool(row.is_current),
        "created_at": row.created_at.isoformat(),
        "graph_snapshot": snapshot,
    }


@router.post(
    "/{workflow_id}/versions/{version_id}/rollback",
    summary="回滚到指定版本（重建节点/边，不动触发器）",
)
async def rollback_workflow_version(
    workflow_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    target = (
        db.query(WorkflowVersion)
        .filter(
            WorkflowVersion.id == version_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not target:
        raise HTTPException(404, "版本不存在")

    try:
        snapshot = json.loads(target.graph_snapshot or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"版本 snapshot 损坏: {exc}") from exc

    _restore_workflow_from_snapshot(db, workflow, snapshot)

    db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.is_current.is_(True),
    ).update({WorkflowVersion.is_current: False})
    target.is_current = True

    db.commit()
    return {"ok": True, "version_no": target.version_no}


@router.get("/executions/{execution_id}", summary="获取执行详情")
async def get_execution_detail(
    execution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """获取工作流执行的详细信息"""
    execution = (
        db.query(WorkflowExecution)
        .join(Workflow)
        .filter(
            WorkflowExecution.id == execution_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(404, "执行记录不存在")

    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": json.loads(execution.input_data or "{}"),
        "output_data": json.loads(execution.output_data or "{}"),
        "error_message": execution.error_message,
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


@workflow_hooks_router.post(
    "/webhook/{trigger_key}", summary="公开 Webhook 触发工作流（需在触发器 config 配置 secret）"
)
async def public_webhook_run_workflow(
    trigger_key: str, request: Request, db: Session = Depends(get_db)
):
    """外部系统无需用户 JWT：匹配 ``WorkflowTrigger.trigger_key``，校验 ``X-Workflow-Secret`` 与触发器
    ``config_json.secret`` 一致后执行；请求 JSON 作为 ``input_data``。
    """
    key = (trigger_key or "").strip()
    trig = (
        db.query(WorkflowTrigger)
        .filter(
            WorkflowTrigger.trigger_key == key,
            WorkflowTrigger.trigger_type == "webhook",
            WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise HTTPException(404, "触发器不存在或未启用")

    cfg: Dict[str, Any] = {}
    try:
        raw_cfg = json.loads(trig.config_json or "{}")
        if isinstance(raw_cfg, dict):
            cfg = raw_cfg
    except json.JSONDecodeError:
        cfg = {}

    secret = str(cfg.get("secret") or "").strip()
    if secret:
        hdr = (request.headers.get("X-Workflow-Secret") or "").strip()
        if not hmac.compare_digest(hdr, secret):
            raise HTTPException(403, "Webhook secret mismatch")
    elif os.environ.get("MODSTORE_REQUIRE_WEBHOOK_SECRET", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        raise HTTPException(
            400, "请在触发器 config 中配置 secret，或关闭 MODSTORE_REQUIRE_WEBHOOK_SECRET"
        )

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    try:
        return run_workflow_for_trigger(
            workflow_id=int(trig.workflow_id),
            user_id=int(trig.user_id),
            input_data=body,
        )
    except Exception as e:
        raise HTTPException(500, str(e)) from e
