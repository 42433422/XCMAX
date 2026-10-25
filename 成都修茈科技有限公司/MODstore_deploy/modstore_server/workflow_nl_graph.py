# mypy: disable-error-code="arg-type"
# isort: skip_file
"""从自然语言生成工作流节点/边（LLM），落库后可选沙箱校验。"""

from __future__ import annotations

from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

import json
import re
from collections import deque as deque
from typing import Any, Callable as Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.models import (
    ESkill,
    ESkillVersion,
    User,
    Workflow as Workflow,
    WorkflowEdge as WorkflowEdge,
    WorkflowNode as WorkflowNode,
)
from modstore_server.services.employee import get_default_employee_client
from modstore_server.services.llm import (
    chat_dispatch_via_session as chat_dispatch_via_session,
)
from modstore_server.workflow_engine import run_workflow_sandbox as run_workflow_sandbox

_MAX_NODES = 20
_MAX_SKILL_BLUEPRINTS = 12
_ALLOWED_TYPES = frozenset(
    {
        "start",
        "end",
        "employee",
        "eskill",
        "condition",
        "openapi_operation",
        "knowledge_search",
        "webhook_trigger",
        "cron_trigger",
        "variable_set",
    }
)


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = _strip_json_fence(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试从文本中抠出第一个 { ... } 块
        i = raw.find("{")
        j = raw.rfind("}")
        if i < 0 or j <= i:
            return None
        try:
            data = json.loads(raw[i : j + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


SYSTEM_PROMPT = """你是 XCAGI Skill 生成与工作流组合器。用户用自然语言描述业务流程，你输出**仅一个 JSON 对象**（不要 markdown 围栏、不要解释）。

JSON 结构：
{
  "skill_blueprints": [
    {
      "temp_skill_id": "字符串，在 skill_blueprints 内唯一，如 skill_parse_input",
      "name": "Skill 名称",
      "domain": "此 Skill 的业务边界",
      "description": "能力说明",
      "static_logic": {
        "type": "template_transform",
        "template": "处理 ${value}",
        "dynamic_template": "处理 ${value}；异常原因：${details}",
        "fallback_template": "兜底处理 ${value}",
        "required_fields": ["value"],
        "domain_keywords": ["业务关键词"],
        "output_var": "result",
        "metadata": {
          "repair_hints": ["缺字段时先补默认值", "质量不足时扩展输出说明"],
          "failure_modes": ["missing_field", "quality_below_threshold"]
        }
      },
      "quality_gate": {},
      "trigger_policy": { "on_error": true, "on_quality_below_threshold": true }
    }
  ],
  "workflow": {
    "nodes": [
      {
        "temp_id": "字符串，在 nodes 内唯一",
        "node_type": "start" | "end" | "eskill" | "condition"
          | "employee" | "openapi_operation" | "knowledge_search"
          | "webhook_trigger" | "cron_trigger" | "variable_set",
        "name": "节点显示名",
        "config": { },
        "position_x": 0,
        "position_y": 0
      }
    ],
    "edges": [
      {
        "source_temp_id": "…",
        "target_temp_id": "…",
        "condition": "可选，Python 表达式字符串；无条件则空字符串"
      }
    ]
  }
}

兼容旧结构时也可直接输出：
{
  "nodes": [
    {
      "temp_id": "字符串，在 nodes 内唯一",
      "node_type": "start" | "end" | "eskill" | "condition" | "employee"
        | "openapi_operation" | "knowledge_search"
        | "webhook_trigger" | "cron_trigger" | "variable_set",
      "name": "节点显示名",
      "config": { },
      "position_x": 0,
      "position_y": 0
    }
  ],
  "edges": [
    {
      "source_temp_id": "…",
      "target_temp_id": "…",
      "condition": "可选，Python 表达式字符串；无条件则空字符串"
    }
  ]
}

规则：
1. 必须有且仅有 **一个** node_type 为 start 的节点，config 为 {}。
2. 必须有且仅有 **一个** node_type 为 end 的节点，config 为 {}。
3. 节点总数不超过 20。
4. 业务能力必须优先表达为 Skill：若「可用 ESkill 目录」已有合适能力，eskill 节点 config 填 "skill_id"；若缺失能力，先在 skill_blueprints 中定义新 Skill，再让 eskill 节点 config 填 "temp_skill_id"。
5. eskill 节点 config 可包含：
   - "skill_id": 整数或数字字符串，引用已有 ESkill。
   - "temp_skill_id": 字符串，引用本次 skill_blueprints 中的临时 Skill。
   - "task": 字符串，可覆盖 Skill 任务描述。
   - "input_mapping": 对象，把工作流上下文映射为 Skill 输入。
   - "output_var": 字符串，默认 eskill_output。
   - "quality_gate": 对象，例如 {"required_keys":["result"]} 或 {"min_length": 20}。
   - "trigger_policy": 对象，例如 {"on_error": true, "on_quality_below_threshold": true}。
   - "force_dynamic": 布尔值；默认 false。
   - "solidify": 布尔值；默认 true。
6. skill_blueprints[].static_logic 必须使用安全结构，优先 "template_transform"；可用类型为 "template_transform"、"pipeline"、"employee_task"。没有明确外部员工时不要使用 employee_task。为了后续自修复，尽量补充 required_fields、domain_keywords、dynamic_template、fallback_template、metadata.repair_hints、metadata.failure_modes。
7. employee 节点仅用于兼容旧工作流，不作为首选业务能力节点；其 config 必须包含：
   - "employee_id": 字符串，**优先**从下方「可用员工目录」中选 id；若无合适项可填目录中第一条或合理占位并在 name 中说明。
   - "task": 字符串，对员工的具体任务说明（一句即可）。
8. condition 节点可在 config 中包含 "expression": 字符串（展示用）；出边分支仍用 edges[].condition。
9. openapi_operation：config 含 "connector_id"(整数)、"operation_id"(字符串)、"params"(对象，可为空)、可选 "output_var"(默认 api_result)。
10. knowledge_search：config 含 "query"(字符串，可用 {{ var }})、可选 "kb_id"、可选 "top_k"(整数)、可选 "output_var"(默认 kb_chunks)、可选 "collection_ids"(整数数组)。
11. webhook_trigger：config 可选 "secret"、可选 "payload_var"(默认 webhook_payload)。须从 start 经边可达（通常 start -> … -> webhook 或 webhook 接在 start 后）。
12. cron_trigger：config 含 "cron"(cron 表达式字符串)、可选 "timezone"(如 Asia/Shanghai)。
13. variable_set：config 含 "name"(变量名)、"value"(字符串，可用 {{ var }} 模板)。
14. edges 构成从 start 经若干节点到 end 的**有向可达**路径；避免悬空节点。
15. position_x / position_y 为横向/纵向布局坐标，建议每层间隔 220（x）与 120（y）。

只输出 JSON，不要其它文字。"""


def _catalog_lines(max_items: int = 40) -> str:
    try:
        rows = get_default_employee_client().list_employees() or []
    except RECOVERABLE_ERRORS:
        rows = []
    lines: List[str] = []
    for r in rows[:max_items]:
        if not isinstance(r, dict):
            continue
        eid = str(r.get("id") or "").strip()
        name = str(r.get("name") or "").strip()
        if eid:
            lines.append(f"- id={eid!r} name={name!r}")
    if not lines:
        return "（当前目录无已上架员工包；employee 节点可填占位 employee_id，用户稍后在画布修改。）"
    return "可用员工目录（employee_id 须与下列 id 一致）：\n" + "\n".join(lines)


def _loads_dict(raw: str | None) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except BOUNDARY_ERRORS:  # noqa: BLE001
        return {}


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return bool(value)


def _as_identifier(value: Any, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw or fallback


def _eskill_catalog_lines(db: Session, user: User, max_items: int = 40) -> str:
    rows = (
        db.query(ESkill)
        .filter(ESkill.user_id == user.id)
        .order_by(ESkill.updated_at.desc())
        .limit(max_items)
        .all()
    )
    if not rows:
        return "可用 ESkill 目录：当前用户暂无 ESkill；缺失能力必须输出 skill_blueprints。"

    active_versions = {
        (v.eskill_id, v.version): v
        for v in db.query(ESkillVersion)
        .filter(ESkillVersion.eskill_id.in_([s.id for s in rows] or [0]))
        .all()
    }
    lines: List[str] = []
    for skill in rows:
        version = active_versions.get((skill.id, skill.active_version))
        logic = _loads_dict(version.static_logic_json if version else None)
        output_var = str(logic.get("output_var") or "eskill_output")
        logic_type = str(logic.get("type") or "template_transform")
        lines.append(
            "- id={id} name={name!r} domain={domain!r} logic_type={logic_type!r} output_var={output_var!r}".format(
                id=skill.id,
                name=skill.name,
                domain=(skill.domain or "")[:120],
                logic_type=logic_type,
                output_var=output_var,
            )
        )
    return "可用 ESkill 目录（优先复用 skill_id，缺失能力才输出 skill_blueprints）：\n" + "\n".join(
        lines
    )


from modstore_server.workflow_nl_operations import (  # noqa: E402
    _create_generated_skills as _create_generated_skills,
    _default_static_logic as _default_static_logic,
    _detect_cycles_nl as _detect_cycles_nl,
    _normalize_node as _normalize_node,
    _normalize_skill_blueprints as _normalize_skill_blueprints,
    _sanitize_static_logic as _sanitize_static_logic,
    _unreachable_from_start_nl as _unreachable_from_start_nl,
)
from modstore_server.workflow_nl_apply import (  # noqa: E402
    apply_nl_workflow_graph as apply_nl_workflow_graph,
)
