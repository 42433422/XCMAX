"""UsageSources control-plane operations with explicit callback dependencies."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from .ports import ErrorPolicy


class UsageSources:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        to_float: Callable[[object], float],
        to_int: Callable[[object], int],
    ) -> None:
        self._errors = errors
        self._call_to_float = to_float
        self._call_to_int = to_int

    def _to_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _to_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _collect_local_ledger(self) -> dict[str, Any]:
        """FHD 本地 token 账本（model_usage_ledger.json）。"""
        try:
            from app.infrastructure.billing.model_usage import list_model_usage_entries

            entries = list_model_usage_entries(limit=500)
        except self._errors.recoverable() as exc:
            return {"available": False, "reason": f"读取账本失败: {exc}"}
        prompt = sum(self._call_to_int(e.get("prompt_tokens")) for e in entries)
        completion = sum(self._call_to_int(e.get("completion_tokens")) for e in entries)
        total = sum(self._call_to_int(e.get("total_tokens")) for e in entries)
        cost = sum(self._call_to_float(e.get("cost_units")) for e in entries)
        by_model: dict[str, dict[str, Any]] = {}
        for e in entries:
            key = f"{e.get('provider', '?')}/{e.get('model', '?')}"
            slot = by_model.setdefault(key, {"total": 0, "count": 0, "cost": 0.0})
            slot["total"] += self._call_to_int(e.get("total_tokens"))
            slot["count"] += 1
            slot["cost"] += self._call_to_float(e.get("cost_units"))
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

    def _collect_cursor_usage(self) -> dict[str, Any]:
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
                [cli, "--json", "--days", "30"], capture_output=True, text=True, timeout=30
            )
        except self._errors.recoverable() as exc:
            return {"available": False, "reason": f"执行失败: {exc}"}
        if proc.returncode != 0:
            return {"available": False, "reason": f"exit={proc.returncode}"}
        try:
            raw = json.loads(proc.stdout)
        except self._errors.recoverable() as exc:
            return {"available": False, "reason": f"JSON 解析失败: {exc}"}
        aggs = raw.get("aggregations", []) if isinstance(raw, dict) else []
        total_input = sum(self._call_to_int(a.get("inputTokens")) for a in aggs)
        total_output = sum(self._call_to_int(a.get("outputTokens")) for a in aggs)
        total_cache_read = sum(self._call_to_int(a.get("cacheReadTokens")) for a in aggs)
        total_cache_write = sum(self._call_to_int(a.get("cacheWriteTokens")) for a in aggs)
        total_cents = sum(self._call_to_float(a.get("totalCents")) for a in aggs)
        by_model: dict[str, dict[str, Any]] = {}
        for a in aggs:
            m = a.get("modelIntent", "unknown")
            slot = by_model.setdefault(
                m, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cents": 0.0}
            )
            slot["input"] += self._call_to_int(a.get("inputTokens"))
            slot["output"] += self._call_to_int(a.get("outputTokens"))
            slot["cache_read"] += self._call_to_int(a.get("cacheReadTokens"))
            slot["cache_write"] += self._call_to_int(a.get("cacheWriteTokens"))
            slot["cents"] += self._call_to_float(a.get("totalCents"))
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

    def _collect_codex_usage(self) -> dict[str, Any]:
        """Codex 用量（~/.codex/archived_sessions/*.jsonl）。"""
        archived = os.path.expanduser("~/.codex/archived_sessions")
        if not os.path.isdir(archived):
            return {"available": False, "reason": f"目录不存在: {archived}"}
        jsonl_files = sorted(
            f
            for f in (os.path.join(archived, x) for x in os.listdir(archived))
            if f.endswith(".jsonl")
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
                        except self._errors.recoverable():
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
                            i = self._call_to_int(usage.get("input_tokens"))
                            c = self._call_to_int(usage.get("cached_input_tokens"))
                            o = self._call_to_int(usage.get("output_tokens"))
                            r = self._call_to_int(usage.get("reasoning_output_tokens"))
                            t = self._call_to_int(usage.get("total_tokens"))
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
            except self._errors.recoverable():
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

    def _collect_trae_usage(self) -> dict[str, Any]:
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
                n = self._call_to_int(value)
                total_turns += n
                turn_details[key] = n
            cur.execute(
                "SELECT value FROM ItemTable WHERE key LIKE '%sessionRelation:globalModelMap%' LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                try:
                    current_models = json.loads(row[0])
                except self._errors.recoverable():
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
                except self._errors.recoverable():
                    pass
            conn.close()
        except self._errors.recoverable() as exc:
            return {"available": False, "reason": f"读取 state.vscdb 失败: {exc}"}
        est_prompt_per_turn = 10000000
        est_completion_per_turn = 500000
        est_prompt = total_turns * est_prompt_per_turn
        est_completion = total_turns * est_completion_per_turn
        est_total = est_prompt + est_completion
        return {
            "available": True,
            "source": "Trae (state.vscdb + 轮次估算)",
            "note": f"Trae API 被 WAF 403 拦截，按 {total_turns} 轮 × 1050 万 tokens/轮 估算（prompt 1000 万 + completion 50 万）",
            "estimated": True,
            "total_chat_turns": total_turns,
            "turn_details": turn_details,
            "current_models": current_models,
            "available_models_count": available_models_count,
            "prompt_tokens": est_prompt,
            "completion_tokens": est_completion,
            "total_tokens": est_total,
        }

    def _collect_mimo_usage(self) -> dict[str, Any]:
        """采集 mimo（小米 MiMo）用量。手动输入静态数据。"""
        credits_used = 22070888859
        credits_quota = 38000000000
        actual_tokens = 80621905
        usage_pct = round(credits_used / credits_quota * 100, 1) if credits_quota else 0
        return {
            "available": True,
            "source": "mimo (小米 MiMo, 手动输入)",
            "note": f"Credits {credits_used:,} / {credits_quota:,}（{usage_pct}%），实际 token {actual_tokens:,}",
            "total_tokens": actual_tokens,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "credits_used": credits_used,
            "credits_quota": credits_quota,
            "usage_percent": usage_pct,
            "estimated": True,
        }
