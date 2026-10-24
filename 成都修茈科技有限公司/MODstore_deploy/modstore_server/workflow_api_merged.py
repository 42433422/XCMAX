"""Auto-merged part* modules (debt24)."""
from __future__ import annotations
import importlib
from modstore_server.operational_errors import RECOVERABLE_ERRORS

# --- from workflow_api_part01.py ---
"""Implementation extracted from the public facade module."""


import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


def _guess_employee_id_from_empty_workflow(workflow: _facade().Workflow) -> str:
    """Best-effort extraction for old empty employee workflows.

    New employee workflows are fixed at creation time.  This fallback only helps
    already-created rows whose canvas is empty.  It is deliberately conservative
    and returns "" if no clear employee id is present.
    """
    text = f"{workflow.name or ''}\n{workflow.description or ''}"
    import re

    for pat in (
        "employee_id[=:：]\\s*([a-z0-9._-]+)",
        "pack_id[=:：]\\s*([a-z0-9._-]+)",
    ):
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1).strip()
    m = re.search("\\b([a-z0-9][a-z0-9._-]{2,})\\b", text, flags=re.I)
    return m.group(1).strip() if m else ""


def _repair_empty_employee_workflow_graph(
    db: _facade().Session, workflow: _facade().Workflow
) -> bool:
    """Create start → employee → end for old empty employee workflow rows."""
    existing = (
        db.query(_facade().WorkflowNode)
        .filter(_facade().WorkflowNode.workflow_id == workflow.id)
        .count()
    )
    if existing:
        return False
    marker = f"{workflow.name or ''} {workflow.description or ''}"
    if "员工" not in marker and "employee" not in marker.lower():
        return False
    employee_id = _facade()._guess_employee_id_from_empty_workflow(workflow)
    if not employee_id:
        return False
    start = _facade().WorkflowNode(
        workflow_id=workflow.id,
        node_type="start",
        name="开始",
        config=_facade().json.dumps({}, ensure_ascii=False),
        position_x=80,
        position_y=140,
    )
    emp = _facade().WorkflowNode(
        workflow_id=workflow.id,
        node_type="employee",
        name=workflow.name or "执行员工",
        config=_facade().json.dumps(
            {
                "employee_id": employee_id,
                "task": (workflow.description or "根据工作流输入完成员工任务")[:400],
            },
            ensure_ascii=False,
        ),
        position_x=340,
        position_y=140,
    )
    end_node = _facade().WorkflowNode(
        workflow_id=workflow.id,
        node_type="end",
        name="结束",
        config=_facade().json.dumps({}, ensure_ascii=False),
        position_x=620,
        position_y=140,
    )
    db.add_all([start, emp, end_node])
    db.flush()
    db.add_all(
        [
            _facade().WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=start.id,
                target_node_id=emp.id,
                condition="",
            ),
            _facade().WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=emp.id,
                target_node_id=end_node.id,
                condition="",
            ),
        ]
    )
    db.commit()
    return True

# --- from workflow_api_part02_part01_part01.py ---
"""Implementation extracted from the public facade module."""


from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


class CreateWorkflowBody(_facade().BaseModel):
    name: str = _facade().Field(..., min_length=1, max_length=256)
    description: str = _facade().Field("", max_length=2000)


class WorkflowExecuteBody(_facade().BaseModel):
    input_data: _facade().Dict[str, _facade().Any] = _facade().Field(default_factory=dict)


class SandboxRunBody(_facade().BaseModel):
    """沙盒运行：默认 Mock 员工，全链路变量快照与边条件分支记录。"""

    input_data: _facade().Dict[str, _facade().Any] = _facade().Field(default_factory=dict)
    mock_employees: bool = True
    validate_only: bool = False


class UpdateWorkflowBody(_facade().BaseModel):
    name: _facade().Optional[str] = None
    description: _facade().Optional[str] = None
    is_active: _facade().Optional[bool] = None


class AddWorkflowNodeBody(_facade().BaseModel):
    node_type: str = _facade().Field(..., min_length=1, max_length=64)
    name: str = _facade().Field(..., min_length=1, max_length=256)
    config: _facade().Dict[str, _facade().Any] = _facade().Field(default_factory=dict)
    position_x: float = 0.0
    position_y: float = 0.0


