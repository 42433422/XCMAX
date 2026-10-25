"""从每日摘要 + 编制员工生成 Vibe-Coding 预备 Markdown（更新清单 + 补丁清单）。"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from modstore_server import digest_vibe_collect as _collect
from modstore_server import digest_vibe_synthesis as _synthesis
from modstore_server import digest_vibe_templates as _templates
from modstore_server.all_hands_report import (
    _load_yuangon_employee_meta as _load_yuangon_employee_meta,
)
from modstore_server.all_hands_report import _manifest_signals as _manifest_signals
from modstore_server.all_hands_report import _recent_failures as _recent_failures
from modstore_server.all_hands_report import _report_one_employee as _report_one_employee
from modstore_server.all_hands_report import _resolve_employee_pairs as _resolve_employee_pairs
from modstore_server.all_hands_report import (
    clamp_all_hands_max_employees as clamp_all_hands_max_employees,
)
from modstore_server.duty_roster import yuangon_area_for_pkg as yuangon_area_for_pkg
from modstore_server.services.llm import resolve_platform_bench_llm as resolve_platform_bench_llm

logger = logging.getLogger(__name__)

DigestVibeProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]

_VIBE_PREP_SYSTEM = """你是 MODstore 的 Vibe-Coding 编排秘书。
根据输入的「每日摘要节选」与「各 AI 员工岗位快照」，生成两份 Markdown，供后续 vibe-coding 自动改码使用。

硬性要求：
1. 仅基于输入事实归纳；不得编造不存在的文件、错误、或已完成的改动。
2. 输出必须是合法 JSON 对象，且只含两个键：
   - ``updates_markdown``：更新清单（文档同步、配置、监控、流程、依赖升级、测试补齐等非紧急维护）
   - ``patches_markdown``：补丁清单（需改代码/修 bug/补迁移/修测试失败的具体任务）
3. 两份 Markdown 各自以一级标题开头：
   - updates 首行必须是 ``# Vibe 预备 · 更新清单``
   - patches 首行必须是 ``# Vibe 预备 · 补丁清单``
4. 按员工 ``employee_id`` 分节（``## [employee_id] 显示名 · v{pack_version}``），每节含：
   - 职责一句
   - 员工包版本 ``pack_version``（来自 snapshot）
   - 建议 scope 路径（来自 snapshot）
   - 3–5 条可执行条目；**每条都必须以 `**P0**` / `**P1**` / `**P2**` 优先级前缀开头**，并按风险分级、**避免整节同一优先级**：
     · P0 = 影响线上/安全/认证，或该岗有近期失败需立即处理；
     · P1 = 契约/联调/集成漂移、重要重构或测试缺口；
     · P2 = 纯文档/README/runbook 补齐、低风险维护。
     （updates 偏维护，patches 偏 diff/修复；两份清单都要体现优先级梯度）
5. 简体中文；不要输出 JSON 以外的任何文字。
6. 版本号由服务端统一写入文首，你无需重复输出版本表。
7. 「进化事实信号」段落（pytest 失败 / incident / 性能探针）优先级高于三端截图分析；补丁清单须优先覆盖这些事实。"""

resolve_vibe_prep_version_context = _templates.resolve_vibe_prep_version_context
_version_header_block = _templates._version_header_block
_apply_version_stamp = _templates._apply_version_stamp
_include_meta_maintenance_updates = _templates._include_meta_maintenance_updates
_include_surface_hint_tasks = _templates._include_surface_hint_tasks
_is_actionable_failure = _templates._is_actionable_failure
_short_task_reason = _templates._short_task_reason
_employee_pack_version = _templates._employee_pack_version
_build_template_vibe_markdowns = _templates._build_template_vibe_markdowns

_finalize_vibe_result = _collect._finalize_vibe_result
_merge_event_backlog_into_patches = _collect._merge_event_backlog_into_patches
_strip_html_to_text = _collect._strip_html_to_text
_lightweight_employee_snapshot = _collect._lightweight_employee_snapshot
_collect_lightweight = _collect._collect_lightweight
_collect_manual_reports = _collect._collect_manual_reports
persist_vibe_prep_on_digest_record = _collect.persist_vibe_prep_on_digest_record
run_digest_vibe_prep_sync = _collect.run_digest_vibe_prep_sync

_build_llm_user_content = _synthesis._build_llm_user_content
_synthesize_vibe_markdowns = _synthesis._synthesize_vibe_markdowns
build_digest_vibe_prep = _synthesis.build_digest_vibe_prep
