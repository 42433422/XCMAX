# mypy: disable-error-code="assignment"
"""Workbench "做脚本" 入口的薄壳：兼容旧 API，内部走新 ``script_agent`` 沙箱。

历史接口保留：
- 模块级 ``SCRIPT_ROOT``（被 ``test_workbench_script_runner.py`` 通过
  monkeypatch 替换为 ``tmp_path``）
- :func:`validate_script` —— 现在 delegate 到
  :mod:`modstore_server.script_agent.static_checker`
- :func:`_fallback_script` —— 仅测试/文档用；生产路径在 LLM 不可用时返回明确错误
- :func:`run_script_job` —— ``await`` 即跑通："生成 → 静检 → 沙箱执行"

Phase 2 起 ``script_agent.agent_loop`` 会承担多轮迭代修复，
本模块仅保留单轮"生成+执行"路径以服务 Workbench"快速跑一个脚本"场景。
"""

from __future__ import annotations

import logging

from modstore_server import workbench_script_agent_job as _agent_job
from modstore_server import workbench_script_job as _script_job
from modstore_server import workbench_script_support as _support
from modstore_server.llm_chat_proxy import chat_dispatch as chat_dispatch
from modstore_server.llm_key_resolver import resolve_api_key as resolve_api_key
from modstore_server.llm_key_resolver import resolve_base_url as resolve_base_url
from modstore_server.script_agent import sandbox_runner as _sandbox
from modstore_server.script_agent.agent_loop import _AGENT_V2 as _AGENT_V2
from modstore_server.script_agent.agent_loop import run_agent_loop as run_agent_loop
from modstore_server.script_agent.agent_loop import run_agent_loop_v2 as run_agent_loop_v2
from modstore_server.script_agent.context_collector import (
    tabular_upload_preview as tabular_upload_preview,
)
from modstore_server.script_agent.llm_client import extract_code_block as extract_code_block
from modstore_server.script_agent.static_checker import validate_script

logger = logging.getLogger(__name__)
_validate = validate_script

SCRIPT_ROOT = _sandbox.SCRIPT_ROOT
MAX_AGENT_ITERATIONS = 6
DEFAULT_SCRIPT_AGENT_ITERATIONS = 30
MAX_SCRIPT_AGENT_ITERATIONS = 50

_fallback_script = _support._fallback_script
_extract_code = _support._extract_code
_looks_like_non_python = _support._looks_like_non_python
validate_script = _support.validate_script
_ensure_script_outputs_fallback = _support._ensure_script_outputs_fallback
_materialize_fallback_output = _support._materialize_fallback_output
_ScriptGenResult = _support._ScriptGenResult
_generate_script = _support._generate_script
_repair_script_once = _support._repair_script_once

_brief_from_workbench = _agent_job._brief_from_workbench
run_script_agent_job = _agent_job.run_script_agent_job
run_script_job = _script_job.run_script_job
