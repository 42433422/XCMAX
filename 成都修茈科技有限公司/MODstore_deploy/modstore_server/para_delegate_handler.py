# isort: skip_file
# ruff: noqa: E402, F401
"""Bridge MODstore duty employees to Para / DevFleet.

The server process cannot call Codex-side MCP tools directly. This handler is
therefore deliberately explicit:

- If ``MODSTORE_PARA_DELEGATE_WEBHOOK`` is configured, it posts a dispatch
  request and trusts only an ``ok=true`` response as executed/accepted.
- If ``MODSTORE_PARA_API_BASE`` is configured, it authenticates against
  Para/DevFleet and creates a real AI subtask on the configured device.
- Otherwise it writes a durable outbox record and returns ``ok=false`` so the
  loop does not report fake success.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

_PARA_GUEST_AUTH_CACHE: Dict[str, str] = {}
DEFAULT_PARA_WAIT_TIMEOUT_SEC = 1800.0


from modstore_server.para_delegate_handler_part01 import (
    _env_bool as _env_bool,
    para_delegate_enabled as para_delegate_enabled,
    para_delegate_ready_for_dispatch as para_delegate_ready_for_dispatch,
    _webhook_url as _webhook_url,
    _api_base as _api_base,
    _api_timeout as _api_timeout,
    _wait_for_completion_default as _wait_for_completion_default,
    _wait_timeout_sec as _wait_timeout_sec,
    _wait_poll_sec as _wait_poll_sec,
    _outbox_dir as _outbox_dir,
    _project_root as _project_root,
    _mode_for_employee as _mode_for_employee,
    _build_request as _build_request,
    _public_request as _public_request,
    _write_outbox as _write_outbox,
    _outbox_response as _outbox_response,
    _allow_local_workdir as _allow_local_workdir,
    _build_para_prompt as _build_para_prompt,
    _get_para_token as _get_para_token,
    _summarize_para_response as _summarize_para_response,
    _para_db_file as _para_db_file,
    _force_single_device_attempt as _force_single_device_attempt,
    _resolve_max_attempts as _resolve_max_attempts,
    _git_preflight_branch as _git_preflight_branch,
    _task_result_snapshot as _task_result_snapshot,
    _wait_for_para_task as _wait_for_para_task,
    _first_para_error as _first_para_error,
)

# ── Para 分级派工：一级=本机单设备，二级=多设备协同（与 FHD super_employee_service 同构） ──
#
# loops 后半经此桥接 Para/DevFleet。原先只认单个写死的 MODSTORE_PARA_DEVICE_ID，没配
# 就 outbox。现补齐与 FHD 一致的分级：默认一级优先——发现在线的本机/主设备派单设备；
# 仅当任务显式要多设备并行/分工(max_devices>1 / target_devices 多个 / para_tier=2 /
# escalate / 文本含"多设备"等)或本机不可用时升二级，扇出到多台 worker。显式给了
# device_id 的部署保持原行为不变(零回归)。设备配对+agent 拉起仍属 DevFleet/运维侧。

_SUBTASK_LABELS = ("需求定位与方案", "核心实现", "验证与收尾")


from modstore_server.para_delegate_handler_part02 import (
    _fallback_order_tools as _fallback_order_tools,
    _dev_tool as _dev_tool,
)

_VALID_DEV_TOOLS = ("codex", "claude_code", "cursor", "trae")
_TOOL_INPUT_ALIASES = {
    "claude": "claude_code",
    "claude-code": "claude_code",
    "cursor_agent": "cursor",
    "cursor-agent": "cursor",
}

# DevFleet / Mac Bridge 上报的 capability / toolName 与调度侧命名不完全一致。
_TOOL_CAP_ALIASES: Dict[str, tuple[str, ...]] = {
    "codex": ("codex_cli",),
    "cursor": ("cursor_cli", "cursor_agent_cli", "cursor-agent_cli"),
    "claude_code": ("claude_code_cli", "claude_cli", "claude-code_cli"),
    "trae": ("trae_cli",),
}
_TOOL_NAME_ALIASES: Dict[str, tuple[str, ...]] = {
    "codex": ("codex",),
    "cursor": ("cursor", "cursor_agent", "cursor-agent"),
    "claude_code": ("claude_code", "claude", "claude-code"),
    "trae": ("trae",),
}


from modstore_server.para_delegate_handler_part03 import (
    _normalize_tool_name as _normalize_tool_name,
    _tool_fallback_allowed as _tool_fallback_allowed,
    _excluded_tools as _excluded_tools,
    _tool_candidates as _tool_candidates,
    _is_cli_runtime_failure as _is_cli_runtime_failure,
    _device_discovery_enabled as _device_discovery_enabled,
    _safe_json as _safe_json,
    _device_tool_entry as _device_tool_entry,
    _device_has_capability as _device_has_capability,
    _device_eligible as _device_eligible,
    _selected_tool_for_device as _selected_tool_for_device,
    _with_selected_tool as _with_selected_tool,
    _select_local_device_with_fallback as _select_local_device_with_fallback,
    _select_fleet_devices_with_fallback as _select_fleet_devices_with_fallback,
    _filter_executor_ready as _filter_executor_ready,
    _resolve_tier as _resolve_tier,
    _max_fleet_devices as _max_fleet_devices,
    _select_local_device as _select_local_device,
    _select_fleet_devices as _select_fleet_devices,
    _fetch_devices as _fetch_devices,
    _resolve_dispatch_devices as _resolve_dispatch_devices,
    _multi_device_prompt as _multi_device_prompt,
    _para_subtask_title as _para_subtask_title,
    _req_with_excluded_tools as _req_with_excluded_tools,
    _attach_tool_fallback_meta as _attach_tool_fallback_meta,
    _post_para_api as _post_para_api,
)


from modstore_server.para_delegate_handler_part04 import (
    _post_para_api_once as _post_para_api_once,
    _coerce_bool as _coerce_bool,
    _post_webhook as _post_webhook,
    dispatch_para_delegate as dispatch_para_delegate,
)

__all__ = [
    "dispatch_para_delegate",
    "para_delegate_enabled",
    "para_delegate_ready_for_dispatch",
]
