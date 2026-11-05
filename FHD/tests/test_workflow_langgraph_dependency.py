"""回归：桌面/本地依赖清单（XCAGI/requirements.txt）必须包含 langgraph vendored 包。

复现背景（win32 桌面 2026-09-09）：按 XCAGI/requirements.txt 安装依赖后缺失 langgraph，
lifespan `_wire_workflow_runtime` → `app.infrastructure.workflow` 顶层导入
`langgraph.checkpoint.base.id`（checkpoint_bridge.py）时后端启动即崩
（ModuleNotFoundError: No module named 'langgraph'）。
"""

from __future__ import annotations


def test_langgraph_checkpoint_uuid6_importable() -> None:
    # 直接对应 app/infrastructure/workflow/checkpoint_bridge.py 的顶层导入
    from langgraph.checkpoint.base.id import uuid6

    assert callable(uuid6)


def test_workflow_package_imports_after_dependency_fix() -> None:
    # 启动崩溃的完整导入链：lifespan → app.infrastructure.workflow
    import app.infrastructure.workflow as workflow

    assert hasattr(workflow, "LanggraphCheckpointBridge")
