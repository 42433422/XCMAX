# isort: skip_file
"""LLM 生成 employee_pack manifest + 最小 zip，经 import_zip 落入用户 Mod 库（与商店上架分离，需用户自行上传上架）。"""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from modman.manifest_util import validate_manifest_dict
from modstore_server.employee_pack_blueprints_template import (
    render_employee_pack_blueprints_py,
    render_employee_pack_employee_py,
)
from modstore_server.employee_scaffold_presets import resolve_preset_capabilities
from modstore_server.employee_stub_template import (
    safe_stub_module_name,
    stub_module_body,
)
from modstore_server.mod_employee_impl_scaffold import sanitize_employee_stem
from modstore_server.xcagi_host_profile import (
    merge_workflow_employee_for_manifest,
    normalize_xcagi_host_profile,
)

_SCAFFOLD_FACADE_EXPORTS: tuple[Any, ...] = (
    io,
    json,
    re,
    zipfile,
    Dict,
    List,
    Optional,
    Tuple,
)
_SCAFFOLD_FACADE_EXPORTS += (validate_manifest_dict, render_employee_pack_blueprints_py)
_SCAFFOLD_FACADE_EXPORTS += (
    render_employee_pack_employee_py,
    resolve_preset_capabilities,
)
_SCAFFOLD_FACADE_EXPORTS += (
    safe_stub_module_name,
    stub_module_body,
    sanitize_employee_stem,
)
_SCAFFOLD_FACADE_EXPORTS += (
    merge_workflow_employee_for_manifest,
    normalize_xcagi_host_profile,
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

_TEMPLATE_BRIEF_PATTERNS = [
    "围绕",
    "执行",
    "相关任务",
    "相关内容",
]


SYSTEM_PROMPT_EMPLOYEE = """你是 XCAGI 全局员工包（employee_pack）清单生成器。用户用自然语言描述想要的 AI 员工能力。
你必须只输出一个 JSON 对象（不要 markdown 围栏、不要解释文字），字段如下：
- id: 字符串，小写英文/数字/点/下划线/连字符，以字母或数字开头，表示包 id（安装目录名），建议 2–48 字符
- name: 简短中文或英文显示名
- version: 语义化版本，默认 "1.0.0"
- description: 一句话介绍
- employee: 对象，必填，含：
  - label: 显示标签
  - capabilities: 字符串数组，能力标识，可为空数组
  （注意：不要写 employee.id 字段，系统会自动从顶层 id 派生）
- department_preset: 可选字符串。当 employee.capabilities 为空时，用于套用脚手架内置部门能力预设（键名见 MODstore 文档 ``employee-scaffold-presets.md``），例如 design、engineering、qa。
- employee_config_v2: 可选对象。应尽量完整描述员工运行时行为，至少包含：
  - cognition.agent.system_prompt: 面向运行时员工的可执行系统提示，必须写清：
    角色边界、可处理任务、输入信息使用方式、输出格式、拒答/不确定时策略、禁止编造。
    不要写空泛口号，不要只复述用户 brief，不要套用固定 API 文档章节。
  - cognition.agent.role: name/persona/tone/expertise，与员工能力一致。
  - cognition.agent.behavior_rules: 3-8 条具体行为规则。
  - cognition.skills: 1-6 个技能条目，每个条目说明 brief。
- 若用户要求联网、网页抓取、AI 模型排行统计，应包含：
  - perception: {"type":"web_rankings"}
  - cognition.agent.system_prompt: 要求基于网页片段输出模型、排名、来源、结论；必须明确引用来源、标注抓取失败来源，并禁止编造未出现在片段中的排名。
  - cognition.agent.model: {"provider":"auto","model_name":"auto","max_tokens":4000}
  - actions.handlers: **必须如实声明**，合法值仅限 ["echo", "llm_md", "webhook"]（vibe_* 见下方扩展）。
    * "echo"   = 仅回显 payload，**不会调 LLM**；不要在只想让模型回话时写 echo
    * "llm_md" = 调 LLM 出 Markdown（默认走 cognition.agent.model 的 max_tokens/temperature）
    * "webhook"= 转发到 actions.webhook.url；声明 webhook 时必须在 actions.webhook 中给出 url
    禁止声明 ["echo"] 但实际期望模型回答；如需模型回答，请写 ["llm_md"]。
  - 若用户描述里出现「写代码 / 改代码 / 自动重构 / 自愈 / refactor / heal」等关键词，
    actions.handlers 可加入 vibe-coding 系列：
      vibe_edit  → 单轮多文件编辑：actions.vibe_edit = {"root":"<工作区子目录>", "brief":"...", "focus_paths":[...], "dry_run":false}
      vibe_heal  → 多轮自愈：actions.vibe_heal = {"root":"<工作区子目录>", "brief":"...", "max_rounds":3}
      vibe_code  → NL → 单技能：actions.vibe_code = {"brief":"...", "skill_id":"...", "run_input":{...}}
    root 必须落在用户工作区下，宿主会强制路径白名单；不要硬编码绝对路径。
- xcagi_host_profile: 可选对象，用于宿主副窗 / 内置轨道对齐（勿编造不存在的 id）：
  - panel_kind: "mod_http" | "builtin_track" | "placeholder"（默认 mod_http）
  - builtin_track_id: 仅当 panel_kind=builtin_track 时填写，允许值之一：
    label_print, shipment_mgmt, receipt_confirm, wechat_msg, wechat_phone, real_phone
  - workflow_employee_row: 可选对象，会合并进 manifest.workflow_employees[0]（如 phone_agent_base_path、workflow_placeholder 等）

示例（employee 对象中不要写 id 字段）：
{"id":"qq-watch-helper","name":"消息监控助手","version":"1.0.0","description":"协助整理与监控类需求","employee":{"label":"监控助手","capabilities":["chat.summarize"]},"xcagi_host_profile":{"panel_kind":"mod_http"}}
"""


from modstore_server.employee_ai_scaffold_part_1 import (  # noqa: E402
    _is_template_brief as _is_template_brief,
    _validate_skill_quality as _validate_skill_quality,
    _default_capabilities as _default_capabilities,
    _default_skill_entries as _default_skill_entries,
    _default_skill_brief as _default_skill_brief,
    _seo_skill_structure as _seo_skill_structure,
    _is_seo_context as _is_seo_context,
    _seo_few_shot_examples as _seo_few_shot_examples,
    _seo_focus_paths as _seo_focus_paths,
    _seo_prompt_suffix as _seo_prompt_suffix,
    _ensure_seo_runtime_details as _ensure_seo_runtime_details,
    _normalize_action_handlers as _normalize_action_handlers,
)
from modstore_server.employee_ai_scaffold_part_2 import (  # noqa: E402
    _strip_json_fence as _strip_json_fence,
    parse_employee_pack_llm_json as parse_employee_pack_llm_json,
    _normalize_employee_config_v2_for_canvas as _normalize_employee_config_v2_for_canvas,
    _normalize_employee_system_prompt as _normalize_employee_system_prompt,
    _normalize_behavior_rules as _normalize_behavior_rules,
    _default_employee_config_v2 as _default_employee_config_v2,
    append_employee_stub_files_to_zip as append_employee_stub_files_to_zip,
    build_employee_pack_zip as build_employee_pack_zip,
    normalize_editor_manifest_for_registry as normalize_editor_manifest_for_registry,
)
