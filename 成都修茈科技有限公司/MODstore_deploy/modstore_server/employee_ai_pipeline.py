# isort: skip_file
# ruff: noqa: E402, F401
"""7 阶段 AI 员工流水线：NL → 完整 employee_pack manifest + 实现代码。

每个阶段独立 LLM 调用 + 严格 JSON 校验；通过 on_event 回调推送 SSE 事件，
供 /api/workbench/employee-ai/draft 端点实时流式输出。

S1-S6 生成 manifest；S7 生成运行时代码（direct_python vendor/ 或 agent 实现）。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from modstore_server.operational_errors import RECOVERABLE_ERRORS

from modstore_server.employee_ai_scaffold import (
    _default_capabilities,
    _default_skill_entries,
    _normalize_behavior_rules,
    _normalize_employee_system_prompt,
    _strip_json_fence,
)
from modstore_server.script_agent.llm_client import LlmClient

# ── system prompts ────────────────────────────────────────────────────────────

_SYS_PARSE_INTENT = """你是 AI 员工意图解析器。用户用自然语言描述想要的 AI 员工。
你只输出一个 JSON 对象（不含 markdown 围栏），字段：
- id: 字符串，小写英文/数字/连字符，2-32 字符
- name: 简短中文显示名（不超过 12 字）
- role: 角色核心职能（不超过 20 字）
- scenario: 使用场景（不超过 80 字）
- industry: 行业分类（如"电商""金融""教育""通用"等）
- complexity: "low"/"medium"/"high"

示例：{"id":"refund-assistant","name":"退款客服助手","role":"退款流程处理","scenario":"用户提交退款申请后自动核查订单并输出处理意见","industry":"电商","complexity":"medium"}"""

_SYS_RANK_WORKFLOW = """你是 AI 工作流选型助手。给你员工意图描述和候选工作流列表，只输出一个 JSON 对象：
- best_index: 最匹配工作流的 index（从 0 开始），若均不匹配输出 -1
- score: 匹配度 0.0-1.0
- reason: 一句话理由（不超过 40 字）

当 score < 0.5 时，best_index 必须为 -1。"""

_SYS_DESIGN_V2 = """你是 XCAGI employee_config_v2 设计师。根据员工意图，只输出一个 JSON 对象，字段：
- perception: 对象，含 type（"text"|"document"|"event"|"web_rankings"|"multimodal"）
- memory: 对象，含 type（"session"|"long_term"|"none"）；需长期记忆时加 knowledge_base 字符串
- cognition: 对象，含 agent.system_prompt（至少 200 字专业 prompt，见要求）及 agent.model（provider/model_name/max_tokens/temperature）
- actions: 对象，含 handlers 数组（合法值见下方）

──────────────────────────────────────────────
handlers 合法值（按任务复杂度选择）：
  "agent"   → **ReAct 多步 agent 循环**（推荐）。员工可使用工具链：读写工作区文件、运行 Python、发起 HTTP。
              适用：需要多步推理、文件操作、代码执行、数据汇总等任何"做事"类任务。
  "direct_python" → **纯 Python 直接执行**，不调 LLM。员工 run(payload, ctx) 函数由宿主直接调用。
              适用：文件格式转换（Excel/Word/PDF/CSV 读取与生成）、数据提取、确定性计算等不需要 LLM 推理的任务。
              选择此 handler 时，system_prompt 可简短（描述输入输出契约即可），model 可省略。
  "llm_md"  → 单轮 LLM 调用，输出 Markdown。适用：纯问答/总结/翻译等一问一答类任务。
  "webhook" → 转发到 actions.webhook.url（必须同时提供 url）。适用：需要转发到外部 webhook 的通知类任务。
  "echo"    → 仅回显 payload，**不调 LLM**。适用：测试/调试，不要在正式员工中使用。
  "vibe_edit"  → 单轮多文件代码编辑（需配置 actions.vibe_edit.root）。
  "vibe_heal"  → 多轮代码自愈（需配置 actions.vibe_heal.root）。
  "vibe_code"  → NL → CodeSkill（需配置 actions.vibe_code.brief）。

选择原则：
  - 只要员工需要"做事"（写文件/读文件/执行步骤/多步分析/调用工具）→ 选 "agent"
  - 任务是确定性的文件处理/格式转换/数据提取，不需要 LLM 推理 → 选 "direct_python"
  - 只是"回答问题"（一问一答，不需要工具）→ 选 "llm_md"
  - 代码重构/自愈场景 → 选 vibe_edit/vibe_heal
  - 禁止在"做事"员工上写 "echo"（echo 不调 LLM，会让员工什么都做不了）
──────────────────────────────────────────────

