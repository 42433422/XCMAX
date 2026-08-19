# ruff: noqa: E402, F401
"""ReAct agent loop + tool infrastructure for employee_pack.

This module provides the execution backbone that turns a single-shot employee
into a real agent able to read/write files, execute code and browse the web —
in the same way Cursor or other coding agents work: Reason → Act → Observe →
repeat until the task is done or the round limit is reached.

Architecture
------------

    ┌──────────────────────────────────────────────────────────┐
    │  blueprints.py  (generated per employee_pack)             │
    │  • builds ctx: call_llm, workspace tools, agent_runner   │
    │  • calls module.run(payload, ctx)                        │
    └────────────────┬─────────────────────────────────────────┘
                     │  ctx["agent_runner"]
                     ▼
    ┌──────────────────────────────────────────────────────────┐
    │  EmployeeAgentRunner.run(task, system_prompt)            │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │  for round in range(max_rounds):                 │   │
    │  │    LLM → JSON(thought + tool/answer)             │   │
    │  │    if answer   → return                          │   │
    │  │    if tool     → dispatch → observe              │   │
    │  └──────────────────────────────────────────────────┘   │
    └──────────────────────────────────────────────────────────┘

Tool calling protocol (the LLM must respond with valid JSON every turn):

  Tool call (not yet done):
    { "thought": "why I need this tool",
      "tool": "tool_name",
      "input": { ...tool params... } }

  Final answer (task complete):
    { "thought": "summary",
      "answer": "the actual result or written content" }

Available tools (injected via ctx by blueprints.py):
    read_workspace_file(path)          — read a file relative to workspace_root
    write_workspace_file(path,content) — write / create a file
    list_workspace_dir(path=".")       — list directory entries
    run_sandboxed_python(code)         — run Python in subprocess (std-lib only, 10 s limit)
    http_get(url, headers)             — HTTP GET (from existing ctx)
    http_post(url, json_body)          — HTTP POST (from existing ctx)
    call_llm(messages)                 — nested LLM call for sub-tasks
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)


from modstore_server.mod_employee_agent_runner_part01 import (
    _bounded_env_int as _bounded_env_int,
    _default_max_rounds as _default_max_rounds,
    _llm_timeout_seconds as _llm_timeout_seconds,
)


# ── Protocol constants ────────────────────────────────────────────────────────

TOOL_PROTOCOL_HEADER = """你是一个能执行真实工作的 AI 员工。
每轮必须输出以下两种格式之一的 **合法 JSON**（不加 markdown 围栏，不加解释文字）：

调用工具（任务未完成时）：
{{
  "thought": "当前分析与下一步计划（至少 20 字）",
  "tool": "工具名",
  "input": {{ 工具所需参数 }}
}}

给出最终答案（任务已完成时）：
{{
  "thought": "总结本次执行路径",
  "answer": "完整的最终结果（可以是 Markdown / JSON / 纯文本）"
}}

可用工具（按需选用，每次只调用一个）：
  analyze_project_summary  params: path(str, default=".")                        — 【优先使用】读取并摘要项目结构（manifests/技术栈/入口文件/README前800字）
  scan_project_tree        params: path(str, default="."), max_files(int, 200)   — 递归扫描目录树，返回文件列表与类型统计
  identify_file_types      params: path(str, default=".")                        — 按扩展名统计目录中的文件类型分布
  read_workspace_file      params: path(str)                                     — 读取工作区文件，最多返回 8000 字符
  write_workspace_file     params: path(str), content(str)                       — 写入（创建或覆盖）文件
  list_workspace_dir       params: path(str, default=".")                        — 列出目录条目（最多 50 项）
  run_sandboxed_python     params: code(str)                                     — 在隔离子进程中运行纯 Python（标准库）
  http_get                 params: url(str), headers(dict)                       — 发起 HTTP GET
  http_post                params: url(str), json_body(dict)                     — 发起 HTTP POST

