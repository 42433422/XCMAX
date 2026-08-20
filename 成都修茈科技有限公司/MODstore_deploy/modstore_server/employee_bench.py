# isort: skip_file
# ruff: noqa: E402, F401
"""员工上架前的基准测试：LLM 生成 1-5 级任务 → 执行 → 量化打分 → 五维审核 →（可选）员工包质询。

公开接口
--------
generate_bench_tasks(brief, panel_summary, db, user_id, provider, model, *, use_platform_dispatch, strict)
    -> List[{level, tasks:[{id, task_desc}]}]

run_and_score_bench(employee_id, task_list, db, user, *, bench_llm_override, per_dimension_ids)
    -> {tasks_result, level_scores, overall_score, audit, passed, reviewer_selection, ...}
    可选环境变量 ``MODSTORE_PACK_PEER_REVIEW_EMPLOYEE``：五维之后在 ``audit.pack_peer_review`` 中附加 LLM 质询分。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modstore_server.models import User

logger = logging.getLogger(__name__)

# ── 权重：越低难度级别权重越高 ──────────────────────────────────────────
_LEVEL_WEIGHTS = {1: 3.0, 2: 2.5, 3: 2.0, 4: 1.5, 5: 1.0}

# ── 效率因子基准（tokens，超过则 efficiency < 1）─────────────────────────
_EFFICIENT_TOKEN_THRESHOLD = 500

# ── 通过标准 ─────────────────────────────────────────────────────────────
_PASS_OVERALL_SCORE = 60.0
_PASS_AUDIT_SCORE = True  # audit.summary.pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 生成测试任务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TASK_GEN_SYSTEM = """\
你是一位严格的 AI 员工考官。根据员工功能描述，为该员工设计一套分级测试任务（共 5 级，每级 3 个任务）。

任务难度递增：
- 1 级：极简验证，单步操作，无歧义输入
- 2 级：基础功能，正常业务场景
- 3 级：中等复杂度，含边界条件
- 4 级：多步骤、需要判断的场景
- 5 级：压力/异常/综合场景

输出**仅**一个合法 JSON 数组（无注释、无 markdown 围栏）：
[
  {
    "level": 1,
    "tasks": [
      {"id": "1-1", "task_desc": "具体任务指令，30字以内"},
      {"id": "1-2", "task_desc": "..."},
      {"id": "1-3", "task_desc": "..."}
    ]
  },
  ... (level 2 to 5)
]
"""


from modstore_server.employee_bench_part01 import (
    _strip_fence as _strip_fence,
    _parse_task_list as _parse_task_list,
    _fallback_tasks as _fallback_tasks,
    generate_bench_tasks as generate_bench_tasks,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 执行 + 量化打分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_RUBRIC_SYSTEM = """\
你是 AI 员工基准测试的量化评分裁判。根据每条任务的「任务描述」与「执行输出摘要」，\
给出 0–100 的符合度分数（integer 或 float）。
规则：
- 只根据摘要判断是否回应了任务；若摘要显示报错、空输出或与任务无关，给低分（0–35）。
- 执行标记 execution_ok=false 时，分数通常不超过 40，除非摘要显示仍有有效部分。
输出**仅**一个合法 JSON 数组（无 markdown 围栏），每个元素：
{"task_id": "<与输入一致>", "score": <0-100>, "note": "<一句中文理由>"}
必须覆盖输入中的每一个 task_id，不得遗漏。"""


from modstore_server.employee_bench_part02 import (
    _derive_bench_execution_ok as _derive_bench_execution_ok,
    _extract_output_preview as _extract_output_preview,
    _parse_rubric_scores as _parse_rubric_scores,
    _align_rubric_keys as _align_rubric_keys,
    _llm_rubric_scores_platform as _llm_rubric_scores_platform,
    _level_scores_from_entries as _level_scores_from_entries,
    _efficiency_factor as _efficiency_factor,
    _run_single_task as _run_single_task,
    _score_level as _score_level,
    _weighted_overall as _weighted_overall,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 五维审核
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 支持的五个维度键（与 package_sandbox_audit 返回结构一致）
AUDIT_DIMENSIONS = (
    "manifest_compliance",
    "declaration_completeness",
    "api_testability_static",
    "security_and_size",
    "metadata_quality",
)

_DIM_LABELS_ZH: Dict[str, str] = {
    "manifest_compliance": "清单 / manifest 结构与 artifact 合规",
    "declaration_completeness": "声明完整度（workflow_employees、字段齐全）",
    "api_testability_static": "API / 路由静态可测性",
    "security_and_size": "包体大小与安全扫描",
    "metadata_quality": "元数据质量（名称、描述、行业等）",
}

_MAX_REVIEWER_CANDIDATES = 48

_MACHINE_SCORE_LINE = re.compile(r"^MACHINE_SCORE\s*=\s*(\d{1,3})\s*$", re.MULTILINE)


from modstore_server.employee_bench_part03 import (
    _parse_machine_score_from_text as _parse_machine_score_from_text,
    _peer_review_gate_enabled as _peer_review_gate_enabled,
    _peer_review_min_score as _peer_review_min_score,
    _run_pack_peer_review_optional as _run_pack_peer_review_optional,
    _read_employee_brief as _read_employee_brief,
    _collect_reviewer_candidate_ids as _collect_reviewer_candidate_ids,
    _snapshot_reviewer_candidate as _snapshot_reviewer_candidate,
    _dimensions_still_open as _dimensions_still_open,
    _llm_assign_reviewers_to_dimensions as _llm_assign_reviewers_to_dimensions,
    _parse_router_json as _parse_router_json,
    resolve_auto_dimension_reviewers as resolve_auto_dimension_reviewers,
    _load_audit_dimension_env_defaults as _load_audit_dimension_env_defaults,
    _audit_single_pack as _audit_single_pack,
    _run_five_dim_audit as _run_five_dim_audit,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 公开入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


from modstore_server.employee_bench_part04 import (
    run_and_score_bench as run_and_score_bench,
)
