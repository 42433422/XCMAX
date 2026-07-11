"""任务拆解路由器：接收自然语言任务 → LLM 拆解子任务 → 匹配员工 → 输出 SubTask 列表。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from modstore_server.security_boundary import opaque_ref

logger = logging.getLogger(__name__)


@dataclass
class SubTask:
    employee_id: str
    task_brief: str
    input_data: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    priority: int = 5


def _load_all_employee_profiles() -> List[Dict[str, Any]]:
    """从 catalog 读取所有已注册员工包的 manifest 摘要（id / name / description / domain / skills）。"""
    try:
        import zipfile

        from modstore_server.models import CatalogItem, get_session_factory

        sf = get_session_factory()
        profiles: List[Dict[str, Any]] = []
        with sf() as session:
            rows = session.query(CatalogItem).filter(CatalogItem.artifact == "employee_pack").all()
            for row in rows:
                profile: Dict[str, Any] = {
                    "id": str(row.pkg_id or ""),
                    "name": str(row.name or ""),
                    "description": str(row.description or ""),
                }
                fn = (row.stored_filename or "").strip()
                if fn:
                    try:
                        from modstore_server.catalog_store import files_dir

                        p = files_dir() / fn
                        if p.exists():
                            with zipfile.ZipFile(p, "r") as z:
                                if "manifest.json" in z.namelist():
                                    mf = json.loads(z.read("manifest.json").decode("utf-8"))
                                    identity = mf.get("identity") or mf
                                    profile["domain"] = str(
                                        identity.get("domain") or identity.get("industry") or ""
                                    )
                                    profile["skills"] = [
                                        str(s.get("name") or s) if isinstance(s, dict) else str(s)
                                        for s in (identity.get("skills") or [])
                                    ]
                                    profile["scope_globs"] = list(
                                        (mf.get("workspace") or {}).get("scope_globs") or []
                                    )
                    except Exception:
                        pass
                profiles.append(profile)
        return profiles
    except Exception:
        logger.exception("task_router: failed to load employee profiles")
        return []


def _build_router_prompt(task_description: str, employees: List[Dict[str, Any]]) -> str:
    emp_list = json.dumps(
        [
            {
                "id": e["id"],
                "name": e["name"],
                "description": e.get("description", "")[:200],
                "domain": e.get("domain", ""),
                "skills": e.get("skills", []),
            }
            for e in employees
        ],
        ensure_ascii=False,
        indent=2,
    )
    return f"""你是一个任务编排专家。根据以下任务描述，将它拆解为若干子任务，并为每个子任务分配最合适的员工。

# 可用员工
{emp_list}

# 用户任务
{task_description}

# 输出格式（严格 JSON，数组）
返回 JSON 数组，每个元素格式：
{{
  "employee_id": "<员工ID，必须从上方员工列表中选>",
  "task_brief": "<简明任务描述，≤200字>",
  "input_data": {{}},
  "depends_on": ["<依赖的前序 employee_id，若无则 []>"],
  "priority": <1-10，1最高>
}}

注意：
- 只能使用 employee_id 来自上方列表的员工
- depends_on 填写前序任务所使用的 employee_id（并行任务填 []）
    - 输出纯 JSON，不加代码块标记"""


def _load_management_employee_profiles() -> List[Dict[str, Any]]:
    """只返回编制内且当前有可执行岗位包的管理端员工。

    公开商店 ``CatalogItem`` 不是管理编制 SSOT，不能作为老板任务的
    自动路由候选。这里同时检查包文件，避免把任务派给“名单上存在、
    运行时不存在”的岗位。
    """

    try:
        from modstore_server.catalog_store import files_dir
        from modstore_server.duty_employee_registry import duty_employee_records
        from modstore_server.duty_roster import all_planned_employee_ids
        from modstore_server.employee_runtime import (
            MANAGEMENT_PRIMARY_WORK_RESERVED_IDS,
            load_employee_pack,
            management_work_runtime_issues,
        )
        from modstore_server.models import get_session_factory

        records = duty_employee_records()
        planned = set(all_planned_employee_ids())
        package_root = files_dir()
        profiles: List[Dict[str, Any]] = []
        sf = get_session_factory()
        with sf() as session:
            for employee_id in sorted(planned.intersection(records)):
                if employee_id in MANAGEMENT_PRIMARY_WORK_RESERVED_IDS:
                    continue
                record = records.get(employee_id) or {}
                stored_filename = str(record.get("stored_filename") or "").strip()
                if not stored_filename or not (package_root / stored_filename).is_file():
                    continue
                try:
                    loaded_pack = load_employee_pack(session, employee_id)
                    runtime_issues = management_work_runtime_issues(loaded_pack)
                except Exception:
                    logger.warning(
                        "management router could not validate employee_ref=%s",
                        opaque_ref(employee_id, namespace="employee"),
                    )
                    continue
                if runtime_issues:
                    logger.info(
                        "management router excluded non-executable employee_ref=%s",
                        opaque_ref(employee_id, namespace="employee"),
                    )
                    continue
                profiles.append(
                    {
                        "id": employee_id,
                        "name": str(record.get("name") or employee_id),
                        "description": str(record.get("description") or ""),
                        "domain": str(record.get("yuangon_area") or record.get("industry") or ""),
                        "skills": [
                            str(value)
                            for value in (record.get("skills") or [])
                            if str(value).strip()
                        ],
                        "stored_filename": stored_filename,
                    }
                )
        return profiles
    except Exception:
        logger.exception("task_router: failed to load management employee profiles")
        return []


def _build_management_owner_prompt(
    task_description: str,
    input_data: Dict[str, Any],
    employees: List[Dict[str, Any]],
) -> str:
    candidates = json.dumps(
        [
            {
                "employee_id": row["id"],
                "name": row.get("name", ""),
                "domain": row.get("domain", ""),
                "description": str(row.get("description") or "")[:260],
                "skills": row.get("skills", []),
            }
            for row in employees
            if row.get("id") != "task-router-officer"
        ],
        ensure_ascii=False,
    )
    bounded_input = json.dumps(input_data or {}, ensure_ascii=False, default=str)[:8000]
    return f"""你是 XCAGI 管理端的任务路由员，只选择一名最适合真正执行任务的员工。
