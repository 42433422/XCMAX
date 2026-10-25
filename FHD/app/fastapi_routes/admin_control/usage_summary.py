"""UsageSummary control-plane operations with explicit callback dependencies."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import ErrorPolicy, JsonObject


class UsageSummary:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        to_int: Callable[[object], int],
        collect_codex_usage: Callable[[], JsonObject],
        collect_cursor_usage: Callable[[], JsonObject],
        collect_local_ledger: Callable[[], JsonObject],
        collect_mimo_usage: Callable[[], JsonObject],
        collect_trae_usage: Callable[[], JsonObject],
        estimate_cost: Callable[[str, JsonObject], float],
        build_token_usage_summary: Callable[[], JsonObject],
    ) -> None:
        self._errors = errors
        self._to_int = to_int
        self._collect_codex_usage = collect_codex_usage
        self._collect_cursor_usage = collect_cursor_usage
        self._collect_local_ledger = collect_local_ledger
        self._collect_mimo_usage = collect_mimo_usage
        self._collect_trae_usage = collect_trae_usage
        self._estimate_cost = estimate_cost
        self._call_build_token_usage_summary = build_token_usage_summary

    def _estimate_cost_usd(self, source_key: str, data: dict[str, Any]) -> float:
        """估算费用（美元）。Cursor 用精确 cents，其余按 API 单价估算。"""
        if not data.get("available"):
            return 0.0
        if source_key == "cursor":
            return self._to_int(data.get("cost_cents")) / 100.0
        if source_key == "codex":
            prompt = self._to_int(data.get("prompt_tokens"))
            cached = self._to_int(data.get("cache_read_tokens"))
            output = self._to_int(data.get("completion_tokens"))
            reasoning = self._to_int(data.get("reasoning_tokens"))
            uncached = max(0, prompt - cached)
            return (
                uncached * 5 / 1000000
                + cached * 1.25 / 1000000
                + (output + reasoning) * 10 / 1000000
            )
        if source_key == "trae":
            prompt = self._to_int(data.get("prompt_tokens"))
            output = self._to_int(data.get("completion_tokens"))
            return (prompt + output) * 5 / 7.2 / 1000000
        if source_key == "local":
            return self._to_int(data.get("cost_units")) / 100.0
        if source_key == "mimo":
            return 0.0
        return 0.0

    def _build_token_usage_summary(self) -> dict[str, Any]:
        """聚合 5 个来源的 token 用量（平台制作 Token）。"""
        local = self._collect_local_ledger()
        cursor = self._collect_cursor_usage()
        codex = self._collect_codex_usage()
        trae = self._collect_trae_usage()
        mimo = self._collect_mimo_usage()
        sources = {"local": local, "cursor": cursor, "codex": codex, "trae": trae, "mimo": mimo}
        for key, src in sources.items():
            src["estimated_cost_usd"] = round(self._estimate_cost(key, src), 2)
        grand_total = sum(self._to_int(s.get("total_tokens")) for s in sources.values())
        grand_prompt = sum(self._to_int(s.get("prompt_tokens")) for s in sources.values())
        grand_completion = sum(self._to_int(s.get("completion_tokens")) for s in sources.values())
        grand_cost = round(sum(s.get("estimated_cost_usd", 0.0) for s in sources.values()), 2)
        summary = {
            "success": True,
            "grand_total_tokens": grand_total,
            "grand_prompt_tokens": grand_prompt,
            "grand_completion_tokens": grand_completion,
            "grand_cost_usd": grand_cost,
            "sources": sources,
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            from app.infrastructure.billing.platform_made_tokens import write_public_snapshot

            snapshot_path = write_public_snapshot(summary)
            summary["public_snapshot_path"] = str(snapshot_path)
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("platform_made_tokens snapshot write failed: %s", exc)
        return summary

    async def admin_token_usage(self, request: Request):
        """平台制作 Token：本地账本 + Cursor + Codex + Trae + mimo。"""
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        if not _session_id_from_request(request):
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        return await asyncio.to_thread(self._call_build_token_usage_summary)
