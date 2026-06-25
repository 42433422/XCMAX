"""派工调度域：小C(assistant) 把任务派给二级/三级员工的统一闭环。

- ``WorkOrder``（app/db/models/work_order.py）：工单 SSOT（规范化、可查询）。
- :class:`DispatchRouter`：决定是否派工、派给谁。
- :class:`TaskDispatchService`：建单→派工→回收→状态流转→持久化→收口。
"""

from __future__ import annotations

from app.application.task_dispatch.router import DispatchRouter, RoutingDecision
from app.application.task_dispatch.service import (
    TaskDispatchService,
    get_task_dispatch_service,
)
from app.application.task_dispatch.status import WorkOrderStatus, can_transition
from app.application.task_dispatch.worker import (
    start_work_order_worker,
    stop_work_order_worker,
)

__all__ = [
    "DispatchRouter",
    "RoutingDecision",
    "TaskDispatchService",
    "get_task_dispatch_service",
    "WorkOrderStatus",
    "can_transition",
    "start_work_order_worker",
    "stop_work_order_worker",
]