约束：
1. 每轮只调用一个工具；结果会以 {{"tool_result": {{...}}}} 回传。
2. 最多 {max_rounds} 轮工具调用后必须输出 answer。
3. 禁止捏造工具结果；必须等待真实返回后再继续。
4. 若工具返回 ok=false，分析原因并换一种思路或直接告知用户。
5. 文件路径必须是相对工作区的相对路径，禁止绝对路径和 ".." 越界。
6. 项目分析任务必须先调用 analyze_project_summary，再按需读取具体文件，不得无依据生成技术描述。
"""

READ_ONLY_TOOL_PROTOCOL_HEADER = """你是一个执行真实只读巡检的 AI 员工。
每轮必须输出以下两种格式之一的合法 JSON（不加 markdown 围栏，不加解释文字）：

调用工具（任务未完成时）：
{{
  "thought": "当前分析与下一步计划（至少 20 字）",
  "tool": "工具名",
  "input": {{ "path": "." }}
}}

给出最终答案（任务完成时）：
{{
  "thought": "总结真实观察路径",
  "answer": "包含 status、summary、evidence 的 JSON 对象字符串"
}}

本次只提供以下只读工作区工具：
  analyze_project_summary  params: path(str, default=".")
  scan_project_tree        params: path(str, default="."), max_files(int, 200)
  identify_file_types      params: path(str, default=".")
  read_workspace_file      params: path(str)
  list_workspace_dir       params: path(str, default=".")

约束：
1. 每轮只调用一个已展示工具，结果会以 {{"tool_result": {{...}}}} 回传。
2. 最多 {max_rounds} 轮工具调用后必须输出 answer。
3. 禁止捏造工具结果；至少一次只读工具成功后才可报告 success。
4. 若工具返回 ok=false，换用另一个已展示的只读工具；不得猜测或调用未展示工具。
5. 文件路径必须是相对工作区的相对路径，禁止绝对路径和 ".." 越界。
6. 本次没有写入、命令、网络、消息、交接或变更工具，任何此类动作都不可用。
"""

RESEARCH_TOOLS_APPEND = """
  internet_search          params: query(str), max_results(int, 可选默认 8)             — 联网检索摘要（受服务器每日配额限制）
  github_repo_snapshot     params: owner(str), repo(str)                               — GitHub 公开仓库元数据与 README 摘录
"""

LLM_OPS_TOOLS_APPEND = """

【LLM 运维工程师专属工具】
  list_platform_llm_models params: provider(str, 可选), refresh(bool, 默认 false)          — 查询平台统一模型与动态能力目录
  list_llm_cli_status      params: live_probe(bool, 默认 false)                            — 检查 Codex/Cursor/Claude/Trae CLI 安装与真实可用性
  list_available_ai_routes params: refresh(bool), live_cli_probe(bool), live_quota_probe(bool)    — 合并平台模型、额度、CLI 与完整 AI 资产接口目录（assets）
  get_platform_llm_quota params: live_probe(bool, 默认 false)                             — 查询真实额度、24h 用量与可信度分级
  get_platform_llm_route   params: {}                                                   — 查询当前平台 AI 员工运行时路由
  get_llm_route_autopilot  params: {}                                                   — 查询后台主动巡检最近一次决策
  run_llm_route_autopilot  params: reason(str, 可选)                                    — 立即执行额度+健康巡检，必要时自动切换并验证/回滚
  switch_platform_llm_route params: provider(str), model(str), reason(str)              — 探活后立即切换下一次平台 AI 员工调用
  rollback_platform_llm_route params: reason(str, 可选)                            — 探活后回滚到上一个运行时路由

被问到「有哪些可用 AI / 接口 / 资产」时，必须先调用 list_available_ai_routes，
并以返回的 assets 为准汇报：interfaces（HTTP/runtime/CLI）、by_category
（llm/vlm/image/video/audio/embedding/rerank）、providers、cli_assets。
不得凭记忆编造未出现在 assets 中的接口。

