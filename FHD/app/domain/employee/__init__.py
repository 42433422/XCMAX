# -*- coding: utf-8 -*-
"""AI 员工领域值对象（纯数据 + 逻辑，不依赖基础设施）。

把 ``employee_config_v2`` 里声明、但运行时此前未消费的能力建模为领域对象：
- ``MemoryScope``：记忆命名空间与开关
- ``EmployeeCapability``：能力声明
- ``PerceptionSpec``：感知类型/模态
- ``CollaborationGraph``：``collaboration.depends_on`` 依赖图（拓扑 + 环检测）
- ``TriggerBinding``：``triggers`` 事件绑定
- ``events``：标准员工事件类型常量
"""

from app.domain.employee.capability import EmployeeCapability, parse_capabilities
from app.domain.employee.collaboration_graph import CollaborationGraph
from app.domain.employee.memory_scope import MemoryScope
from app.domain.employee.perception_spec import PerceptionSpec
from app.domain.employee.trigger_binding import TriggerBinding

__all__ = [
    "CollaborationGraph",
    "EmployeeCapability",
    "MemoryScope",
    "PerceptionSpec",
    "TriggerBinding",
    "parse_capabilities",
]
