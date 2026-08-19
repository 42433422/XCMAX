# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_bench")


def _derive_bench_execution_ok(raw: _facade().Dict[str, _facade().Any]) -> bool:
    """从 execute_employee_task 返回体推导是否执行成功（顶层无 ok 字段）。"""
    if not isinstance(raw, dict):
        return False
    if str(raw.get("cognition_error") or "").strip():
        return False
    if raw.get("ok") is False:
        return False
    err_top = raw.get("error")
    if err_top and (not raw.get("result")):
        return False
    inner = raw.get("result")
    if not isinstance(inner, dict):
        return True
    for out in inner.get("outputs") or []:
        if not isinstance(out, dict):
            continue
        if out.get("error"):
            return False
        if out.get("ok") is False:
            return False
    return True


def _extract_output_preview(raw: _facade().Dict[str, _facade().Any], limit: int = 500) -> str:
    """抽取员工输出摘要供裁判模型评分。"""
    if not isinstance(raw, dict):
        return ""
    head = str(raw.get("reasoning_excerpt") or "").strip()
    parts: _facade().List[str] = []
    if head:
        parts.append(head[:limit])
    inner = raw.get("result")
    if isinstance(inner, dict):
        chunks: _facade().List[str] = []
        for out in (inner.get("outputs") or [])[:8]:
            if not isinstance(out, dict):
                continue
            text = (
                out.get("output")
                or out.get("reasoning")
                or out.get("summary")
                or out.get("text_preview")
                or out.get("response")
            )
            if text:
                chunks.append(str(text).strip()[:limit])
            elif out.get("error"):
                chunks.append(f"error:{str(out.get('error'))[:200]}")
        if chunks:
            parts.extend(chunks)
    if parts:
        return "\n".join(parts)[: limit * 5]
    if raw.get("error"):
        return f"error:{str(raw.get('error'))[:limit]}"
    return ""


def _parse_rubric_scores(content: str) -> _facade().Dict[str, float]:
    """解析裁判模型返回的 JSON 数组。"""
    raw = _facade()._strip_fence(content)
    try:
        data = _facade().json.loads(raw)
    except _facade().json.JSONDecodeError:
        (i, j) = (raw.find("["), raw.rfind("]"))
        if i < 0 or j <= i:
            return {}
        try:
            data = _facade().json.loads(raw[i : j + 1])
        except _facade().json.JSONDecodeError:
            return {}
    if not isinstance(data, list):
        return {}
    out: _facade().Dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("task_id") or "").strip()
        sc = row.get("score")
        if not tid or sc is None:
            continue
        try:
            val = float(sc)
        except (TypeError, ValueError):
            continue
        out[tid] = float(max(0.0, min(100.0, val)))
    return out


def _align_rubric_keys(
    raw_scores: _facade().Dict[str, float], expected_ids: set[str]
) -> _facade().Dict[str, float]:
    """裁判返回的 task_id 可能与请求略有差异，对齐到真实 task_id。"""
    if not raw_scores or not expected_ids:
        return {}
    out: _facade().Dict[str, float] = {}
    lower_map = {k.strip().lower(): v for (k, v) in raw_scores.items()}
    for tid in expected_ids:
        if tid in raw_scores:
            out[tid] = raw_scores[tid]
            continue
        lk = tid.strip().lower()
        if lk in lower_map:
            out[tid] = lower_map[lk]
    return out


async def _llm_rubric_scores_platform(
    provider: str, model: str, items: _facade().List[_facade().Dict[str, _facade().Any]]
) -> _facade().Tuple[_facade().Dict[str, float], _facade().Optional[str]]:
    """调用平台密钥裁判模型为每条任务打分（不经 require_llm_credit / 钱包）。"""
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    if not items:
        return ({}, None)
    out: _facade().Dict[str, float] = {}
    chunk_size = 10
    last_err: _facade().Optional[str] = None
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        payload = _facade().json.dumps(chunk, ensure_ascii=False)
        result = await chat_dispatch_via_platform_only(
            provider,
            model,
            [
                {"role": "system", "content": _facade()._RUBRIC_SYSTEM},
                {"role": "user", "content": payload},
            ],
            max_tokens=6000,
        )
        if not result.get("ok"):
            last_err = str(result.get("error") or "rubric upstream error")
            _facade().logger.warning("bench rubric LLM failed: %s", last_err)
            continue
        part = _facade()._parse_rubric_scores(str(result.get("content") or ""))
        out.update(part)
    return (out, last_err)


def _level_scores_from_entries(
    tasks_result: _facade().List[_facade().Dict[str, _facade().Any]]
) -> _facade().Dict[int, float]:
    buckets: _facade().Dict[int, _facade().List[float]] = _facade().defaultdict(list)
    for e in tasks_result:
        lv = int(e.get("level") or 0)
        if 1 <= lv <= 5:
            buckets[lv].append(float(e.get("score") or 0.0))
    out: _facade().Dict[int, float] = {}
    for lv in range(1, 6):
        vals = buckets.get(lv) or []
        out[lv] = round(sum(vals) / len(vals), 1) if vals else 0.0
    return out


def _efficiency_factor(cost_tokens: int) -> float:
    """token 消耗越少效率因子越高（最大 1.0）。"""
    if cost_tokens <= 0:
        return 1.0
    factor = _facade()._EFFICIENT_TOKEN_THRESHOLD / max(
        cost_tokens, _facade()._EFFICIENT_TOKEN_THRESHOLD
    )
    return min(1.0, factor)


def _run_single_task(
    employee_id: str,
    task_desc: str,
    user_id: int,
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """同步执行单条任务，记录 ok / cost_tokens / duration_ms。"""
    from modstore_server.services.employee import get_default_employee_client

    client = get_default_employee_client()
    t0 = _facade().time.perf_counter()
    try:
        res = client.execute_task(
            employee_id=employee_id,
            task=task_desc,
            input_data={},
            user_id=user_id,
            bench_llm_override=bench_llm_override,
        )
        if isinstance(res, dict):
            ok = _facade()._derive_bench_execution_ok(res)
            cost_tokens = int(
                res.get("llm_tokens") or res.get("cost_tokens") or res.get("tokens_used") or 0
            )
        else:
            ok = bool(res)
            cost_tokens = 0
    except Exception as exc:
        _facade().logger.warning(
            "bench task failed employee=%s task=%r: %s", employee_id, task_desc[:40], exc
        )
        ok = False
        cost_tokens = 0
        res = {"error": str(exc)}
    duration_ms = (_facade().time.perf_counter() - t0) * 1000
    raw_dict = res if isinstance(res, dict) else {}
    return {
        "ok": ok,
        "cost_tokens": cost_tokens,
        "duration_ms": round(duration_ms, 1),
        "raw": raw_dict,
        "output_preview": _facade()._extract_output_preview(raw_dict),
    }


def _score_level(level_results: _facade().List[_facade().Dict[str, _facade().Any]]) -> float:
    """对某一级的多条任务结果计算平均得分（0-100）。"""
    if not level_results:
        return 0.0
    scores = [
        100.0 * (1.0 if r["ok"] else 0.0) * _facade()._efficiency_factor(r["cost_tokens"])
        for r in level_results
    ]
    return sum(scores) / len(scores)


def _weighted_overall(level_scores: _facade().Dict[int, float]) -> float:
    total_w = sum((_facade()._LEVEL_WEIGHTS[lv] for lv in range(1, 6)))
    weighted = sum(
        (_facade()._LEVEL_WEIGHTS.get(lv, 1.0) * level_scores.get(lv, 0.0) for lv in range(1, 6))
    )
    return weighted / total_w if total_w else 0.0
