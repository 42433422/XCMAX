# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""战略-执行分层机制 — FastAPI 路由。

所有路由挂在 ``/api/xcmax/strategic`` 前缀下，分 4 个子域：
- ``/decisions``        — 战略决策账本（提议/批准/执行/复盘）
- ``/autonomy``         — 自治边界规则查看与 seed
- ``/meetings``         — 员工自治会议生命周期
- ``/reports``          — 周报/月报自动产出

鉴权策略：
- 读取类（GET）使用 ``get_current_user``（任意登录用户可读，确保透明）
- 写入类（POST）使用 ``require_admin``（仅管理员可触发状态变更，符合"信任度边界"）
- 内部 AI 员工通过 service-account token 走 ``require_admin`` 等价路径
"""

from __future__ import annotations

import importlib
import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server.api.actor_identity import authenticated_admin_actor
from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.strategic_layer import (
    AutonomyAction,
    CouncilMeetingService,
    DecidedBy,
    DecisionAlreadyDecidedError,
    DecisionLifecycleError,
    DecisionProposer,
    DecisionStatus,
    DecisionType,
    MeetingStatus,
    MeetingType,
    StrategicDecisionLedger,
    StrategicReportService,
    seed_default_boundaries,
)
from modstore_server.strategic_layer_models import CancelMeetingRequest as CancelMeetingRequest
from modstore_server.strategic_layer_models import (
    CompleteExecutionRequest,
)
from modstore_server.strategic_layer_models import ConcludeMeetingRequest as ConcludeMeetingRequest
from modstore_server.strategic_layer_models import (
    DecisionReviewRequest,
)
from modstore_server.strategic_layer_models import (
    GenerateMonthlyReportRequest as GenerateMonthlyReportRequest,
)
from modstore_server.strategic_layer_models import (
    GenerateWeeklyReportRequest as GenerateWeeklyReportRequest,
)
from modstore_server.strategic_layer_models import (
    ProposeDecisionRequest,
    ReviewDecisionRequest,
)
from modstore_server.strategic_layer_models import ScheduleMeetingRequest as ScheduleMeetingRequest
from modstore_server.strategic_layer_models import (
    StartExecutionRequest,
    StrategicCouncilReviewRequest,
)
from modstore_server.strategic_layer_models import (
    UpdateActionItemRequest as UpdateActionItemRequest,
)
from modstore_server.strategic_layer_models import (
    WithdrawRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax/strategic", tags=["strategic-layer"])


# ─── Pydantic 请求模型 ─────────────────────────────────────────────────────


# ─── 工具函数 ───────────────────────────────────────────────────────────────


from modstore_server.strategic_layer_api_part01 import (
    RetortClarificationAnswerRequest as RetortClarificationAnswerRequest,
)
from modstore_server.strategic_layer_api_part01 import _ledger as _ledger
from modstore_server.strategic_layer_api_part01 import (
    _lifecycle_error_to_http as _lifecycle_error_to_http,
)
from modstore_server.strategic_layer_api_part01 import _meeting_service as _meeting_service
from modstore_server.strategic_layer_api_part01 import _parse_dt as _parse_dt
from modstore_server.strategic_layer_api_part01 import _report_service as _report_service
from modstore_server.strategic_layer_api_part01 import _to_public_dict as _to_public_dict
from modstore_server.strategic_layer_api_part01 import (
    answer_retort_clarification as answer_retort_clarification,
)
from modstore_server.strategic_layer_api_part01 import approve_decision as approve_decision
from modstore_server.strategic_layer_api_part01 import complete_decision as complete_decision
from modstore_server.strategic_layer_api_part01 import get_decision as get_decision
from modstore_server.strategic_layer_api_part01 import (
    get_retort_clarification as get_retort_clarification,
)
from modstore_server.strategic_layer_api_part01 import (
    get_strategic_council_status as get_strategic_council_status,
)
from modstore_server.strategic_layer_api_part01 import list_autonomy_rules as list_autonomy_rules
from modstore_server.strategic_layer_api_part01 import list_decisions as list_decisions
from modstore_server.strategic_layer_api_part01 import (
    list_retort_clarifications as list_retort_clarifications,
)
from modstore_server.strategic_layer_api_part01 import propose_decision as propose_decision
from modstore_server.strategic_layer_api_part01 import reject_decision as reject_decision
from modstore_server.strategic_layer_api_part01 import review_decision as review_decision
from modstore_server.strategic_layer_api_part01 import (
    run_strategic_council_review as run_strategic_council_review,
)
from modstore_server.strategic_layer_api_part01 import start_decision as start_decision
from modstore_server.strategic_layer_api_part01 import (
    sweep_retort_clarifications as sweep_retort_clarifications,
)
from modstore_server.strategic_layer_api_part01 import withdraw_decision as withdraw_decision
from modstore_server.strategic_layer_api_part02 import seed_autonomy_rules as seed_autonomy_rules
from modstore_server.strategic_layer_api_part02 import (
    strategic_layer_health as strategic_layer_health,
)

_routes_module = importlib.import_module("modstore_server.strategic_layer_meeting_routes")
schedule_meeting = _routes_module.schedule_meeting
list_meetings = _routes_module.list_meetings
get_meeting = _routes_module.get_meeting
start_meeting = _routes_module.start_meeting
conclude_meeting = _routes_module.conclude_meeting
cancel_meeting = _routes_module.cancel_meeting
list_action_items = _routes_module.list_action_items
update_action_item = _routes_module.update_action_item
_parse_date = _routes_module._parse_date
generate_weekly_report = _routes_module.generate_weekly_report
generate_monthly_report = _routes_module.generate_monthly_report
list_reports = _routes_module.list_reports
get_report = _routes_module.get_report
