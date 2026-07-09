"""Token usage collectors for xcmax admin (split from xcmax_admin.py).

Symbols are re-exported by ``app.fastapi_routes.xcmax_admin`` so existing
test patches on that module path keep working when summary/route call them.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _collect_local_ledger() -> dict[str, Any]:
    """FHD 本地 token 账本（model_usage_ledger.json）。"""
    try:
        from app.infrastructure.billing.model_usage import list_model_usage_entries

        entries = list_model_usage_entries(limit=500)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"读取账本失败: {exc}"}
    prompt = sum(_to_int(e.get("prompt_tokens")) for e in entries)
    completion = sum(_to_int(e.get("completion_tokens")) for e in entries)
    total = sum(_to_int(e.get("total_tokens")) for e in entries)
    cost = sum(_to_float(e.get("cost_units")) for e in entries)
    by_model: dict[str, dict[str, Any]] = {}
    for e in entries:
        key = f"{e.get('provider', '?')}/{e.get('model', '?')}"
        slot = by_model.setdefault(key, {"total": 0, "count": 0, "cost": 0.0})
        slot["total"] += _to_int(e.get("total_tokens"))
        slot["count"] += 1
        slot["cost"] += _to_float(e.get("cost_units"))
    return {
        "available": True,
        "source": "FHD 本地账本",
        "records": len(entries),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_units": cost,
        "by_model": dict(sorted(by_model.items(), key=lambda x: -x[1]["total"])),
    }


def _collect_cursor_usage() -> dict[str, Any]:
    """Cursor 用量（cursor-usage CLI）。"""
    import shutil
    import subprocess

    cli = shutil.which("cursor-usage") or str(
        os.path.expanduser("~/Library/Python/3.9/bin/cursor-usage")
    )
    if not os.path.exists(cli):
        return {"available": False, "reason": f"cursor-usage CLI 不存在: {cli}"}
    try:
        proc = subprocess.run(
            [cli, "--json", "--days", "30"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"执行失败: {exc}"}
    if proc.returncode != 0:
        return {"available": False, "reason": f"exit={proc.returncode}"}
    try:
        raw = json.loads(proc.stdout)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"JSON 解析失败: {exc}"}
    aggs = raw.get("aggregations", []) if isinstance(raw, dict) else []
    total_input = sum(_to_int(a.get("inputTokens")) for a in aggs)
    total_output = sum(_to_int(a.get("outputTokens")) for a in aggs)
    total_cache_read = sum(_to_int(a.get("cacheReadTokens")) for a in aggs)
    total_cache_write = sum(_to_int(a.get("cacheWriteTokens")) for a in aggs)
    total_cents = sum(_to_float(a.get("totalCents")) for a in aggs)
    by_model: dict[str, dict[str, Any]] = {}
    for a in aggs:
        m = a.get("modelIntent", "unknown")
        slot = by_model.setdefault(
            m, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cents": 0.0}
        )
        slot["input"] += _to_int(a.get("inputTokens"))
        slot["output"] += _to_int(a.get("outputTokens"))
        slot["cache_read"] += _to_int(a.get("cacheReadTokens"))
        slot["cache_write"] += _to_int(a.get("cacheWriteTokens"))
        slot["cents"] += _to_float(a.get("totalCents"))
    return {
        "available": True,
        "source": "Cursor (cursor-usage CLI, 最近 30 天)",
        "aggregations": len(aggs),
        "prompt_tokens": total_input,
        "completion_tokens": total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
        "total_tokens": total_input + total_output + total_cache_read + total_cache_write,
        "cost_cents": total_cents,
        "by_model": dict(
            sorted(
                by_model.items(),
                key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_read"]),
            )
        ),
    }


def _collect_codex_usage() -> dict[str, Any]:
    """Codex 用量（~/.codex/archived_sessions/*.jsonl）。"""
    archived = os.path.expanduser("~/.codex/archived_sessions")
    if not os.path.isdir(archived):
        return {"available": False, "reason": f"目录不存在: {archived}"}
    jsonl_files = sorted(
        f for f in (os.path.join(archived, x) for x in os.listdir(archived)) if f.endswith(".jsonl")
    )
    total_input = total_cached = total_output = total_reasoning = total_total = 0
    by_model: dict[str, dict[str, Any]] = {}
    session_count = 0
    for fpath in jsonl_files:
        session_model = "unknown"
        has_token = False
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    try:
                        evt = json.loads(line)
                    except RECOVERABLE_ERRORS:
                        continue
                    if evt.get("type") == "session_meta":
                        payload = evt.get("payload") or {}
                        session_model = (
                            payload.get("model") or payload.get("model_provider") or "unknown"
                        )
                    if (
                        evt.get("type") == "event_msg"
                        and (evt.get("payload") or {}).get("type") == "token_count"
                    ):
                        info = (evt.get("payload") or {}).get("info") or {}
                        usage = info.get("total_token_usage") or {}
                        i = _to_int(usage.get("input_tokens"))
                        c = _to_int(usage.get("cached_input_tokens"))
                        o = _to_int(usage.get("output_tokens"))
                        r = _to_int(usage.get("reasoning_output_tokens"))
                        t = _to_int(usage.get("total_tokens"))
                        total_input += i
                        total_cached += c
                        total_output += o
                        total_reasoning += r
                        total_total += t
                        slot = by_model.setdefault(
                            session_model,
                            {
                                "input": 0,
                                "cached": 0,
                                "output": 0,
                                "reasoning": 0,
                                "total": 0,
                                "count": 0,
                            },
                        )
                        slot["input"] += i
                        slot["cached"] += c
                        slot["output"] += o
                        slot["reasoning"] += r
                        slot["total"] += t
                        slot["count"] += 1
                        has_token = True
        except RECOVERABLE_ERRORS:
            continue
        if has_token:
            session_count += 1
    return {
        "available": True,
        "source": "Codex (~/.codex/archived_sessions)",
        "jsonl_files": len(jsonl_files),
        "sessions_with_tokens": session_count,
        "prompt_tokens": total_input,
        "cached_tokens": total_cached,
        "completion_tokens": total_output,
        "reasoning_tokens": total_reasoning,
        "total_tokens": total_total,
        "by_model": dict(sorted(by_model.items(), key=lambda x: -x[1]["total"])),
    }


def _collect_trae_usage() -> dict[str, Any]:
    """Trae 用量（state.vscdb，API 403 无法获取精确 token）。"""
    import sqlite3

    state_db = os.path.expanduser(
        "~/Library/Application Support/Trae CN/User/globalStorage/state.vscdb"
    )
    if not os.path.exists(state_db):
        return {"available": False, "reason": f"state.vscdb 不存在: {state_db}"}
    total_turns = 0
    turn_details: dict[str, int] = {}
    current_models: Any = None
    available_models_count = 0
    try:
        conn = sqlite3.connect(state_db)
        cur = conn.cursor()
        cur.execute(
            "SELECT key, value FROM ItemTable WHERE key LIKE 'ai.chat.feedback%.accumulatedTurns'"
        )
        for key, value in cur.fetchall():
            n = _to_int(value)
            total_turns += n
            turn_details[key] = n
        cur.execute(
            "SELECT value FROM ItemTable WHERE key LIKE '%sessionRelation:globalModelMap%' LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            try:
                current_models = json.loads(row[0])
            except RECOVERABLE_ERRORS:
                current_models = None
        cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%model_list_map%' LIMIT 1")
        row = cur.fetchone()
        if row:
            try:
                m = json.loads(row[0])
                if isinstance(m, dict):
                    for _mode, models in m.items():
                        if isinstance(models, list):
                            available_models_count += len(models)
            except RECOVERABLE_ERRORS:
                pass
        conn.close()
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"读取 state.vscdb 失败: {exc}"}
    # Trae API 被 403 拦截，用轮次估算 token 用量
    # IDE AI 助手 Composer/Agent 模式每轮：prompt ~10000000（含多文件代码上下文+历史对话缓存）
    # + completion ~500000（AI 回复+代码生成）
    # 参照 Cursor 52 亿/30 天、Codex 84 亿/5 会话校准
    est_prompt_per_turn = 10_000_000
    est_completion_per_turn = 500_000
    est_prompt = total_turns * est_prompt_per_turn
    est_completion = total_turns * est_completion_per_turn
    est_total = est_prompt + est_completion
    return {
        "available": True,
        "source": "Trae (state.vscdb + 轮次估算)",
        "note": f"Trae API 被 WAF 403 拦截，按 {total_turns} 轮 × 1050 万 tokens/轮 估算"
        f"（prompt 1000 万 + completion 50 万）",
        "estimated": True,
        "total_chat_turns": total_turns,
        "turn_details": turn_details,
        "current_models": current_models,
        "available_models_count": available_models_count,
        "prompt_tokens": est_prompt,
        "completion_tokens": est_completion,
        "total_tokens": est_total,
    }


def _estimate_cost_usd(source_key: str, data: dict[str, Any]) -> float:
    """估算费用（美元）。Cursor 用精确 cents，其余按 API 单价估算。"""
    if not data.get("available"):
        return 0.0
    if source_key == "cursor":
        return _to_int(data.get("cost_cents")) / 100.0
    if source_key == "codex":
        # GPT-5: input $5/1M (uncached), $1.25/1M (cached), output+reasoning $10/1M
        prompt = _to_int(data.get("prompt_tokens"))
        cached = _to_int(data.get("cache_read_tokens"))
        output = _to_int(data.get("completion_tokens"))
        reasoning = _to_int(data.get("reasoning_tokens"))
        uncached = max(0, prompt - cached)
        return (
            uncached * 5 / 1_000_000
            + cached * 1.25 / 1_000_000
            + (output + reasoning) * 10 / 1_000_000
        )
    if source_key == "trae":
        # GLM-5.1: input ¥5/1M, output ¥5/1M, 1 USD ≈ 7.2 CNY
        prompt = _to_int(data.get("prompt_tokens"))
        output = _to_int(data.get("completion_tokens"))
        return (prompt + output) * 5 / 7.2 / 1_000_000
    if source_key == "local":
        return _to_int(data.get("cost_units")) / 100.0
    if source_key == "mimo":
        # mimo 套餐制，Credits 额度内不再单独计费
        return 0.0
    return 0.0


def _collect_mimo_usage() -> dict[str, Any]:
    """采集 mimo（小米 MiMo）用量。手动输入静态数据。"""
    # 用户手动提供：实际 token 80,621,905，Credits 额度 38,000,000,000
    credits_used = 22_070_888_859
    credits_quota = 38_000_000_000
    actual_tokens = 80_621_905
    usage_pct = round(credits_used / credits_quota * 100, 1) if credits_quota else 0
    return {
        "available": True,
        "source": "mimo (小米 MiMo, 手动输入)",
        "note": f"Credits {credits_used:,} / {credits_quota:,}（{usage_pct}%），"
        f"实际 token {actual_tokens:,}",
        "total_tokens": actual_tokens,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "credits_used": credits_used,
        "credits_quota": credits_quota,
        "usage_percent": usage_pct,
        "estimated": True,
    }


