# ruff: noqa: E402, F401
"""员工自治闭环服务层。

提供：
- 建议单（EmployeeSuggestion）创建 / 审批 / 分发
- 协作线程（thread + mention）最小实现
- 每日简报待办任务入队与调度
- 文档一致性报告触发自动修复建议
- 员工执行指标驱动的 prompt 自进化建议
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import and_, func, or_

from modstore_server import employee_pack_proposal as _employee_pack_proposal
from modstore_server.llm_failure_classifier import FAILURE_KIND_QUOTA, FAILURE_KIND_TRANSIENT
from modstore_server.models import (
    EmployeeChangeRequest,
    EmployeeCollabMessage,
    EmployeeCollabThread,
    EmployeeEvolutionRecord,
    EmployeeExecutionMetric,
    EmployeeSuggestion,
    PendingBriefTask,
    User,
    get_session_factory,
)
from modstore_server.platform_llm_scope import platform_llm_scoped

logger = logging.getLogger(__name__)


from modstore_server.employee_autonomy_service_part01 import (
    _jloads as _jloads,
    _jdumps as _jdumps,
    _dedupe_strs as _dedupe_strs,
    _resolve_actor_user_id as _resolve_actor_user_id,
    _publish_event as _publish_event,
    _suggestion_auto_dispatch_enabled as _suggestion_auto_dispatch_enabled,
    _brief_auto_dispatch_enabled as _brief_auto_dispatch_enabled,
    _doc_autofix_enabled as _doc_autofix_enabled,
    _evolution_enabled as _evolution_enabled,
    _infer_suggestion_targets as _infer_suggestion_targets,
    create_collab_thread as create_collab_thread,
    post_collab_message as post_collab_message,
    create_employee_suggestion as create_employee_suggestion,
    ingest_suggestion_event_payload as ingest_suggestion_event_payload,
    approve_suggestion as approve_suggestion,
    reject_suggestion as reject_suggestion,
    _build_subtask_text as _build_subtask_text,
    dispatch_suggestion as dispatch_suggestion,
    dispatch_pending_suggestions as dispatch_pending_suggestions,
)


_TODO_BULLET_RE = re.compile(r"^\s*(?:[-*•]|(?:\d+[\.\)\、]))\s*(.+?)\s*$")


from modstore_server.employee_autonomy_service_part02 import (
    _parse_todo_lines as _parse_todo_lines,
    enqueue_daily_brief_todos as enqueue_daily_brief_todos,
    list_pending_brief_tasks as list_pending_brief_tasks,
    dispatch_pending_brief_tasks as dispatch_pending_brief_tasks,
    trigger_doc_autofix_from_report as trigger_doc_autofix_from_report,
    _PlatformBenchLlmClient as _PlatformBenchLlmClient,
)


# 进化引擎只应对「prompt 可修」的失败做 prompt 优化。配额/限流/鉴权/缺 key 等基建类失败
# 不是 prompt 问题，refine prompt 救不回来；这些失败进入候选会导致进化引擎空转。
_EVOLUTION_INFRA_FAILURE_MARKERS: Tuple[str, ...] = (
    "配额",
    "quota",
    "llm_calls",
    "429",
    "too many requests",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "limitation",
    "missing api key",
    "未配置",
    "para_api",
    "para api",
    "para_delegate",
    "blocked_no_online_para_device",
    "missing_para_api_base_or_device_id",
)
_EVOLUTION_IGNORED_TASK_MARKERS: Tuple[str, ...] = (
    "event=employee.evolution.",
    "event=employee.suggestion.",
    "event=employee.collab.",
    "event=employee.brief_todo.",
    "event=employee.execution.recovery",
)
_PARA_DELEGATE_EMPLOYEES: Tuple[str, ...] = (
    "vibe-coding-maintainer",
    "change-request-auditor",
    "test-qa-runner",
)
_GENERIC_HANDLER_FAILURE = "one or more handlers returned ok=false"


from modstore_server.employee_autonomy_service_part03 import (
    _alert_evolution_quota_circuit_break as _alert_evolution_quota_circuit_break,
    _evolution_failure_candidates as _evolution_failure_candidates,
    run_employee_evolution_scan as run_employee_evolution_scan,
    aggregate_admin_suggestion_dashboard as aggregate_admin_suggestion_dashboard,
)


__all__ = [
    "aggregate_admin_suggestion_dashboard",
    "approve_suggestion",
    "create_collab_thread",
    "create_employee_suggestion",
    "dispatch_pending_brief_tasks",
    "dispatch_pending_suggestions",
    "dispatch_suggestion",
    "enqueue_daily_brief_todos",
    "ingest_suggestion_event_payload",
    "list_pending_brief_tasks",
    "post_collab_message",
    "reject_suggestion",
    "run_employee_evolution_scan",
    "trigger_doc_autofix_from_report",
]


# Keep the historical service API while the workflow imports the lightweight
# module directly (this service also imports database-backed employee models).
ProposalValidationError = _employee_pack_proposal.ProposalValidationError
validate_proposal = _employee_pack_proposal.validate_proposal
_call_llm = _employee_pack_proposal._call_llm


from modstore_server.employee_autonomy_service_part04 import (
    propose_employee_pack as propose_employee_pack,
)
