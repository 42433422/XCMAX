"""Model price comparisons, VLM routing and local billing projections."""

from __future__ import annotations

import os

from .employee_tool_ports import ModelCatalog, Payload
from .results import _err, _ok


async def compare_model_prices(ports: ModelCatalog, params: Payload, ctx: Payload) -> Payload:
    """对比各 LLM 模型价格（内置价格表，覆盖 10 家 provider）。

    支持按 provider 过滤，按价格排序。标注免费模型。
    """
    provider_filter = str(params.get("provider") or "").strip().lower()
    sort_by = str(params.get("sort_by") or "output").strip().lower()
    prices = [dict(p) for p in ports.prices]
    if provider_filter:
        prices = [p for p in prices if provider_filter in str(p["provider"]).lower()]
    sort_key = "input_per_1m" if sort_by == "input" else "output_per_1m"
    prices.sort(key=lambda x: float(x.get(sort_key, 999)))
    free_models = [
        p["model"]
        for p in prices
        if float(p.get("input_per_1m", 0)) == 0 and float(p.get("output_per_1m", 0)) == 0
    ]
    cheapest = prices[0] if prices else None
    return _ok(
        f"对比 {len(prices)} 个模型（按 {sort_key} 升序），{len(free_models)} 个免费",
        prices=prices,
        free_models=free_models,
        cheapest=cheapest,
        sort_by=sort_key,
        total_models=len(ports.prices),
        providers_covered=sorted({p["provider"] for p in ports.prices}),
    )


async def list_vlm_models(ports: ModelCatalog, params: Payload, ctx: Payload) -> Payload:
    """列出当前环境可推断的 VLM（视觉识别）模型候选。

    供 llm-ops-engineer 盘点「谁能做图文识别」，并指导配置
    ``XCAGI_EMPLOYEE_VLM_PROVIDER`` / ``XCAGI_EMPLOYEE_VLM_MODEL``。
    """
    from app.infrastructure.llm.vlm_route import list_configured_vlm_candidates, resolve_vlm_route

    candidates = list_configured_vlm_candidates()
    route = resolve_vlm_route()
    known_defaults = [
        {"provider": "openai", "model": "gpt-4o-mini", "capability": "vlm"},
        {"provider": "qwen", "model": "qwen-vl-plus", "capability": "vlm"},
        {"provider": "zhipu", "model": "glm-4v-flash", "capability": "vlm"},
        {"provider": "siliconflow", "model": "Qwen/Qwen2-VL-7B-Instruct", "capability": "vlm"},
        {"provider": "openrouter", "model": "openai/gpt-4o-mini", "capability": "vlm"},
    ]
    return _ok(
        f"发现 {len(candidates)} 个已配置 VLM 候选；当前路由 ok={bool(route.get('ok'))}",
        candidates=candidates,
        active_route=route,
        known_defaults=known_defaults,
        env_hint={
            "XCAGI_EMPLOYEE_VLM_PROVIDER": os.environ.get("XCAGI_EMPLOYEE_VLM_PROVIDER", "")
            or "(未设置)",
            "XCAGI_EMPLOYEE_VLM_MODEL": os.environ.get("XCAGI_EMPLOYEE_VLM_MODEL", "")
            or "(未设置)",
            "FHD_TEMPLATE_VLM_ENRICH": os.environ.get("FHD_TEMPLATE_VLM_ENRICH", "") or "(未设置)",
        },
    )


async def get_vlm_route(ports: ModelCatalog, params: Payload, ctx: Payload) -> Payload:
    """查询当前生效的员工 VLM 路由（模版 PDF/PPT 识图与员工 call_llm 多模态共用）。"""
    from app.infrastructure.llm.vlm_route import resolve_vlm_route

    route = resolve_vlm_route()
    if route.get("ok"):
        return _ok(
            f"VLM 路由：{route.get('provider')}/{route.get('model')}（{route.get('source')}）",
            route=route,
        )
    return _err(str(route.get("message") or "未配置 VLM"), route=route)


async def query_local_token_usage(ports: ModelCatalog, params: Payload, ctx: Payload) -> Payload:
    """查询本地 token 用量账本（真实数据，非 LLM 编造）。

    读取 FHD 的增量用量账本，返回 token 用量统计。
    b.ai/mimo 等平台不开放 usage 查询 API，但 FHD 在 agent_orchestrator
    路径下会记录每次 LLM 调用的 prompt/completion/total tokens 到本地账本。

    可用 params:
    - user_id: 按用户筛选
    - run_id: 按会话/run 筛选
    - limit: 返回最近 N 条明细（默认 20，0 = 只返回汇总不返回明细）
    - group_by: "model" | "provider" | "none"（默认 model）
    """
    try:
        from app.infrastructure.billing.model_usage import (
            list_model_usage_entries,
            model_usage_database_path,
        )
    except ImportError as exc:
        return _err(f"无法导入 billing 模块: {exc}")
    user_id = str(params.get("user_id") or "").strip()
    run_id = str(params.get("run_id") or "").strip()
    limit = int(str(params.get("limit") if params.get("limit") is not None else 20))
    group_by = str(params.get("group_by") or "model").strip().lower()
    ledger_path = model_usage_database_path()
    entries = list_model_usage_entries(
        limit=max(limit, 500) if limit > 0 else 500, run_id=run_id, user_id=user_id
    )
    model_entries = [e for e in entries if str(e.get("entry_type") or "model_call") == "model_call"]
    total_prompt = sum(int(e.get("prompt_tokens") or 0) for e in model_entries)
    total_completion = sum(int(e.get("completion_tokens") or 0) for e in model_entries)
    total_tokens = sum(int(e.get("total_tokens") or 0) for e in model_entries)
    total_cost = sum(int(e.get("cost_units") or 0) for e in model_entries)
    groups: dict[str, Payload] = {}
    group_key = "model" if group_by == "model" else "provider" if group_by == "provider" else ""
    for e in model_entries:
        if not group_key:
            continue
        key = str(e.get(group_key) or "unknown")
        g = groups.setdefault(
            key,
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_units": 0,
                "calls": 0,
            },
        )
        g["prompt_tokens"] += int(e.get("prompt_tokens") or 0)
        g["completion_tokens"] += int(e.get("completion_tokens") or 0)
        g["total_tokens"] += int(e.get("total_tokens") or 0)
        g["cost_units"] += int(e.get("cost_units") or 0)
        g["calls"] += 1
    details = []
    if limit > 0:
        for e in model_entries[:limit]:
            details.append(
                {
                    "created_at": e.get("created_at", ""),
                    "provider": e.get("provider", ""),
                    "model": e.get("model", ""),
                    "prompt_tokens": int(e.get("prompt_tokens") or 0),
                    "completion_tokens": int(e.get("completion_tokens") or 0),
                    "total_tokens": int(e.get("total_tokens") or 0),
                    "cost_units": int(e.get("cost_units") or 0),
                    "run_id": e.get("run_id", ""),
                    "user_id": e.get("user_id", ""),
                }
            )
    ledger_exists = ledger_path.is_file()
    return _ok(
        f"本地账本 {len(model_entries)} 条 model_call 记录，总 token={total_tokens:,}",
        ledger_path=str(ledger_path),
        ledger_exists=ledger_exists,
        usage_summary={
            "total_calls": len(model_entries),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "cost_units": total_cost,
        },
        groups=groups if group_key else {},
        group_by=group_by,
        details=details,
        detail_count=len(details),
        note="仅 agent_orchestrator 路径记录；conversation 服务主路径未持久化。b.ai/mimo 平台不开放 usage API，需去各自控制台查看。",
    )
