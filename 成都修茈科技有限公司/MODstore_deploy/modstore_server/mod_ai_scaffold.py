# mypy: disable-error-code="arg-type, dict-item, index, union-attr"
"""LLM 生成可导入 Mod 脚手架（manifest + skeleton 文件），经 import_zip 落库。"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from modman.manifest_util import validate_manifest_dict
from modman.scaffold import template_dir
from modstore_server.mod_ai_manifest import extract_json_text as _extract_json_text
from modstore_server.mod_ai_manifest import normalize_mod_id as normalize_mod_id
from modstore_server.mod_ai_manifest import parse_llm_manifest_json as parse_llm_manifest_json
from modstore_server.mod_ai_manifest import strip_json_fence as _strip_json_fence

__all__ = ["_strip_json_fence", "normalize_mod_id", "parse_llm_manifest_json"]


SYSTEM_PROMPT = """你是 XCAGI Mod 清单生成器。用户会用自然语言描述想要的扩展 Mod。
你必须只输出一个 JSON 对象（不要 markdown 围栏、不要解释文字），字段如下：
- id: 字符串，小写英文/数字/点/下划线/连字符，以字母或数字开头，建议 2–48 字符
- name: 简短中文或英文显示名
- version: 语义化版本，默认 "1.0.0"
- description: 一句话介绍
- workflow_employees: 可选数组；每项为对象，含 id、label、panel_title、panel_summary（均可选但 id 与 label 至少其一非空）

示例：
{"id":"demo-helper","name":"演示助手","version":"1.0.0","description":"示例 Mod","workflow_employees":[{"id":"helper-1","label":"助手","panel_title":"助手","panel_summary":"占位说明"}]}
"""


from modstore_server.mod_ai_scaffold_part01 import _sub_template as _sub_template
from modstore_server.mod_ai_scaffold_part01 import build_scaffold_zip as build_scaffold_zip

# --- Mod suite / 专业版脚手架（与 ``mod_scaffold_runner`` 对齐的最小实现）---

SYSTEM_PROMPT_SUITE = (
    SYSTEM_PROMPT
    + "\n\n此外请输出 Mod 蓝图 JSON：包含 manifest（对象）、employees（数组）、blueprint（对象）。"
)

# 传统模式侧栏基线（与修复器约定的 industry / ui_shell 合并后总项数 ≥ 18）
_DEFAULT_TRADITIONAL_SIDEBAR: List[Dict[str, Any]] = [
    {
        "key": "dashboard",
        "label": "工作台",
        "path": "/dashboard",
        "order": 10,
        "visible": True,
    },
    {
        "key": "briefing",
        "label": "今日简报",
        "path": "/briefing",
        "order": 15,
        "visible": True,
    },
    {
        "key": "inbox",
        "label": "消息中心",
        "path": "/inbox",
        "order": 18,
        "visible": True,
    },
    {"key": "tasks", "label": "任务", "path": "/tasks", "order": 22, "visible": True},
    {
        "key": "calendar",
        "label": "日程",
        "path": "/calendar",
        "order": 26,
        "visible": True,
    },
    {
        "key": "customers",
        "label": "客户",
        "path": "/customers",
        "order": 30,
        "visible": True,
    },
    {
        "key": "products",
        "label": "物料/产品",
        "path": "/products",
        "order": 34,
        "visible": True,
    },
    {"key": "orders", "label": "订单", "path": "/orders", "order": 38, "visible": True},
    {
        "key": "shipments",
        "label": "发货",
        "path": "/shipments",
        "order": 42,
        "visible": True,
    },
    {
        "key": "inventory",
        "label": "库存",
        "path": "/inventory",
        "order": 46,
        "visible": True,
    },
    {
        "key": "warehouse",
        "label": "仓储",
        "path": "/warehouse",
        "order": 50,
        "visible": True,
    },
    {
        "key": "purchases",
        "label": "采购",
        "path": "/purchases",
        "order": 54,
        "visible": True,
    },
    {
        "key": "finance",
        "label": "财务",
        "path": "/finance",
        "order": 58,
        "visible": True,
    },
    {
        "key": "reports",
        "label": "报表",
        "path": "/reports",
        "order": 62,
        "visible": True,
    },
    {
        "key": "analytics",
        "label": "分析",
        "path": "/analytics",
        "order": 66,
        "visible": True,
    },
    {
        "key": "knowledge",
        "label": "知识库",
        "path": "/knowledge",
        "order": 70,
        "visible": True,
    },
    {
        "key": "workflows",
        "label": "工作流",
        "path": "/workflows",
        "order": 74,
        "visible": True,
    },
    {
        "key": "settings",
        "label": "设置",
        "path": "/settings",
        "order": 90,
        "visible": True,
    },
]


from modstore_server.mod_ai_scaffold_part02 import (
    _ensure_suite_manifest_fields as _ensure_suite_manifest_fields,
)
from modstore_server.mod_ai_scaffold_part02 import (
    _menu_overrides_from_sidebar as _menu_overrides_from_sidebar,
)
from modstore_server.mod_ai_scaffold_part02 import (
    _merge_traditional_sidebar as _merge_traditional_sidebar,
)
from modstore_server.mod_ai_scaffold_part02 import (
    _normalize_frontend_app as _normalize_frontend_app,
)
from modstore_server.mod_ai_scaffold_part02 import (
    _normalize_frontend_menu as _normalize_frontend_menu,
)
from modstore_server.mod_ai_scaffold_part02 import _sanitize_industry as _sanitize_industry
from modstore_server.mod_ai_scaffold_part02 import (
    merge_employees_for_blueprint_routes as merge_employees_for_blueprint_routes,
)
from modstore_server.mod_ai_scaffold_part02 import (
    parse_llm_mod_suite_json as parse_llm_mod_suite_json,
)
from modstore_server.mod_ai_scaffold_part02 import (
    render_frontend_routes_js as render_frontend_routes_js,
)
from modstore_server.mod_ai_scaffold_part02 import (
    render_generated_home_vue as render_generated_home_vue,
)
from modstore_server.mod_ai_scaffold_part02 import (
    render_suite_blueprints_py as render_suite_blueprints_py,
)
