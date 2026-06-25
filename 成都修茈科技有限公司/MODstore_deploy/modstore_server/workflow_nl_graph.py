"""从自然语言生成工作流节点/边（LLM），落库后可选沙箱校验。"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.models import ESkill, ESkillVersion, User, Workflow, WorkflowEdge, WorkflowNode
from modstore_server.services.employee import get_default_employee_client
from modstore_server.services.llm import chat_dispatch_via_session
from modstore_server.workflow_engine import run_workflow_sandbox

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
    except Exception:
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
    except Exception:  # noqa: BLE001
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


def _default_static_logic(name: str, output_var: str = "result") -> Dict[str, Any]:
    return {
        "type": "template_transform",
        "template": f"{name}: " + "${value}",
        "dynamic_template": f"{name}: " + "${value}；补充信息：${details}",
        "fallback_template": f"{name}: " + "${value}",
        "output_var": output_var or "result",
        "metadata": {
            "repair_hints": ["补齐缺失输入后重试", "质量不足时追加 details 生成更完整结果"],
            "failure_modes": ["missing_field", "quality_below_threshold", "runtime_error"],
        },
    }


def _sanitize_static_logic(raw: Any, name: str, warnings: List[str]) -> Dict[str, Any]:
    logic = _safe_dict(raw)
    if not logic:
        return _default_static_logic(name)

    logic_type = str(logic.get("type") or "template_transform").strip()
    if logic_type not in {"template_transform", "pipeline", "employee_task"}:
        warnings.append(
            f"Skill {name!r} static_logic.type={logic_type!r} 不支持，已改为 template_transform"
        )
        return _default_static_logic(name, str(logic.get("output_var") or "result"))

    if logic_type == "template_transform":
        output_var = str(logic.get("output_var") or "result").strip() or "result"
        template = str(logic.get("template") or f"{name}: " + "${value}")
        sanitized = {
            "type": "template_transform",
            "template": template,
            "output_var": output_var,
        }
        required = logic.get("required_fields")
        if isinstance(required, list):
            sanitized["required_fields"] = [str(x) for x in required if str(x).strip()]
        domain_keywords = logic.get("domain_keywords")
        if isinstance(domain_keywords, list):
            sanitized["domain_keywords"] = [str(x) for x in domain_keywords if str(x).strip()]
        dynamic_template = logic.get("dynamic_template")
        if isinstance(dynamic_template, str) and dynamic_template.strip():
            sanitized["dynamic_template"] = dynamic_template
        fallback_template = logic.get("fallback_template")
        if isinstance(fallback_template, str) and fallback_template.strip():
            sanitized["fallback_template"] = fallback_template
        if "allow_steps" in logic:
            sanitized["allow_steps"] = _safe_bool(logic.get("allow_steps"), False)
        metadata = logic.get("metadata")
        if isinstance(metadata, dict):
            sanitized["metadata"] = metadata
        repair_hints = logic.get("repair_hints")
        if isinstance(repair_hints, list):
            sanitized.setdefault("metadata", {})["repair_hints"] = [
                str(x) for x in repair_hints if str(x).strip()
            ]
        failure_modes = logic.get("failure_modes")
        if isinstance(failure_modes, list):
            sanitized.setdefault("metadata", {})["failure_modes"] = [
                str(x) for x in failure_modes if str(x).strip()
            ]
        return sanitized

    if logic_type == "employee_task":
        employee_id = str(logic.get("employee_id") or "").strip()
        if not employee_id:
            warnings.append(
                f"Skill {name!r} 缺少 employee_id，employee_task 已降级为 template_transform"
            )
            return _default_static_logic(name, str(logic.get("output_var") or "result"))
        return {
            "type": "employee_task",
            "employee_id": employee_id,
            "task_template": str(logic.get("task_template") or logic.get("task") or name),
            "output_var": str(logic.get("output_var") or "employee_result"),
        }

    steps_in = logic.get("steps")
    if not isinstance(steps_in, list) or not steps_in:
        warnings.append(f"Skill {name!r} pipeline 缺少 steps，已改为 template_transform")
        return _default_static_logic(name, str(logic.get("output_var") or "result"))
    steps: List[Dict[str, Any]] = []
    for idx, step in enumerate(steps_in[:12]):
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("type") or "template_transform").strip()
        output_var = str(step.get("output_var") or step.get("id") or f"step_{idx}").strip()
        if step_type == "template_transform":
            steps.append(
                {
                    "id": str(step.get("id") or output_var),
                    "type": "template_transform",
                    "template": str(step.get("template") or "${value}"),
                    "output_var": output_var or f"step_{idx}",
                }
            )
        elif step_type == "set_value":
            steps.append(
                {
                    "id": str(step.get("id") or output_var),
                    "type": "set_value",
                    "value": step.get("value"),
                    "output_var": output_var or f"step_{idx}",
                }
            )
        elif step_type == "employee_task" and str(step.get("employee_id") or "").strip():
            steps.append(
                {
                    "id": str(step.get("id") or output_var),
                    "type": "employee_task",
                    "employee_id": str(step.get("employee_id") or "").strip(),
                    "task_template": str(step.get("task_template") or step.get("task") or name),
                    "output_var": output_var or f"step_{idx}",
                }
            )
        else:
            warnings.append(
                f"Skill {name!r} pipeline step #{idx} 类型 {step_type!r} 不可用，已跳过"
            )
    if not steps:
        return _default_static_logic(name, str(logic.get("output_var") or "result"))
    return {"type": "pipeline", "steps": steps}


def _normalize_skill_blueprints(data: Dict[str, Any], warnings: List[str]) -> List[Dict[str, Any]]:
    raw = data.get("skill_blueprints")
    if raw is None:
        raw = data.get("skills")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw[:_MAX_SKILL_BLUEPRINTS]):
        if not isinstance(item, dict):
            continue
        temp_id = _as_identifier(item.get("temp_skill_id") or item.get("id"), f"skill_{idx + 1}")
        if temp_id in seen:
            warnings.append(f"重复 temp_skill_id {temp_id!r}，已跳过")
            continue
        seen.add(temp_id)
        name = str(item.get("name") or temp_id).strip()[:128] or temp_id
        out.append(
            {
                "temp_skill_id": temp_id,
                "name": name,
                "domain": str(item.get("domain") or "").strip()[:2000],
                "description": str(item.get("description") or "").strip()[:4000],
                "static_logic": _sanitize_static_logic(item.get("static_logic"), name, warnings),
                "quality_gate": _safe_dict(item.get("quality_gate")),
                "trigger_policy": {
                    "on_error": True,
                    "on_quality_below_threshold": True,
                    **_safe_dict(item.get("trigger_policy")),
                },
            }
        )
    return out


def _create_generated_skills(
    db: Session,
    user: User,
    blueprints: List[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, int]:
    temp_to_skill: Dict[str, int] = {}
    for bp in blueprints:
        temp_id = str(bp.get("temp_skill_id") or "").strip()
        name = str(bp.get("name") or temp_id or "Generated Skill").strip()[:128]
        if not temp_id:
            continue
        existing = db.query(ESkill).filter(ESkill.user_id == user.id, ESkill.name == name).first()
        if existing:
            temp_to_skill[temp_id] = int(existing.id)
            warnings.append(f"Skill {name!r} 已存在，复用 skill_id={existing.id}")
            continue
        skill = ESkill(
            user_id=user.id,
            name=name,
            domain=str(bp.get("domain") or ""),
            description=str(bp.get("description") or ""),
            active_version=1,
        )
        db.add(skill)
        db.flush()
        version = ESkillVersion(
            eskill_id=skill.id,
            version=1,
            static_logic_json=_dumps(bp.get("static_logic") or _default_static_logic(name)),
            trigger_policy_json=_dumps(bp.get("trigger_policy") or {}),
            quality_gate_json=_dumps(bp.get("quality_gate") or {}),
            note="ai generated from workflow",
        )
        db.add(version)
        temp_to_skill[temp_id] = int(skill.id)
    return temp_to_skill


def _normalize_node(raw: Dict[str, Any], warnings: List[str]) -> Optional[Dict[str, Any]]:
    tid = str(raw.get("temp_id") or "").strip()
    nt = str(raw.get("node_type") or "").strip().lower()
    name = str(raw.get("name") or "").strip() or nt
    if not tid or nt not in _ALLOWED_TYPES:
        warnings.append(f"跳过非法节点: temp_id={tid!r} type={nt!r}")
        return None
    cfg = raw.get("config")
    if not isinstance(cfg, dict):
        cfg = {}
    if nt == "employee":
        eid = str(cfg.get("employee_id") or "").strip()
        task = str(cfg.get("task") or "").strip()
        if not eid:
            warnings.append(f"员工节点 {name!r} 缺少 employee_id，已用占位 placeholder")
            eid = "placeholder"
            cfg = {**cfg, "employee_id": eid}
        if not task:
            task = "根据工作流上下文完成用户描述中的任务"
            cfg = {**cfg, "task": task}
            warnings.append(f"员工节点 {name!r} 已补全默认 task")
    elif nt == "eskill":
        raw_skill_id = cfg.get("skill_id") or cfg.get("eskill_id")
        skill_id = str(raw_skill_id or "").strip()
        if skill_id:
            try:
                skill_id = str(int(skill_id))
            except (TypeError, ValueError):
                warnings.append(
                    f"ESkill 节点 {name!r} skill_id={skill_id!r} 不是数字，已清空并等待 temp_skill_id 映射"
                )
                skill_id = ""
        temp_skill_id = _as_identifier(
            cfg.get("temp_skill_id") or cfg.get("skill_ref") or cfg.get("temp_id"),
            "",
        )
        task = str(cfg.get("task") or "").strip()
        output_var = str(cfg.get("output_var") or "eskill_output").strip() or "eskill_output"
        input_mapping = cfg.get("input_mapping")
        if not isinstance(input_mapping, dict):
            input_mapping = {}
        normalized_cfg: Dict[str, Any] = {
            "task": task,
            "output_var": output_var,
            "input_mapping": input_mapping,
            "quality_gate": _safe_dict(cfg.get("quality_gate")),
            "trigger_policy": _safe_dict(cfg.get("trigger_policy")),
            "force_dynamic": _safe_bool(cfg.get("force_dynamic"), False),
            "solidify": _safe_bool(cfg.get("solidify"), True),
        }
        if skill_id:
            normalized_cfg["skill_id"] = skill_id
        if temp_skill_id:
            normalized_cfg["temp_skill_id"] = temp_skill_id
        if not skill_id and not temp_skill_id:
            warnings.append(f"ESkill 节点 {name!r} 缺少 skill_id/temp_skill_id")
        cfg = normalized_cfg
    elif nt == "condition":
        expr = str(cfg.get("expression") or "").strip()
        cfg = {"expression": expr} if expr else {}
    elif nt == "openapi_operation":
        try:
            cid = int(cfg.get("connector_id") or 0)
        except (TypeError, ValueError):
            cid = 0
        oid = str(cfg.get("operation_id") or "").strip()
        params = cfg.get("params")
        if not isinstance(params, dict):
            params = {}
        im = cfg.get("input_mapping")
        if isinstance(im, dict) and im:
            params = im
        out_var = str(cfg.get("output_var") or "api_result").strip() or "api_result"
        cfg = {
            "connector_id": cid,
            "operation_id": oid,
            "params": params,
            "input_mapping": params,
            "output_var": out_var,
        }
        if not cid:
            warnings.append(f"OpenAPI 节点 {name!r} 缺少有效 connector_id，已写 0，请在画布中修改")
        if not oid:
            warnings.append(f"OpenAPI 节点 {name!r} 缺少 operation_id，请在画布中补全")
    elif nt == "knowledge_search":
        query = str(cfg.get("query") or cfg.get("query_template") or "").strip()
        kb_id = str(cfg.get("kb_id") or "").strip()
        if not query and kb_id:
            query = f"知识库 {kb_id} 检索"
            warnings.append(f"知识检索节点 {name!r} 已根据 kb_id 生成占位 query")
        if not query:
            query = "根据上下文检索知识库"
            warnings.append(f"知识检索节点 {name!r} 已补全默认 query")
        try:
            top_k = int(cfg.get("top_k") or 5)
        except (TypeError, ValueError):
            top_k = 5
        output_var = str(cfg.get("output_var") or "kb_chunks").strip() or "kb_chunks"
        cids = cfg.get("collection_ids")
        if not isinstance(cids, list):
            cids = []
        cfg = {
            "query": query,
            "top_k": max(1, min(50, top_k)),
            "output_var": output_var,
            "collection_ids": cids,
        }
        if kb_id:
            cfg["kb_id"] = kb_id
    elif nt == "webhook_trigger":
        secret = str(cfg.get("secret") or "").strip()
        payload_var = str(cfg.get("payload_var") or "webhook_payload").strip() or "webhook_payload"
        cfg = {"secret": secret, "payload_var": payload_var}
    elif nt == "cron_trigger":
        cron = str(cfg.get("cron") or "0 * * * *").strip() or "0 * * * *"
        tz = str(cfg.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
        cfg = {"cron": cron, "timezone": tz}
    elif nt == "variable_set":
        vname = str(cfg.get("name") or "").strip()
        value = cfg.get("value", "")
        if value is not None and not isinstance(value, (dict, list)):
            value = str(value)
        if not vname:
            warnings.append(f"变量赋值节点 {name!r} 缺少 name，已用占位 _var")
            vname = "_var"
        cfg = {"name": vname, "value": value}
    elif nt in ("start", "end"):
        cfg = {}
    else:
        cfg = {}
    try:
        px = float(raw.get("position_x", 0))
        py = float(raw.get("position_y", 0))
    except (TypeError, ValueError):
        px, py = 0.0, 0.0
    return {
        "temp_id": tid,
        "node_type": nt,
        "name": name[:256],
        "config": cfg,
        "position_x": px,
        "position_y": py,
    }


def _detect_cycles_nl(nodes_in: List[Dict[str, Any]], edges_in: List[Dict[str, Any]]) -> List[str]:
    """基于 temp_id 的有向图环路检测（DFS 三色）。"""
    node_ids = {n["temp_id"] for n in nodes_in}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges_in:
        src = str(e.get("source_temp_id") or "").strip()
        tgt = str(e.get("target_temp_id") or "").strip()
        if src in adj and tgt in node_ids:
            adj[src].append(tgt)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in node_ids}
    cycles: List[str] = []

    def dfs(u: str, path: List[str]) -> None:
        color[u] = GRAY
        path.append(u)
        for v in adj.get(u, []):
            if v not in node_ids:
                continue
            vc = color.get(v, WHITE)
            if vc == GRAY:
                try:
                    idx = path.index(v)
                    cycles.append(" → ".join(path[idx:] + [v]))
                except ValueError:
                    cycles.append(f"cycle near {u!r} -> {v!r}")
            elif vc == WHITE:
                dfs(v, path)
        path.pop()
        color[u] = BLACK

    for nid in node_ids:
        if color.get(nid) == WHITE:
            dfs(nid, [])

    return cycles


def _unreachable_from_start_nl(
    nodes_in: List[Dict[str, Any]], edges_in: List[Dict[str, Any]]
) -> List[str]:
    """从 node_type=start 的节点出发 BFS，返回不可达的 temp_id。"""
    start_ids = [n["temp_id"] for n in nodes_in if n.get("node_type") == "start"]
    node_ids = {n["temp_id"] for n in nodes_in}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges_in:
        src = str(e.get("source_temp_id") or "").strip()
        tgt = str(e.get("target_temp_id") or "").strip()
        if src in adj and tgt in node_ids:
            adj[src].append(tgt)

    if not start_ids:
        return []

    visited: set[str] = set()
    q: deque[str] = deque(start_ids)
    while q:
        u = q.popleft()
        if u in visited:
            continue
        visited.add(u)
        for v in adj.get(u, []):
            if v not in visited:
                q.append(v)

    return [n["temp_id"] for n in nodes_in if n["temp_id"] not in visited]


async def apply_nl_workflow_graph(
    db: Session,
    user: User,
    *,
    workflow_id: int,
    brief: str,
    provider: Optional[str],
    model: Optional[str],
    target_employee_pack_id: Optional[str] = None,
    target_employee_label: Optional[str] = None,
    status_hook: Optional[Callable[[str], Any]] = None,
    preset_eskill_nodes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    为已存在且属于当前用户的工作流生成节点与边。
    成功: ok=True, nodes_created, edges_created, sandbox_ok, validation_errors, llm_warnings
    失败: ok=False, error=...

    preset_eskill_nodes: 可选，由 employee_skill_register 预先注册的真脚本 ESkill 列表，
        格式 [{eskill_id: int, name: str, output_var: str}, ...]。
        传入后会在 system prompt 追加约束让 LLM 串接这些节点，并在落库时强制补齐漏掉的节点。
    """
    wf = db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    if not wf:
        return {"ok": False, "error": "工作流不存在或无权访问"}

    from modstore_server.mod_scaffold_runner import resolve_llm_provider_model

    prov, mdl, err = resolve_llm_provider_model(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    employee_pack_id = str(target_employee_pack_id or "").strip()
    employee_label = str(target_employee_label or "").strip()
    employee_node_requirements = ""
    if employee_pack_id:
        label_hint = f"（显示名：{employee_label}）" if employee_label else ""
        employee_node_requirements = (
            "\n\n本次工作流属于新生成的可执行员工包，画布必须打通该员工包：\n"
            f'- 必须包含至少一个 node_type="employee" 节点，config.employee_id 必须精确填写 {employee_pack_id!r}{label_hint}。\n'
            "- employee 节点表示真实可执行员工包入口；业务前后处理仍可用 eskill 节点表达。\n"
            "- 推荐链路：start -> 若干 eskill/condition -> employee -> 若干 eskill/condition -> end。\n"
        )

    # ── preset_eskill_nodes 约束注入 ───────────────────────────────────────
    preset_nodes: List[Dict[str, Any]] = []
    preset_requirements = ""
    if preset_eskill_nodes:
        preset_nodes = [
            p
            for p in preset_eskill_nodes
            if isinstance(p, dict) and p.get("eskill_id") and p.get("name")
        ]
    if preset_nodes:
        lines = "\n".join(
            f"  {i+1}. skill_id={p['eskill_id']} name={p['name']!r} output_var={p.get('output_var', 'result')!r}"
            for i, p in enumerate(preset_nodes)
        )
        preset_requirements = (
            "\n\n【重要约束】本次员工工作流已预先生成了以下真实可执行 ESkill（Python 脚本），"
            "你必须在画布中按顺序串接它们：\n"
            f"{lines}\n"
            "规则：\n"
            '- 对每个预置 Skill，在 workflow.nodes 中生成一个 node_type="eskill" 节点，'
            "config.skill_id 填写对应数字，config.output_var 填写对应 output_var。\n"
            "- 这些节点已在数据库中，不需要在 skill_blueprints 中重复定义。\n"
            "- 可在这些节点前后增加 condition / variable_set / start / end，但不得删除任何预置节点。\n"
            "- 推荐链路：start -> eskill(1) -> eskill(2) -> … -> end。\n"
        )

    user_msg = (
        f"工作流名称: {wf.name}\n\n"
        f"工作流说明与需求:\n{brief.strip()}\n\n"
        f"{_eskill_catalog_lines(db, user)}\n\n"
        f"{_catalog_lines()}\n\n"
        f"{employee_node_requirements}"
        f"{preset_requirements}"
        "请先生成 skill_blueprints（仅新增不在上面「重要约束」中的 Skill），再生成 workflow.nodes 与 workflow.edges JSON。"
    )
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    if status_hook:
        try:
            maybe = status_hook(f"正在调用 {prov}/{mdl} 生成画布节点与边…")
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception:
            pass

    result = await chat_dispatch_via_session(
        db,
        user.id,
        prov,
        mdl,
        msgs,
        max_tokens=4096,
    )

    if status_hook:
        try:
            maybe = status_hook("解析模型响应、组装节点与边…")
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception:
            pass

    if not result.get("ok"):
        e = str(result.get("error") or "LLM 调用失败")
        if "missing api key" in e.lower():
            e = "该供应商未配置可用 API Key（平台或 BYOK）"
        return {"ok": False, "error": e}

    data = _extract_json_object(str(result.get("content") or ""))
    if not data:
        return {"ok": False, "error": "模型返回无法解析为 JSON 对象"}

    workflow_data = data.get("workflow") if isinstance(data.get("workflow"), dict) else data
    raw_nodes = workflow_data.get("nodes") if isinstance(workflow_data, dict) else None
    raw_edges = workflow_data.get("edges") if isinstance(workflow_data, dict) else None
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return {
            "ok": False,
            "error": "JSON 须包含 workflow.nodes/workflow.edges 或 nodes/edges 数组",
        }

    warnings: List[str] = []
    skill_blueprints = _normalize_skill_blueprints(data, warnings)
    nodes_in: List[Dict[str, Any]] = []
    seen_tid: set[str] = set()
    for i, rn in enumerate(raw_nodes):
        if not isinstance(rn, dict):
            continue
        if len(nodes_in) >= _MAX_NODES:
            warnings.append(f"节点超过 {_MAX_NODES} 个，已截断")
            break
        nn = _normalize_node(rn, warnings)
        if not nn:
            continue
        if nn["temp_id"] in seen_tid:
            warnings.append(f"重复 temp_id {nn['temp_id']!r}，已跳过后续")
            continue
        seen_tid.add(nn["temp_id"])
        nodes_in.append(nn)

    employee_pack_id = str(target_employee_pack_id or "").strip()
    if employee_pack_id:
        employee_nodes = [n for n in nodes_in if n["node_type"] == "employee"]
        if employee_nodes:
            first_cfg = dict(employee_nodes[0].get("config") or {})
            first_cfg["employee_id"] = employee_pack_id
            if target_employee_label and not str(employee_nodes[0].get("name") or "").strip():
                employee_nodes[0]["name"] = str(target_employee_label)[:120]
            if not str(first_cfg.get("task") or "").strip():
                first_cfg["task"] = str(brief or "根据工作流上下文完成员工任务")[:400]
            employee_nodes[0]["config"] = first_cfg
            for extra in employee_nodes[1:]:
                extra_cfg = dict(extra.get("config") or {})
                if not str(extra_cfg.get("employee_id") or "").strip():
                    extra_cfg["employee_id"] = employee_pack_id
                extra["config"] = extra_cfg
        else:
            nodes_in.append(
                {
                    "temp_id": "target_employee",
                    "node_type": "employee",
                    "name": str(target_employee_label or "执行员工")[:120],
                    "config": {
                        "employee_id": employee_pack_id,
                        "task": str(brief or "根据工作流上下文完成员工任务")[:400],
                    },
                    "position_x": 260.0,
                    "position_y": 120.0,
                }
            )
            warnings.append("模型未生成 employee 节点，已自动插入目标员工包节点")

    temp_to_row: Dict[str, Dict[str, Any]] = {n["temp_id"]: n for n in nodes_in}
    edges_in: List[Dict[str, Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        s = str(raw_edge.get("source_temp_id") or "").strip()
        t = str(raw_edge.get("target_temp_id") or "").strip()
        cond = str(raw_edge.get("condition") or "")
        if not s or not t or s not in temp_to_row or t not in temp_to_row:
            warnings.append(f"跳过无效边: {s!r} -> {t!r}")
            continue
        edges_in.append({"source_temp_id": s, "target_temp_id": t, "condition": cond})

    # ── 强制补齐漏掉的 preset eskill 节点 ────────────────────────────────
    if preset_nodes:
        existing_skill_ids = {
            str(
                n.get("config", {}).get("skill_id")
                or n.get("config", {}).get("temp_skill_id")
                or ""
            )
            for n in nodes_in
            if n.get("node_type") == "eskill"
        }
        missing_presets = [
            p
            for p in preset_nodes
            if str(p["eskill_id"]) not in existing_skill_ids
            and str(p.get("temp_skill_id") or "") not in existing_skill_ids
        ]
        if missing_presets:
            warnings.append(f"LLM 漏掉 {len(missing_presets)} 个预置 ESkill 节点，已自动插入")
            for idx_p, p in enumerate(missing_presets):
                tid = f"preset_eskill_{p['eskill_id']}"
                if tid in seen_tid:
                    continue
                seen_tid.add(tid)
                nodes_in.append(
                    {
                        "temp_id": tid,
                        "node_type": "eskill",
                        "name": str(p["name"])[:120],
                        "config": {
                            "skill_id": str(p["eskill_id"]),
                            "output_var": str(p.get("output_var") or "vibe_result"),
                            "task": str(p.get("name") or "")[:200],
                            "input_mapping": {},
                            "quality_gate": {},
                            "trigger_policy": {},
                            "force_dynamic": False,
                            "solidify": True,
                        },
                        "position_x": 260.0 + idx_p * 240.0,
                        "position_y": 240.0,
                    }
                )

        # 若有插入的 preset 节点，把它们串进 start → preset(s) → end 链
        temp_to_row = {n["temp_id"]: n for n in nodes_in}
        inserted_preset_tids = [
            f"preset_eskill_{p['eskill_id']}"
            for p in missing_presets
            if f"preset_eskill_{p['eskill_id']}" in seen_tid
        ]
        if inserted_preset_tids:
            start_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "start"), "")
            end_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "end"), "")
            if start_tid and end_tid:
                # 移除原先直连 start→end 的边
                edges_in = [
                    e
                    for e in edges_in
                    if not (e["source_temp_id"] == start_tid and e["target_temp_id"] == end_tid)
                ]
                chain = inserted_preset_tids
                prev = start_tid
                for tid in chain:
                    if not any(e["target_temp_id"] == tid for e in edges_in):
                        edges_in.append(
                            {"source_temp_id": prev, "target_temp_id": tid, "condition": ""}
                        )
                    prev = tid
                if not any(
                    e["source_temp_id"] == prev and e["target_temp_id"] == end_tid for e in edges_in
                ):
                    edges_in.append(
                        {"source_temp_id": prev, "target_temp_id": end_tid, "condition": ""}
                    )

    starts = [n for n in nodes_in if n["node_type"] == "start"]
    ends = [n for n in nodes_in if n["node_type"] == "end"]
    if len(starts) != 1 or len(ends) != 1:
        return {
            "ok": False,
            "error": f"图中须有且仅有一个 start 与一个 end（当前 start={len(starts)} end={len(ends)}）",
        }

    if employee_pack_id and any(n["temp_id"] == "target_employee" for n in nodes_in):
        start_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "start"), "")
        end_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "end"), "")
        if start_tid and end_tid:
            edges_in = [
                e
                for e in edges_in
                if not (e["source_temp_id"] == start_tid and e["target_temp_id"] == end_tid)
            ]
            if not any(e["target_temp_id"] == "target_employee" for e in edges_in):
                edges_in.append(
                    {
                        "source_temp_id": start_tid,
                        "target_temp_id": "target_employee",
                        "condition": "",
                    }
                )
            if not any(e["source_temp_id"] == "target_employee" for e in edges_in):
                edges_in.append(
                    {
                        "source_temp_id": "target_employee",
                        "target_temp_id": end_tid,
                        "condition": "",
                    }
                )

    if not edges_in:
        return {"ok": False, "error": "未生成任何有效边"}

    cycles = _detect_cycles_nl(nodes_in, edges_in)
    if cycles:
        warnings.append(f"检测到环路（示例）: {cycles[0][:240]}")

    unreachable = _unreachable_from_start_nl(nodes_in, edges_in)
    if unreachable:
        warnings.append(f"存在从 start 不可达的节点 temp_id（至多列 5 个）: {unreachable[:5]}")

    skill_refs = {
        str(n.get("config", {}).get("temp_skill_id") or "")
        for n in nodes_in
        if n.get("node_type") == "eskill" and str(n.get("config", {}).get("temp_skill_id") or "")
    }
    blueprint_refs = {str(bp.get("temp_skill_id") or "") for bp in skill_blueprints}
    preset_name_to_skill = {
        str(p.get("name") or "").strip(): str(p.get("eskill_id") or "").strip()
        for p in preset_nodes
        if str(p.get("name") or "").strip() and str(p.get("eskill_id") or "").strip()
    }
    preset_alias_refs: set[str] = set()
    if preset_nodes and len(preset_nodes) == 1:
        preset_alias_refs = set(skill_refs)
    if preset_name_to_skill or preset_alias_refs:
        sole_preset_skill_id = (
            str(preset_nodes[0].get("eskill_id") or "").strip()
            if preset_nodes and len(preset_nodes) == 1
            else ""
        )
        for n in nodes_in:
            if n.get("node_type") != "eskill":
                continue
            cfg = n.get("config") if isinstance(n.get("config"), dict) else {}
            temp_skill_id = str(cfg.get("temp_skill_id") or "")
            if temp_skill_id in blueprint_refs or str(cfg.get("skill_id") or "").strip():
                if temp_skill_id not in preset_alias_refs:
                    continue
            preset_skill_id = preset_name_to_skill.get(str(n.get("name") or "").strip()) or (
                sole_preset_skill_id if temp_skill_id in preset_alias_refs else ""
            )
            if preset_skill_id:
                cfg.pop("temp_skill_id", None)
                cfg["skill_id"] = preset_skill_id
                n["config"] = cfg
                skill_refs.discard(temp_skill_id)
        if preset_alias_refs:
            skill_blueprints = [
                bp
                for bp in skill_blueprints
                if str(bp.get("temp_skill_id") or "") not in preset_alias_refs
            ]
            blueprint_refs = {str(bp.get("temp_skill_id") or "") for bp in skill_blueprints}
    missing_refs = sorted(x for x in skill_refs if x and x not in blueprint_refs)
    if missing_refs:
        return {
            "ok": False,
            "error": f"ESkill 节点引用了不存在的 temp_skill_id: {', '.join(missing_refs)}",
        }

    if status_hook:
        try:
            maybe = status_hook("正在创建 AI 生成的 Skill…")
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception:
            pass

    # 落库：**必须先** `_create_generated_skills` 固化蓝图，再插入 WorkflowNode，确保 eskill 节点带数字 skill_id（Skill 组事实源）。
    id_map: Dict[str, int] = {}
    temp_to_skill: Dict[str, int] = {}
    try:
        temp_to_skill = _create_generated_skills(db, user, skill_blueprints, warnings)
        for n in nodes_in:
            cfg = dict(n["config"])
            if n["node_type"] == "eskill":
                temp_skill_id = str(cfg.pop("temp_skill_id", "") or "")
                if temp_skill_id and not str(cfg.get("skill_id") or "").strip():
                    skill_id = temp_to_skill.get(temp_skill_id)
                    if not skill_id:
                        raise ValueError(f"未能创建或映射 Skill: {temp_skill_id}")
                    cfg["skill_id"] = str(skill_id)
                if not str(cfg.get("skill_id") or "").strip():
                    raise ValueError(f"ESkill 节点 {n['name']!r} 缺少 skill_id")
            row = WorkflowNode(
                workflow_id=workflow_id,
                node_type=n["node_type"],
                name=n["name"],
                config=json.dumps(cfg, ensure_ascii=False),
                position_x=n["position_x"],
                position_y=n["position_y"],
            )
            db.add(row)
            db.flush()
            id_map[n["temp_id"]] = row.id

        for e in edges_in:
            sid = id_map.get(e["source_temp_id"])
            tid = id_map.get(e["target_temp_id"])
            if not sid or not tid:
                continue
            db.add(
                WorkflowEdge(
                    workflow_id=workflow_id,
                    source_node_id=sid,
                    target_node_id=tid,
                    condition=e["condition"] or "",
                )
            )
        db.commit()
    except Exception as ex:
        db.rollback()
        return {"ok": False, "error": f"写入节点/边失败: {ex}"}

    report = run_workflow_sandbox(
        workflow_id,
        {},
        mock_employees=True,
        validate_only=True,
    )
    errs = [str(x) for x in (report.get("errors") or [])]
    val_ok = bool(report.get("ok"))
    return {
        "ok": True,
        "nodes_created": len(nodes_in),
        "edges_created": len(edges_in),
        "sandbox_ok": val_ok,
        "validation_errors": errs,
        "llm_warnings": warnings,
        "skills_created": len(temp_to_skill),
        "skill_ids": temp_to_skill,
    }