system_prompt 要求（不少于 200 字）：
1. 必须是员工运行时真正使用的系统提示，不是产品介绍或使用说明；
2. 必须明确：
   a. 角色边界（我是谁、我能做什么、我不能做什么）
   b. 工作步骤（3-7 步具体执行流程，如：收到请求 → 读取配置 → 扫描目录 → 分析 → 生成输出 → 写入文件）
   c. 可用工具及调用时机（agent 模式下：read_workspace_file/write_workspace_file/list_workspace_dir/run_sandboxed_python 等）
   d. 输出格式（结构化 JSON / Markdown 章节 / 具体字段列表）
   e. 失败策略（工具失败如何降级，信息不足时如实告知）
   f. 禁止事项（禁止编造数据/结果/文件内容，禁止越界访问）
3. 若已绑定工作流或候选 Skill，必须在 system_prompt 中说明何时进入工作流及失败时降级方案；
4. 不要使用"用途/输入/输出/示例"模板章节，不要只复述用户 brief；
5. 不得编造未给出的外部系统状态、执行结果、数据来源。

model 建议：provider 默认 "auto"，model_name 默认 "auto"，temperature 0.2，
           agent 模式下 max_tokens 建议 2048（每轮工具调用），llm_md 模式下 max_tokens 建议 4000。"""

_SYS_SUGGEST_SKILLS = """你是 AI 技能推荐助手。根据员工角色和场景推荐合适的技能，只输出 JSON 数组（不含对象包裹），每项含：
- name: 技能名（不超过 16 字）
- brief: 技能简介（不超过 50 字）
- kind: 技能类型，从以下选一个：
    "project_directory_scan"  → 目录/文件树扫描
    "file_type_identification" → 文件类型识别与统计
    "manifest_reading"         → 读取项目配置文件（package.json/pyproject.toml/README 等）
    "readme_generation"        → 生成项目文档/README
    "code_analysis"            → 静态代码分析
    "domain_specific"          → 其他领域特定技能

推荐 2-5 个，按重要性排序。
示例：[{"name":"目录扫描","brief":"递归列出项目文件树，识别源码、配置、资源目录","kind":"project_directory_scan"}]"""

# Keywords that indicate a "project analysis / documentation" type employee.
# When detected, the pipeline forces `agent` handler and adds workspace config.
_PROJECT_ANALYSIS_KEYWORDS: frozenset = frozenset(
    {
        "readme",
        "文档",
        "documentation",
        "docs",
        "说明",
        "使用说明",
        "项目分析",
        "项目介绍",
        "技术栈",
        "目录结构",
        "安装指南",
        "部署指南",
        "生成文档",
        "generate readme",
        "generate docs",
        "project doc",
        "代码库",
        "codebase",
        "代码分析",
        "代码文件",
        "项目文件",
    }
)

_SYS_SUGGEST_PRICING = """你是 AI 定价顾问。根据员工复杂度、功能丰富度、行业特性建议定价，只输出一个 JSON 对象：
- tier: "free"/"basic"/"standard"/"pro"/"enterprise"
- cny: 月费（人民币），免费则 0
- period: "month"（月付）/ "year"（年付）/ "once"（买断）
- reasoning: 不超过 60 字的定价理由

定价参考区间：free=0，basic≤9，standard≤29，pro≤99，enterprise≥99"""

_SYS_REFINE_PROMPT = """你是专业 system prompt 优化助手。用户提供当前 system prompt 和优化指令，你须：
1. 输出优化后的 system prompt（与原文同语言，去掉废话/模糊表述，增强具体性和专业度）
2. 用一句话解释主要改动

只输出一个 JSON 对象：
- improved_prompt: 完整的优化后 system prompt（字符串）
- diff_explanation: 改动说明（不超过 80 字）"""


# ── dataclasses ───────────────────────────────────────────────────────────────


from modstore_server.employee_ai_pipeline_part01 import (
    Intent as Intent,
    WorkflowChoice as WorkflowChoice,
    EmployeeConfigV2 as EmployeeConfigV2,
    SuggestedSkill as SuggestedSkill,
    _is_project_analysis_intent as _is_project_analysis_intent,
    PricingHint as PricingHint,
    _parse_json as _parse_json,
    stage_parse_intent as stage_parse_intent,
    stage_resolve_workflow as stage_resolve_workflow,
    stage_design_v2 as stage_design_v2,
    _build_employee_runtime_prompt as _build_employee_runtime_prompt,
    _quality_gate_system_prompt as _quality_gate_system_prompt,
    stage_suggest_skills as stage_suggest_skills,
    stage_suggest_pricing as stage_suggest_pricing,
    stage_assemble as stage_assemble,
    _build_vibe_coding_prompt as _build_vibe_coding_prompt,
    GeneratedCode as GeneratedCode,
)


from modstore_server.employee_ai_pipeline_part02 import (
    stage_generate_code as stage_generate_code,
    refine_system_prompt as refine_system_prompt,
    run_pipeline as run_pipeline,
)
