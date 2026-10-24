"""Task api for workbench delivery."""

from __future__ import annotations

import logging
from typing import cast

from fastapi import Depends

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.workbench.schemas import DispatchRequest

_LOG = logging.getLogger("modstore_server.workbench_api")


async def dispatch_task(body: DispatchRequest, user: User = Depends(_get_current_user)):
    """接收自然语言任务描述，由 task_router 拆解为子任务列表，按拓扑执行各员工。

    use_task_router=False 时退化为指定单员工的 plan_and_dispatch。
    """
    import asyncio

    loop = asyncio.get_event_loop()

    def _run():
        if body.use_task_router:
            from modstore_server.task_router import route_and_dispatch

            return route_and_dispatch(
                body.task_description,
                created_by_user_id=int(cast(int, user.id)),
                llm_provider=body.llm_provider,
                llm_model=body.llm_model,
                max_concurrency=body.max_concurrency,
                allow_high_risk_real_run=body.allow_high_risk_real_run,
            )
        else:
            from modstore_server.employee_orchestrator import plan_and_dispatch

            target = (body.target_employee_id or "daily-orchestrator").strip()
            return plan_and_dispatch(
                body.task_description,
                {},
                target_employee_id=target,
                created_by_user_id=int(cast(int, user.id)),
                max_concurrency=body.max_concurrency,
                allow_high_risk_real_run=body.allow_high_risk_real_run,
            )

    result = await loop.run_in_executor(None, _run)
    return result
