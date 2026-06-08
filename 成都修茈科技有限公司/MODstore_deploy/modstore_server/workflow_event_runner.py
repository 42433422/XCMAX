"""工作流触发执行：供 Cron / 公开 Webhook / NeuroBus 事件共用（配额一致）。"""

from __future__ import annotations

from typing import Any, Dict

from modstore_server.models import get_session_factory
from modstore_server.quota_middleware import consume_llm_credit, require_llm_credit
from modstore_server.workflow_engine import execute_workflow


def run_workflow_for_trigger(
    *, workflow_id: int, user_id: int, input_data: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """执行一次工作流并扣减 ``llm_calls`` 配额（与 ``workflow_scheduler`` 语义对齐）。"""
    sf = get_session_factory()
    with sf() as qdb:
        require_llm_credit(qdb, user_id, 1)
    output = execute_workflow(workflow_id, input_data or {}, user_id=user_id)
    with sf() as qdb2:
        consume_llm_credit(qdb2, user_id, 1)
    return {"ok": True, "result": output}