切换约束：只能选择平台模型目录中存在、已配置平台密钥且探活成功的模型；
禁止传入 force 绕过目录或健康检查。所有切换都写入审计历史。
模型选型：先检查 models_detailed[].capabilities，按 input_modalities、
output_modalities 和 operations 匹配任务。capability_source=provider_metadata 最可靠；
hybrid/model_id_inference 包含规则推断，对 TTS、视频等非对话能力不得当成员工主聊天路由切换。
媒体接口：生图走 /api/llm/image，生视频走 /api/llm/video；均要求 OpenAI-compat
provider + 目录中对应 category 模型；audio/embedding/rerank 目前以目录发现为主。
CLI 兜底只在平台 API 调用失败时启用，按 Codex、Claude、Cursor、Trae 顺序尝试；
它们在隔离临时目录中以只读/无 YOLO 方式运行，不传递平台 API key。
CLI 仅接线文本对话；Codex 产品侧 image_generation 未接入平台兜底，须在 assets.cli_assets
的 product_capabilities_not_wired 中如实说明。
后台自动驾驶仅在生产显式开启时每 5 分钟检查当前路由；普通 429 只记录不切换，
连续 3 次真实错误且路由已驻留 15 分钟才允许切换，精确额度耗尽可立即切换。
所有切换使用 revision 比较交换，管理员并发操作优先；精确额度优先，其次真实调用探测，再其次本地用量账本。
额度未知必须标为 unknown/usage_only，不得推断为充足。
"""

LLM_OPS_READ_ONLY_TOOLS_APPEND = """

【LLM 运维工程师只读工具】
  list_platform_llm_models params: provider(str, 可选), refresh(false)
  list_llm_cli_status      params: live_probe(false)
  list_available_ai_routes params: refresh(false), live_cli_probe(false), live_quota_probe(false)
  get_platform_llm_quota   params: live_probe(false)
  get_platform_llm_route   params: {}
  get_llm_route_autopilot  params: {}
"""

HOST_CHECKER_TOOLS_APPEND = """

【宿主检查员工专属工具】
  probe_mod_host params: base_url(str, 可选), timeout_seconds(number, 可选) — 对白名单宿主执行只读 GET，检查 /api/mods/、/api/mods/llm-status、/api/version；不会返回密钥值
"""

SELF_CHECKER_TOOLS_APPEND = """

【员工包自检员工专属工具】
  validate_xcemp_package params: xcemp_path(str), timeout_seconds(number, 可选) — 校验工作区内 .xcemp 归档并在独立 cwd、最小环境变量的子进程中运行 validate
"""

_READ_ONLY_AGENT_TOOLS = frozenset(
    {
        "read_workspace_file",
        "list_workspace_dir",
        "scan_project_tree",
        "identify_file_types",
        "analyze_project_summary",
        "call_llm",
        "list_platform_llm_models",
        "list_llm_cli_status",
        "list_available_ai_routes",
        "get_platform_llm_quota",
        "get_platform_llm_route",
        "get_llm_route_autopilot",
    }
)

# ── Tool implementations ──────────────────────────────────────────────────────


from modstore_server.mod_employee_agent_runner_part02 import (
    _guard_path as _guard_path,
    tool_read_workspace_file as tool_read_workspace_file,
    tool_write_workspace_file as tool_write_workspace_file,
    tool_list_workspace_dir as tool_list_workspace_dir,
    tool_run_sandboxed_python as tool_run_sandboxed_python,
    tool_scan_project_tree as tool_scan_project_tree,
    tool_identify_file_types as tool_identify_file_types,
    tool_analyze_project_summary as tool_analyze_project_summary,
)


# ── EmployeeAgentRunner ───────────────────────────────────────────────────────


from modstore_server.mod_employee_agent_runner_employeeagentrunner_mixin01 import (
    _EmployeeAgentRunnerPart01Mixin,
)

from modstore_server.mod_employee_agent_runner_part03 import (
    EmployeeAgentRunner as EmployeeAgentRunner,
    _try_parse_json as _try_parse_json,
    build_agent_runner as build_agent_runner,
)