class AddWorkflowEdgeBody(_facade().BaseModel):
    source_node_id: int
    target_node_id: int
    condition: str = ""


class PatchWorkflowNodeBody(_facade().BaseModel):
    name: _facade().Optional[str] = None
    config: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    position_x: _facade().Optional[float] = None
    position_y: _facade().Optional[float] = None


class WorkflowTriggerBody(_facade().BaseModel):
    trigger_type: str = _facade().Field(..., min_length=1, max_length=32)
    trigger_key: str = _facade().Field("", max_length=128)
    config: _facade().Dict[str, _facade().Any] = _facade().Field(default_factory=dict)
    is_active: bool = True


class PublishVersionBody(_facade().BaseModel):
    note: str = _facade().Field("", max_length=2000)


def _serialize_workflow_snapshot(
    db: _facade().Session, workflow: _facade().Workflow
) -> _facade().Dict[str, _facade().Any]:
    """把当前 workflow 的图与触发器序列化为版本 snapshot。"""
    nodes = (
        db.query(_facade().WorkflowNode)
        .filter(_facade().WorkflowNode.workflow_id == workflow.id)
        .order_by(_facade().WorkflowNode.id.asc())
        .all()
    )
    edges = (
        db.query(_facade().WorkflowEdge)
        .filter(_facade().WorkflowEdge.workflow_id == workflow.id)
        .order_by(_facade().WorkflowEdge.id.asc())
        .all()
    )
    triggers = (
        db.query(_facade().WorkflowTrigger)
        .filter(_facade().WorkflowTrigger.workflow_id == workflow.id)
        .order_by(_facade().WorkflowTrigger.id.asc())
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
                "config": _facade().json.loads(n.config or "{}"),
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
                "config": _facade().json.loads(t.config_json or "{}"),
                "is_active": bool(t.is_active),
            }
            for t in triggers
        ],
    }