候选集是管理编制的完整白名单，不得输出候选集外的 ID，不得选 task-router-officer 自己执行。

# 管理端可执行员工
{candidates}

# 老板任务
{task_description[:12000]}

# 结构化输入
{bounded_input}

# 输出
只输出 JSON 数组，且只能有一项：
[{{"employee_id":"<候选 ID>","reason":"<为什么该岗位最匹配>"}}]
""".strip()


def resolve_management_work_owner(
    task_description: str,
    input_data: Dict[str, Any] | None = None,
    *,
    llm_provider: str = "auto",
    llm_model: str = "auto",
) -> Dict[str, Any]:
    """为统一管理任务台账选择一名真正执行人。

    先用代码所有权做可重复的确定性匹配；没有文件路径证据时，
    再让 LLM 从管理编制白名单中单选。任何不合法输出都会回退到
    安全可执行的 ``intent-analyst`` 并把原因写入路由审计。
    """

    profiles = _load_management_employee_profiles()
    by_id = {str(row.get("id") or ""): row for row in profiles}
    executable_ids = set(by_id)
    fallback = "intent-analyst"
    if fallback not in executable_ids:
        non_router_ids = sorted(executable_ids.difference({"task-router-officer"}))
        fallback = non_router_ids[0] if non_router_ids else ""

    base: Dict[str, Any] = {
        "employee_id": fallback,
        "strategy": "fallback",
        "reason": "无可用的精确路由证据，交由需求分析员先完成可验收的结构化处理",
        "candidates": sorted(executable_ids),
        "candidate_count": len(executable_ids),
        "fallback_reason": "",
    }
    if not fallback:
        base["fallback_reason"] = "no executable management employee package"
        return base

    payload = dict(input_data or {})
    payload.setdefault("description", task_description)
    try:
        from modstore_server.code_ownership import extract_incident_paths, resolve_code_owners

        paths = extract_incident_paths(payload)
        ownership = resolve_code_owners(paths, limit=max(8, len(executable_ids)))
        valid_owners = [
            row
            for row in (ownership.get("owners") or [])
            if str(row.get("employee_id") or "") in executable_ids
            and str(row.get("employee_id") or "") != "task-router-officer"
        ]
        valid_owners.sort(
            key=lambda row: (
                -int(row.get("match_score") or 0),
                -int(row.get("match_count") or 0),
                str(row.get("employee_id") or ""),
            )
        )
        if valid_owners:
            selected = valid_owners[0]
            employee_id = str(selected.get("employee_id") or "")
            return {
                **base,
                "employee_id": employee_id,
                "strategy": "code_ownership",
                "reason": (
                    f"路径所有权命中 {int(selected.get('match_count') or 0)} 个文件，"
                    f"匹配分 {int(selected.get('match_score') or 0)}"
                ),
                "matched_files": list(selected.get("matched_files") or []),
                "matched_globs": list(selected.get("matched_globs") or []),
            }
    except Exception as exc:
        logger.warning("management owner code-ownership routing failed: %s", exc)

    prompt = _build_management_owner_prompt(task_description, payload, profiles)
    raw = _call_llm(prompt, llm_provider=llm_provider, llm_model=llm_model)
    try:
        decoded = json.loads(raw)
        row = decoded[0] if isinstance(decoded, list) and decoded else None
        if not isinstance(row, dict):
            raise ValueError("router did not return one object")
        employee_id = str(row.get("employee_id") or "").strip()
        if employee_id == "task-router-officer" or employee_id not in executable_ids:
            raise ValueError(f"router returned non-management employee: {employee_id or 'empty'}")
        return {
            **base,
            "employee_id": employee_id,
            "strategy": "llm",
            "reason": str(row.get("reason") or "LLM 从管理编制白名单中选择")[:2000],
        }
    except Exception as exc:
        return {
            **base,
            "fallback_reason": str(exc)[:2000],
        }


def decompose_task(
    task_description: str,
    *,
    llm_provider: str = "auto",
    llm_model: str = "auto",
    max_subtasks: int = 8,
) -> List[SubTask]:
    """将自然语言任务拆解为 SubTask 列表。

    如果 LLM 调用失败，退回到单员工（daily-orchestrator）模式。
    """
    employees = _load_all_employee_profiles()
    if not employees:
        logger.warning("task_router: no employee profiles found, using fallback")
        return [
            SubTask(
                employee_id="daily-orchestrator",
                task_brief=task_description,
                input_data={},
                depends_on=[],
            )
        ]

    prompt = _build_router_prompt(task_description, employees)
    raw_json = _call_llm(prompt, llm_provider=llm_provider, llm_model=llm_model)

    subtasks: List[SubTask] = []
    try:
        items = json.loads(raw_json)
        if not isinstance(items, list):
            raise ValueError("expected JSON array")
        valid_ids = {e["id"] for e in employees}
        for item in items[:max_subtasks]:
            eid = str(item.get("employee_id") or "").strip()
            if not eid or eid not in valid_ids:
                logger.warning(
                    "task_router: unknown employee_ref=%s, skipping",
                    opaque_ref(eid, namespace="employee"),
                )
                continue
            subtasks.append(
                SubTask(
                    employee_id=eid,
                    task_brief=str(item.get("task_brief") or task_description)[:500],
                    input_data=item.get("input_data") or {},
                    depends_on=[
                        str(d) for d in (item.get("depends_on") or []) if str(d) in valid_ids
                    ],
                    priority=int(item.get("priority") or 5),
                )
            )
    except Exception:
        logger.warning(
            "task_router: LLM output parse failed output_ref=%s",
            opaque_ref(raw_json, namespace="router-output"),
        )

    if not subtasks:
        subtasks = [
            SubTask(
                employee_id="daily-orchestrator",
                task_brief=task_description,
                input_data={},
                depends_on=[],
            )
        ]

    return subtasks


def _call_llm(prompt: str, *, llm_provider: str, llm_model: str) -> str:
    """调用 LLM，返回原始文本（尽力提取 JSON 部分）。

    ``chat_dispatch_via_session`` 返回 dict，不是异步流；后台任务以平台身份
    调用，避免拆解任务扣到普通用户钱包或被用户配额挡住。
    """
    try:
        from modstore_server.models import get_session_factory
        from modstore_server.runtime_async import run_coro_sync
        from modstore_server.services.llm import (
            chat_dispatch_via_session,
            resolve_platform_bench_llm,
        )

        provider = (llm_provider or "").strip()
        model = (llm_model or "").strip()
        if provider in ("", "auto") or model in ("", "auto"):
            bench_provider, bench_model = resolve_platform_bench_llm()
            provider = bench_provider or provider
            model = bench_model or model
        if not provider or provider == "auto" or not model or model == "auto":
            logger.warning("task_router: 未配置平台 LLM，跳过拆解")
            return "[]"

        messages = [{"role": "user", "content": prompt}]

        async def _inner() -> str:
            sf = get_session_factory()
            with sf() as session:
                result = await chat_dispatch_via_session(
                    session,
                    0,
                    provider,
                    model,
                    messages,
                )
            if not isinstance(result, dict):
                return ""
            if not result.get("ok"):
                logger.warning(
                    "task_router: LLM call failed error_ref=%s",
                    opaque_ref(result.get("error"), namespace="router-error"),
                )
                return ""
            return str(result.get("content") or "")

        raw = run_coro_sync(_inner())
    except Exception:
        logger.warning("task_router LLM call failed")
        return "[]"

    # 提取 JSON 片段（模型可能输出 markdown 代码块）
    import re

    m = re.search(r"\[[\s\S]*\]", raw or "")
    return m.group(0) if m else (raw or "[]")


def route_and_dispatch(
    task_description: str,
    *,
    created_by_user_id: int = 0,
    llm_provider: str = "auto",
    llm_model: str = "auto",
    max_concurrency: int = 2,
    allow_high_risk_real_run: bool = False,
) -> Dict[str, Any]:
    """一步完成：拆解 → 路由 → 按拓扑执行。

    返回各子任务的执行结果列表。
    """
    subtasks = decompose_task(
        task_description,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    from modstore_server.employee_orchestrator import dispatch_subtasks

    return dispatch_subtasks(
        subtasks,
        created_by_user_id=created_by_user_id,
        max_concurrency=max_concurrency,
        allow_high_risk_real_run=allow_high_risk_real_run,
    )


__all__ = [
    "SubTask",
    "decompose_task",
    "resolve_management_work_owner",
    "route_and_dispatch",
]
