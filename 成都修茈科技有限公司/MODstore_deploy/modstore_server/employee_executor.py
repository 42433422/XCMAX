# ruff: noqa: E402, F401
"""AI员工执行器：基于 employee_config_v2 的真实执行管道。"""

from __future__ import annotations

import asyncio
import csv
import importlib.util
import io
import json
import logging
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from modstore_server.catalog_store import files_dir
from modstore_server.duty_burn_in_handlers import (
    bind_reviewed_burn_in_handlers,
)
from modstore_server.duty_burn_in_handlers import (
    deterministic_direct_input_ready as _deterministic_direct_input_ready,
)
from modstore_server.duty_burn_in_handlers import (
    is_reviewed_direct_burn_in,
)
from modstore_server.employee_runtime import (
    build_employee_context,
    load_employee_pack_resolved,
    parse_employee_config_v2,
)
from modstore_server.llm_failure_classifier import FAILURE_KIND_QUOTA, classify_failure_kind
from modstore_server.models import EmployeeExecutionMetric, User, get_session_factory
from modstore_server.runtime_async import run_coro_sync as _run_coro_sync
from modstore_server.services.llm import chat_dispatch_via_session

logger = logging.getLogger(__name__)

_METRIC_TASK_MAX_LEN = 128


from modstore_server.employee_executor_part01 import (
    _emp_im_notify_boss as _emp_im_notify_boss,
)


# 员工大会待机：manifest system_prompt 常要求「输出 JSON」，与四段 Markdown 汇报冲突。
_ALL_HANDS_COGNITION_SYSTEM_APPEND = """\
【员工大会模式 — 覆盖日常 JSON 输出要求】
当前任务为数字管家召集的「员工大会」汇报（非流水线执行、非工作台单次任务）。
硬性要求：
- 回复必须说人话：先给结论/状态，再说原因，再说下一步；不要直接倾倒 JSON、内部字段或英文模板。
- 只输出 **简体中文 Markdown**，严格按用户消息中的四段标题结构作答；**禁止**输出 JSON、禁止 ``warnings`` / ``status`` 字段。
- 用 manifest / depends_on / handlers 与 input 中的节选说明职责；缺上游产物在待机模式下**属于正常**，不得写「输入不足」类流水线报错。
- 不得编造 research_context / yuangon_pack_excerpt / recent_failures 中未出现的路径或版本号。"""

_ALL_HANDS_ROLE_CONTEXT_MODES = frozenset({"all_hands_meeting", "all_hands_standby"})


# 10 项成熟度第 1 项「主动沟通」协议：让 LLM 知道有 requires_human 通道可用，
# 遇到下面任一情况必须主动向老板提问（输出 requires_human=true + human_question）。
# 不破坏原 JSON 输出格式，只是把 requires_human / human_question 作为可选字段加入。
#
# 触发门收紧（2026-07-20）：仅条件 1-4（真正需要老板业务决策）才走 requires_human。
# - 条件 5（超职责）→ 交由 handoff_to 协议处理，不问老板
# - 条件 6（3次失败）→ 输出 exhausted=true + failure_summary，不问老板，由进化扫描接手
# - 条件 7（泛化不确定）→ 移除，依赖 1-4 的具体场景判断
_PHASE_D_PROTOCOL_APPEND = """\
【主动沟通协议 — 强制遵守】
你是真员工，不是提示词机器人。完成任务时遇到以下任一情况，**必须**在 JSON 输出里追加两个字段：
- "requires_human": true
- "human_question": "<你具体想问老板的问题，简短一句中文>"

需要主动提问的情况（仅限需要老板本人业务决策）：
1. 任务优先级不明确（多个任务冲突，不知道先做哪个）
2. 缺资源（需要其他员工配合、需要数据、需要权限）
3. 发现风险（代码改动可能影响线上、安全风险、合规风险）
4. 需要老板决策（业务方向、产品取舍、用户影响）

提问要具体，不要套话。例：
- ❌ "需要老板确认" — 太空
- ✅ "本周修复 A 还是 B 优先级更高？目前 A 影响 100 用户/天" — 具体

没有上述情况时，正常输出你的工作 JSON，不需要带 requires_human 字段。

【失败耗尽协议 — 不问老板】
如果同一任务你已经失败 3 次仍无法解决，**不要**输出 requires_human，改为追加：
- "exhausted": true
- "failure_summary": "<三次失败的原因摘要，各一句>"
失败耗尽时由系统进化扫描接手（改进你的 prompt 或转给更合适的员工），不需要老板介入。

【任务转交协议 — 同事协作】
如果你判断任务**不属于你的职责范围**（如本员工 manifest 没覆盖的代码路径 / 接口 / 服务），
应该在 JSON 输出里追加：
- "handoff_to": "<目标员工的 employee_id>"
- "handoff_reason": "<为什么转交给他，一句话>"
- "handoff_context": "<上下文摘要，让目标员工不用重新看一遍 task>"

只在你**确实无法处理**时才转交，不要把简单任务推给别人。
转交后你仍然要正常完成你能做的部分，不要因为转交就停手。"""