def _restore_workflow_from_snapshot(
    db: _facade().Session,
    workflow: _facade().Workflow,
    snapshot: _facade().Dict[str, _facade().Any],
) -> None:
    """用 snapshot 替换当前 workflow 的 nodes/edges 与 name/description。

    刻意不动 ``WorkflowTrigger`` 表 —— 避免回滚时把用户对外暴露的
    webhook URL/cron 调度悄悄停掉。
    """
    db.query(_facade().WorkflowEdge).filter(
        _facade().WorkflowEdge.workflow_id == workflow.id
    ).delete()
    db.query(_facade().WorkflowNode).filter(
        _facade().WorkflowNode.workflow_id == workflow.id
    ).delete()
    db.flush()
    local_to_new: _facade().Dict[int, int] = {}
    for raw in snapshot.get("nodes") or []:
        node = _facade().WorkflowNode(
            workflow_id=workflow.id,
            node_type=str(raw.get("node_type") or "").strip() or "start",
            name=str(raw.get("name") or "节点"),
            config=_facade().json.dumps(raw.get("config") or {}),
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
        edge = _facade().WorkflowEdge(
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
    workflow.updated_at = _facade().datetime.now(_facade().timezone.utc)


def _parse_positive_int(v: _facade().Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _workflow_summary(
    db: _facade().Session, workflow: _facade().Workflow, user_id: int
) -> _facade().Dict[str, _facade().Any]:
    sandbox_status = _facade().sandbox_status_for_workflow(db, workflow, user_id=user_id)
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


def _employee_matches_manifest_entry(
    entry: _facade().Dict[str, _facade().Any], employee_id: str
) -> bool:
    if not isinstance(entry, dict):
        return False
    eid = str(entry.get("id") or "").strip()
    if eid and _facade()._employee_id_matches(eid, employee_id):
        return True
    label = str(entry.get("label") or "").strip()
    panel_title = str(entry.get("panel_title") or "").strip()
    return _facade()._employee_id_matches(label, employee_id) or _facade()._employee_id_matches(
        panel_title, employee_id
    )


@_facade().router.post("/", summary="创建工作流")
async def create_workflow(
    body: CreateWorkflowBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """创建新的工作流（JSON body：name, description）。"""
    workflow = _facade().Workflow(
        user_id=user.id,
        name=body.name.strip(),
        description=(body.description or "").strip(),
        is_active=True,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
    }


@_facade().router.get("/", summary="获取工作流列表")
async def list_workflows(
    is_active: _facade().Optional[bool] = None,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """获取用户的工作流列表"""
    query = db.query(_facade().Workflow).filter(_facade().Workflow.user_id == user.id)
    if is_active is not None:
        query = query.filter(_facade().Workflow.is_active == is_active)
    workflows = query.all()
    return [_facade()._workflow_summary(db, w, user.id) for w in workflows]


@_facade().router.get("/employee-eligible", summary="获取员工可绑定的工作流")
async def list_employee_eligible_workflows(
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflows = (
        db.query(_facade().Workflow)
        .filter(
            _facade().Workflow.user_id == user.id,
            _facade().Workflow.is_active.is_(True),
        )
        .order_by(_facade().Workflow.updated_at.desc(), _facade().Workflow.id.desc())
        .all()
    )
    rows = [_facade()._workflow_summary(db, w, user.id) for w in workflows]
    eligible = [r for r in rows if r.get("sandbox_passed_for_current_graph")]
    return {"workflows": eligible, "all_workflows": rows, "total": len(eligible)}


@_facade().router.get("/by-employee", summary="按员工查询关联工作流")
async def list_workflows_by_employee(
    employee_id: str = _facade().Query(..., min_length=1, max_length=256),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """
    关联规则：
    1) workflow 节点中 employee 节点 config.employee_id 精确匹配；
    2) 兜底读取用户可见 Mod 的 manifest.workflow_employees[*].workflow_id/workflowId。
    """
    eid = (employee_id or "").strip()
    if not eid:
        raise _facade().HTTPException(400, "employee_id 不能为空")
    workflows = db.query(_facade().Workflow).filter(_facade().Workflow.user_id == user.id).all()
    workflow_by_id = {int(w.id): w for w in workflows}
    result_by_id: _facade().Dict[int, _facade().Dict[str, _facade().Any]] = {}
    node_hit_ids: set[int] = set()
    manifest_hit_ids: set[int] = set()
    errors: _facade().List[str] = []
    emp_nodes = (
        db.query(_facade().WorkflowNode)
        .join(_facade().Workflow)
        .filter(
            _facade().Workflow.user_id == user.id,
            _facade().WorkflowNode.node_type == "employee",
        )
        .all()
    )
    for n in emp_nodes:
        try:
            cfg = _facade().json.loads(n.config or "{}")
        except _facade().json.JSONDecodeError:
            errors.append(f"workflow_node[{n.id}] config 不是合法 JSON")
            continue
        hit = _facade()._employee_id_matches(str((cfg or {}).get("employee_id") or "").strip(), eid)
        if not hit:
            continue
        wid = int(n.workflow_id)
        w = workflow_by_id.get(wid)
        if not w:
            continue
        node_hit_ids.add(wid)
        result_by_id[wid] = {
            "id": wid,
            "name": w.name or f"工作流 {wid}",
            "source": "node",
        }
    try:
        try:
            from modstore_server import app as app_module

            lib = app_module._lib()
        except RECOVERABLE_ERRORS:
            cfg = _facade().load_config()
            lib = _facade().resolved_library(cfg)
        allow_mod_ids: _facade().Optional[set[str]] = (
            None if user.is_admin else set(_facade().get_user_mod_ids(user.id))
        )
        for d in _facade().iter_mod_dirs(lib):
            mid = d.name
            if allow_mod_ids is not None and mid not in allow_mod_ids:
                continue
            data, err = _facade().read_manifest(d)
            if err or not isinstance(data, dict):
                errors.append(f"mod[{mid}] manifest 读取失败: {err or 'invalid'}")
                continue
            wf_rows = data.get("workflow_employees")
            if not isinstance(wf_rows, list):
                continue
            for row in wf_rows:
                if not _facade()._employee_matches_manifest_entry(row, eid):
                    continue
                wid = _facade()._parse_positive_int(row.get("workflow_id") or row.get("workflowId"))
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
    except RECOVERABLE_ERRORS as e:
        errors.append(f"manifest 扫描失败: {e}")
    rows = sorted(result_by_id.values(), key=lambda x: int(x.get("id") or 0))
    return {
        "workflows": rows,
        "node_hits": len(node_hit_ids),
        "manifest_hits": len(manifest_hit_ids),
        "errors": errors,
    }

# --- from workflow_api_part02_part01_part02.py ---
"""Implementation extracted from the public facade module."""

import importlib
from modstore_server.workflow_api_part02_part01_part01 import AddWorkflowEdgeBody
from modstore_server.workflow_api_part02_part01_part01 import AddWorkflowNodeBody
from modstore_server.workflow_api_part02_part01_part01 import PatchWorkflowNodeBody
from modstore_server.workflow_api_part02_part01_part01 import SandboxRunBody
from modstore_server.workflow_api_part02_part01_part01 import UpdateWorkflowBody


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


@_facade().router.get("/{workflow_id}", summary="获取工作流详情")
async def get_workflow(
    workflow_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """获取工作流的详细信息，包括节点和边"""
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    nodes = (
        db.query(_facade().WorkflowNode)
        .filter(_facade().WorkflowNode.workflow_id == workflow_id)
        .all()
    )
    if not nodes and _facade()._repair_empty_employee_workflow_graph(db, workflow):
        nodes = (
            db.query(_facade().WorkflowNode)
            .filter(_facade().WorkflowNode.workflow_id == workflow_id)
            .all()
        )
    edges = (
        db.query(_facade().WorkflowEdge)
        .filter(_facade().WorkflowEdge.workflow_id == workflow_id)
        .all()
    )
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "graph_fingerprint": _facade().workflow_graph_fingerprint(db, workflow_id),
        "sandbox_status": _facade().sandbox_status_for_workflow(db, workflow, user_id=user.id),
        "nodes": [
            {
                "id": n.id,
                "node_type": n.node_type,
                "name": n.name,
                "config": _facade().json.loads(n.config),
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


@_facade().router.put("/{workflow_id}", summary="更新工作流")
async def update_workflow(
    workflow_id: int,
    body: UpdateWorkflowBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """更新工作流信息（JSON body：name, description, is_active）。"""
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.is_active is not None:
        workflow.is_active = body.is_active
    workflow.updated_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    db.refresh(workflow)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "updated_at": workflow.updated_at.isoformat(),
    }


@_facade().router.delete("/{workflow_id}", summary="删除工作流")
async def delete_workflow(
    workflow_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """删除工作流"""
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    db.query(_facade().WorkflowEdge).filter(
        _facade().WorkflowEdge.workflow_id == workflow_id
    ).delete()
    db.query(_facade().WorkflowNode).filter(
        _facade().WorkflowNode.workflow_id == workflow_id
    ).delete()
    db.query(_facade().WorkflowExecution).filter(
        _facade().WorkflowExecution.workflow_id == workflow_id
    ).delete()
    db.query(_facade().WorkflowSandboxRun).filter(
        _facade().WorkflowSandboxRun.workflow_id == workflow_id
    ).delete()
    db.delete(workflow)
    db.commit()
    return {"message": "工作流已删除"}


@_facade().router.post("/{workflow_id}/nodes", summary="添加工作流节点")
async def add_workflow_node(
    workflow_id: int,
    body: AddWorkflowNodeBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """添加工作流节点（JSON body）。"""
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    node = _facade().WorkflowNode(
        workflow_id=workflow_id,
        node_type=body.node_type.strip(),
        name=body.name.strip(),
        config=_facade().json.dumps(body.config or {}),
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
        "config": _facade().json.loads(node.config),
        "position_x": node.position_x,
        "position_y": node.position_y,
    }


@_facade().router.put("/nodes/{node_id}", summary="更新工作流节点")
async def update_workflow_node(
    node_id: int,
    body: PatchWorkflowNodeBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """更新工作流节点（JSON body）。"""
    node = (
        db.query(_facade().WorkflowNode)
        .join(_facade().Workflow)
        .filter(_facade().WorkflowNode.id == node_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not node:
        raise _facade().HTTPException(404, "节点不存在")
    if body.name is not None:
        node.name = body.name
    if body.config is not None:
        node.config = _facade().json.dumps(body.config)
    if body.position_x is not None:
        node.position_x = body.position_x
    if body.position_y is not None:
        node.position_y = body.position_y
    db.commit()
    db.refresh(node)
    return {
        "id": node.id,
        "name": node.name,
        "config": _facade().json.loads(node.config),
        "position_x": node.position_x,
        "position_y": node.position_y,
    }


@_facade().router.delete("/nodes/{node_id}", summary="删除工作流节点")
async def delete_workflow_node(
    node_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """删除工作流节点"""
    node = (
        db.query(_facade().WorkflowNode)
        .join(_facade().Workflow)
        .filter(_facade().WorkflowNode.id == node_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not node:
        raise _facade().HTTPException(404, "节点不存在")
    db.query(_facade().WorkflowEdge).filter(
        (_facade().WorkflowEdge.source_node_id == node_id)
        | (_facade().WorkflowEdge.target_node_id == node_id)
    ).delete()
    db.delete(node)
    db.commit()
    return {"message": "节点已删除"}


@_facade().router.post("/{workflow_id}/edges", summary="添加工作流边")
async def add_workflow_edge(
    workflow_id: int,
    body: AddWorkflowEdgeBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """添加工作流边（JSON body）。"""
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    source_node = (
        db.query(_facade().WorkflowNode)
        .filter(
            _facade().WorkflowNode.id == body.source_node_id,
            _facade().WorkflowNode.workflow_id == workflow_id,
        )
        .first()
    )
    target_node = (
        db.query(_facade().WorkflowNode)
        .filter(
            _facade().WorkflowNode.id == body.target_node_id,
            _facade().WorkflowNode.workflow_id == workflow_id,
        )
        .first()
    )
    if not source_node or not target_node:
        raise _facade().HTTPException(400, "源节点或目标节点不存在")
    edge = _facade().WorkflowEdge(
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


@_facade().router.delete("/edges/{edge_id}", summary="删除工作流边")
async def delete_workflow_edge(
    edge_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """删除工作流边"""
    edge = (
        db.query(_facade().WorkflowEdge)
        .join(_facade().Workflow)
        .filter(_facade().WorkflowEdge.id == edge_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not edge:
        raise _facade().HTTPException(404, "边不存在")
    db.delete(edge)
    db.commit()
    return {"message": "边已删除"}


@_facade().router.get("/{workflow_id}/validate", summary="校验工作流（静态 + 拓扑提示）")
async def validate_workflow_endpoint(
    workflow_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    from modstore_server.workflow_engine import run_workflow_sandbox

    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    report = run_workflow_sandbox(workflow_id, {}, validate_only=True, user_id=user.id)
    return report


@_facade().router.post(
    "/{workflow_id}/sandbox-run",
    summary="[已弃用] 节点图沙盒运行；新工作流请用 /api/script-workflows/{id}/sandbox-run",
    deprecated=True,
)
async def sandbox_run_workflow(
    workflow_id: int,
    body: SandboxRunBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """
    [已弃用] 节点图工作流沙箱测试。

    新生工作流请走"脚本即工作流"路径：``POST /api/script-workflows/sessions``
    启动 agent loop，自动验收通过后再 ``POST .../sandbox-run`` 用真实数据手动跑。

    此端点仍支持已存在节点图工作流的临时调试，但不再演进。
    """
    from modstore_server.workflow_engine import run_workflow_sandbox

    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    report = run_workflow_sandbox(
        workflow_id,
        body.input_data,
        mock_employees=body.mock_employees,
        validate_only=body.validate_only,
        user_id=user.id,
    )
    if not body.validate_only:
        row = _facade().record_workflow_sandbox_run(
            db,
            workflow_id=workflow_id,
            user_id=user.id,
            report=report,
            validate_only=body.validate_only,
            mock_employees=body.mock_employees,
        )
        status = _facade().sandbox_status_for_workflow(db, workflow, user_id=user.id)
        report = {
            **report,
            "sandbox_run_id": int(row.id),
            "graph_fingerprint": row.graph_fingerprint,
            "sandbox_status": status,
            "sandbox_passed_for_current_graph": status["sandbox_passed_for_current_graph"],
        }
    if not report.get("ok") and (not body.validate_only):
        raise _facade().HTTPException(
            400,
            detail={
                "errors": report.get("errors"),
                "warnings": report.get("warnings"),
                "mode": "real" if not body.mock_employees else "mock",
                "sandbox_status": report.get("sandbox_status"),
            },
        )
    return report

# --- from workflow_api_part03_part01_part01.py ---
"""Implementation extracted from the public facade module."""


from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib
from modstore_server.workflow_api_part02_part01_part01 import PublishVersionBody
from modstore_server.workflow_api_part02_part01_part01 import WorkflowExecuteBody
from modstore_server.workflow_api_part02_part01_part01 import WorkflowTriggerBody


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


@_facade().router.post("/{workflow_id}/execute", summary="执行工作流")
async def execute_workflow(
    workflow_id: int,
    body: WorkflowExecuteBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """生产执行：结果写入 workflow_executions（引擎内不落重复执行行）。"""
    from modstore_server.workflow_engine import execute_workflow as engine_execute

    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    if not workflow.is_active:
        raise _facade().HTTPException(400, "工作流未激活")
    execution = _facade().WorkflowExecution(
        workflow_id=workflow_id,
        user_id=user.id,
        status="running",
        input_data=_facade().json.dumps(body.input_data or {}),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    sf = _facade().get_session_factory()
    with sf() as qdb:
        _facade().require_llm_credit(qdb, user.id, 1)
    failure_message: _facade().Optional[str] = None
    try:
        output_data = engine_execute(workflow_id, body.input_data or {}, user_id=user.id)
        execution.status = "completed"
        execution.output_data = _facade().json.dumps(output_data)
        execution.completed_at = _facade().datetime.now(_facade().timezone.utc)
        try:
            with sf() as qdb2:
                _facade().consume_llm_credit(qdb2, user.id, 1)
        except RECOVERABLE_ERRORS:
            pass
    except RECOVERABLE_ERRORS as e:
        failure_message = str(e)
        execution.status = "failed"
        execution.error_message = failure_message
        execution.completed_at = _facade().datetime.now(_facade().timezone.utc)
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
    except RECOVERABLE_ERRORS:
        pass
    if failure_message is not None:
        raise _facade().HTTPException(500, failure_message)
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": _facade().json.loads(execution.input_data),
        "output_data": _facade().json.loads(execution.output_data or "{}"),
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


@_facade().router.get("/{workflow_id}/executions", summary="获取工作流执行记录")
async def get_workflow_executions(
    workflow_id: int,
    limit: int = _facade().Query(50, ge=1, le=100),
    offset: int = _facade().Query(0, ge=0),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """获取工作流的执行记录"""
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    executions = (
        db.query(_facade().WorkflowExecution)
        .filter(_facade().WorkflowExecution.workflow_id == workflow_id)
        .order_by(_facade().WorkflowExecution.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [
        {
            "id": e.id,
            "status": e.status,
            "input_data": _facade().json.loads(e.input_data or "{}"),
            "output_data": _facade().json.loads(e.output_data or "{}"),
            "error_message": e.error_message,
            "started_at": e.started_at.isoformat(),
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
        }
        for e in executions
    ]


@_facade().router.get("/{workflow_id}/triggers", summary="获取工作流触发器")
async def list_workflow_triggers(
    workflow_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    rows = (
        db.query(_facade().WorkflowTrigger)
        .filter(_facade().WorkflowTrigger.workflow_id == workflow_id)
        .all()
    )
    return [
        {
            "id": r.id,
            "trigger_type": r.trigger_type,
            "trigger_key": r.trigger_key,
            "config": _facade().json.loads(r.config_json or "{}"),
            "is_active": r.is_active,
        }
        for r in rows
    ]


@_facade().router.post("/{workflow_id}/triggers", summary="新增工作流触发器")
async def create_workflow_trigger(
    workflow_id: int,
    body: WorkflowTriggerBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    row = _facade().WorkflowTrigger(
        workflow_id=workflow_id,
        user_id=user.id,
        trigger_type=body.trigger_type.strip().lower(),
        trigger_key=(body.trigger_key or "").strip(),
        config_json=_facade().json.dumps(body.config or {}),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if (row.trigger_type or "").strip().lower() == "cron":
        from modstore_server.workflow_scheduler import refresh_cron_trigger

        refresh_cron_trigger(row.id)
    return {"id": row.id, "ok": True}


@_facade().router.delete("/{workflow_id}/triggers/{trigger_id}", summary="删除或停用工作流触发器")
async def delete_workflow_trigger(
    workflow_id: int,
    trigger_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    row = (
        db.query(_facade().WorkflowTrigger)
        .filter(
            _facade().WorkflowTrigger.id == trigger_id,
            _facade().WorkflowTrigger.workflow_id == workflow_id,
        )
        .first()
    )
    if not row:
        raise _facade().HTTPException(404, "触发器不存在")
    row.is_active = False
    db.commit()
    from modstore_server.workflow_scheduler import unregister_cron_trigger

    unregister_cron_trigger(trigger_id)
    return {"ok": True}


@_facade().router.post(
    "/{workflow_id}/webhook-run",
    summary="Webhook 方式触发执行工作流（需已配置 webhook 触发器）",
)
async def webhook_run_workflow(
    workflow_id: int,
    body: _facade().Dict[str, _facade().Any],
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    trig = (
        db.query(_facade().WorkflowTrigger)
        .filter(
            _facade().WorkflowTrigger.workflow_id == workflow_id,
            _facade().WorkflowTrigger.trigger_type == "webhook",
            _facade().WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise _facade().HTTPException(400, "该工作流未配置激活的 webhook 触发器")
    try:
        return _facade().run_workflow_for_trigger(
            workflow_id=workflow_id, user_id=user.id, input_data=body or {}
        )
    except RECOVERABLE_ERRORS as e:
        raise _facade().HTTPException(500, str(e)) from e


@_facade().router.post("/{workflow_id}/versions/publish", summary="发布工作流版本（快照当前图）")
async def publish_workflow_version(
    workflow_id: int,
    body: PublishVersionBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    snapshot = _facade()._serialize_workflow_snapshot(db, workflow)
    if not snapshot["nodes"]:
        raise _facade().HTTPException(400, "当前图为空，无法发布版本")
    last = (
        db.query(_facade().WorkflowVersion)
        .filter(_facade().WorkflowVersion.workflow_id == workflow_id)
        .order_by(_facade().WorkflowVersion.version_no.desc())
        .first()
    )
    next_no = int(last.version_no) + 1 if last else 1
    db.query(_facade().WorkflowVersion).filter(
        _facade().WorkflowVersion.workflow_id == workflow_id,
        _facade().WorkflowVersion.is_current.is_(True),
    ).update({_facade().WorkflowVersion.is_current: False})
    row = _facade().WorkflowVersion(
        workflow_id=workflow_id,
        user_id=user.id,
        version_no=next_no,
        note=(body.note or "").strip(),
        graph_snapshot=_facade().json.dumps(snapshot, ensure_ascii=False),
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


@_facade().router.get("/{workflow_id}/versions", summary="工作流版本列表（按 version_no 倒序）")
async def list_workflow_versions(
    workflow_id: int,
    limit: int = _facade().Query(50, ge=1, le=100),
    offset: int = _facade().Query(0, ge=0),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    rows = (
        db.query(_facade().WorkflowVersion)
        .filter(_facade().WorkflowVersion.workflow_id == workflow_id)
        .order_by(_facade().WorkflowVersion.version_no.desc())
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


@_facade().router.get(
    "/{workflow_id}/versions/{version_id}",
    summary="工作流版本详情（含 graph_snapshot）",
)
async def get_workflow_version(
    workflow_id: int,
    version_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    row = (
        db.query(_facade().WorkflowVersion)
        .filter(
            _facade().WorkflowVersion.id == version_id,
            _facade().WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not row:
        raise _facade().HTTPException(404, "版本不存在")
    try:
        snapshot = _facade().json.loads(row.graph_snapshot or "{}")
    except _facade().json.JSONDecodeError:
        snapshot = {}
    return {
        "id": row.id,
        "version_no": row.version_no,
        "note": row.note or "",
        "is_current": bool(row.is_current),
        "created_at": row.created_at.isoformat(),
        "graph_snapshot": snapshot,
    }

# --- from workflow_api_part03_part01_part02.py ---
"""Implementation extracted from the public facade module."""


from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


@_facade().router.post(
    "/{workflow_id}/versions/{version_id}/rollback",
    summary="回滚到指定版本（重建节点/边，不动触发器）",
)
async def rollback_workflow_version(
    workflow_id: int,
    version_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    target = (
        db.query(_facade().WorkflowVersion)
        .filter(
            _facade().WorkflowVersion.id == version_id,
            _facade().WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not target:
        raise _facade().HTTPException(404, "版本不存在")
    try:
        snapshot = _facade().json.loads(target.graph_snapshot or "{}")
    except _facade().json.JSONDecodeError as exc:
        raise _facade().HTTPException(500, f"版本 snapshot 损坏: {exc}") from exc
    _facade()._restore_workflow_from_snapshot(db, workflow, snapshot)
    db.query(_facade().WorkflowVersion).filter(
        _facade().WorkflowVersion.workflow_id == workflow_id,
        _facade().WorkflowVersion.is_current.is_(True),
    ).update({_facade().WorkflowVersion.is_current: False})
    target.is_current = True
    db.commit()
    return {"ok": True, "version_no": target.version_no}


@_facade().router.get("/executions/{execution_id}", summary="获取执行详情")
async def get_execution_detail(
    execution_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """获取工作流执行的详细信息"""
    execution = (
        db.query(_facade().WorkflowExecution)
        .join(_facade().Workflow)
        .filter(
            _facade().WorkflowExecution.id == execution_id,
            _facade().Workflow.user_id == user.id,
        )
        .first()
    )
    if not execution:
        raise _facade().HTTPException(404, "执行记录不存在")
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": _facade().json.loads(execution.input_data or "{}"),
        "output_data": _facade().json.loads(execution.output_data or "{}"),
        "error_message": execution.error_message,
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


@_facade().workflow_hooks_router.post(
    "/webhook/{trigger_key}",
    summary="公开 Webhook 触发工作流（需在触发器 config 配置 secret）",
)
async def public_webhook_run_workflow(
    trigger_key: str,
    request: _facade().Request,
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """外部系统无需用户 JWT：匹配 ``WorkflowTrigger.trigger_key``，校验 ``X-Workflow-Secret`` 与触发器
    ``config_json.secret`` 一致后执行；请求 JSON 作为 ``input_data``。
    """
    key = (trigger_key or "").strip()
    trig = (
        db.query(_facade().WorkflowTrigger)
        .filter(
            _facade().WorkflowTrigger.trigger_key == key,
            _facade().WorkflowTrigger.trigger_type == "webhook",
            _facade().WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise _facade().HTTPException(404, "触发器不存在或未启用")
    cfg: _facade().Dict[str, _facade().Any] = {}
    try:
        raw_cfg = _facade().json.loads(trig.config_json or "{}")
        if isinstance(raw_cfg, dict):
            cfg = raw_cfg
    except _facade().json.JSONDecodeError:
        cfg = {}
    secret = str(cfg.get("secret") or "").strip()
    if secret:
        hdr = (request.headers.get("X-Workflow-Secret") or "").strip()
        if not _facade().hmac.compare_digest(hdr, secret):
            raise _facade().HTTPException(403, "Webhook secret mismatch")
    elif _facade().os.environ.get("MODSTORE_REQUIRE_WEBHOOK_SECRET", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        raise _facade().HTTPException(
            400,
            "请在触发器 config 中配置 secret，或关闭 MODSTORE_REQUIRE_WEBHOOK_SECRET",
        )
    try:
        body = await request.json()
    except RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        return _facade().run_workflow_for_trigger(
            workflow_id=int(trig.workflow_id),
            user_id=int(trig.user_id),
            input_data=body,
        )
    except RECOVERABLE_ERRORS as e:
        raise _facade().HTTPException(500, str(e)) from e
