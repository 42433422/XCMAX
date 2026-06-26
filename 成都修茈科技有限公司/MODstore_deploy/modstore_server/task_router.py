"""任务拆解路由器：接收自然语言任务 → LLM 拆解子任务 → 匹配员工 → 输出 SubTask 列表。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
        import io
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
                logger.warning("task_router: unknown employee_id=%s, skipping", eid)
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
    except Exception as exc:
        logger.warning("task_router: LLM output parse failed: %s\nraw=%s", exc, raw_json[:500])

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
            logger.warning(
                "task_router: 未配置平台 LLM（provider=%s model=%s），跳过拆解",
                provider or "",
                model or "",
            )
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
                    "task_router: LLM 调用未成功：%s",
                    str(result.get("error") or "")[:200],
                )
                return ""
            return str(result.get("content") or "")

        raw = run_coro_sync(_inner())
    except Exception as exc:
        logger.warning("task_router LLM call failed: %s", exc)
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


__all__ = ["SubTask", "decompose_task", "route_and_dispatch"]