from modstore_server.employee_executor_part02 import (
    _is_all_hands_cognition_context as _is_all_hands_cognition_context,
    _build_all_hands_cognition_user_message as _build_all_hands_cognition_user_message,
    _metric_task_preview as _metric_task_preview,
    _flag_enabled as _flag_enabled,
    _resolve_metric_user_id as _resolve_metric_user_id,
)


_executor_sem: threading.Semaphore | None = None
_executor_sem_n: int = 0


from modstore_server.employee_executor_part03 import (
    _executor_max_concurrent as _executor_max_concurrent,
    _get_executor_semaphore as _get_executor_semaphore,
    _executor_extra_cognition_retries as _executor_extra_cognition_retries,
    _executor_detail_log_enabled as _executor_detail_log_enabled,
    _is_transient_llm_error as _is_transient_llm_error,
    _run_cognition_with_transient_retries as _run_cognition_with_transient_retries,
    _get_section as _get_section,
    _perception_excel as _perception_excel,
    _extract_vision_data_urls as _extract_vision_data_urls,
    _perception_image as _perception_image,
    _memory_long_term_chroma as _memory_long_term_chroma,
    _perception_real as _perception_real,
    _perception_document as _perception_document,
    _perception_web_rankings as _perception_web_rankings,
    _memory_real as _memory_real,
    _cognition_real as _cognition_real,
    _cognition_sync as _cognition_sync,
)


from modstore_server.employee_executor_part04 import (
    _action_wechat_notify as _action_wechat_notify,
    _action_openapi_tool as _action_openapi_tool,
    _tpl_str as _tpl_str,
    _tpl_obj as _tpl_obj,
    _action_fhd_business as _action_fhd_business,
    _merge_original_input_into_reasoning as _merge_original_input_into_reasoning,
    _trusted_system_burn_in_project_root as _trusted_system_burn_in_project_root,
    _trusted_system_duty_contract_execution as _trusted_system_duty_contract_execution,
    _action_agent_runner as _action_agent_runner,
)


from modstore_server.employee_executor_part05 import (
    _employee_pack_extract_root as _employee_pack_extract_root,
    _action_direct_python as _action_direct_python,
    _prefer_para_with_local_fallback as _prefer_para_with_local_fallback,
    _filter_handlers_vibe_coding_maintainer as _filter_handlers_vibe_coding_maintainer,
    _actions_real as _actions_real,
    _extract_token_count as _extract_token_count,
)


from modstore_server.employee_executor_part06 import (
    _auto_wrap_execution_result_to_change_requests as _auto_wrap_execution_result_to_change_requests,
    _handlers_execution_ok as _handlers_execution_ok,
    _handler_failure_detail as _handler_failure_detail,
    _evaluate_employee_risk_gate as _evaluate_employee_risk_gate,
)


from modstore_server.employee_executor_part07 import (
    execute_employee_task as execute_employee_task,
    get_employee_status as get_employee_status,
)


from modstore_server.employee_executor_part08 import (
    list_employees as list_employees,
)
