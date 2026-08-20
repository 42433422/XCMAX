# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
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
