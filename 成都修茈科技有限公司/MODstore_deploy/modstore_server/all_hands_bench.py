"""Dispatch grounded standby reports, synthesized answers, and meeting minutes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Tuple

from modstore_server.all_hands_ports import (
    BenchDispatcher,
    ExcerptReader,
    JsonObject,
    SessionProvider,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchReply:
    text: str = ""
    error: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class AllHandsBench:
    session_provider: SessionProvider
    dispatch: BenchDispatcher
    excerpt: ExcerptReader
    standby_context: Callable[[str, JsonObject], JsonObject]
    craft_ids: frozenset[str]
    standby_prompt: str
    answer_prompt: str
    minutes_prompt: str

    async def standby_report(
        self,
        *,
        pkg_id: str,
        display_name: str,
        task_text: str,
        inp: Dict[str, Any],
        user_id: int,
        bench_provider: str,
        bench_model: str,
    ) -> Tuple[str, str, int]:
        """制作车间待机：用大会任务模板 + bench LLM，不经员工 cognition（避免 JSON 告警）。"""
        payload = dict(inp)
        if pkg_id in self.craft_ids:
            sig = payload.get("manifest_signals")
            if isinstance(sig, dict):
                payload["craft_workshop_standby"] = self.standby_context(pkg_id, sig)
        user_content = f"{task_text}\n\n---\n\n以下为结构化输入（JSON），请据此撰写四段 Markdown 汇报：\n{json.dumps(payload, ensure_ascii=False)[:14000]}"
        messages = [
            {"role": "system", "content": self.standby_prompt},
            {"role": "user", "content": user_content},
        ]
        reply = await self._request(
            user_id,
            bench_provider,
            bench_model,
            messages,
            max_tokens=4096,
            exception_prefix="待机汇报 LLM 异常：",
        )
        return (reply.text, reply.error[:800], reply.tokens)

    async def answer(
        self,
        *,
        user_question: str,
        employees: List[Dict[str, Any]],
        bench_provider: str,
        bench_model: str,
        user_id: int,
    ) -> Dict[str, Any]:
        """把多名员工的 Q&A 答复送给 bench LLM 合并成「数字管家综合答复」。

        返回 ``{ markdown, cited_employees: [pkg_id], model, error }``；
        bench LLM 不可用或失败时 ``markdown == ""`` 且 ``error`` 非空。
        """
        started_at = datetime.now(timezone.utc).isoformat()
        cited = [
            str(r.get("employee_id") or "").strip()
            for r in employees
            if str(r.get("employee_id") or "").strip()
        ]
        if not bench_provider or not bench_model:
            return {
                "question": user_question,
                "markdown": "",
                "cited_employees": cited,
                "generated_at": started_at,
                "model": "",
                "error": "平台 Bench LLM 未配置（MODSTORE_EMPLOYEE_BENCH_* 或平台 Key）",
            }
        parts: List[str] = []
        for row in employees:
            eid = str(row.get("employee_id") or "").strip()
            name = str(row.get("name") or eid).strip()
            area = str(row.get("area") or "").strip()
            if not eid:
                continue
            excerpt = self.excerpt(row)
            parts.append(f"### [{eid}] {name}（区域：{area or '未知'}）\n\n{excerpt}")
        body = "\n\n".join(parts) if parts else "（没有可合并的员工答复）"
        user_content = f"管理员问题：\n{(user_question or '').strip()}\n\n以下是 {len(parts)} 名员工以自身岗位视角给出的答复：\n\n{body}"
        messages = [
            {"role": "system", "content": self.answer_prompt},
            {"role": "user", "content": user_content},
        ]
        reply = await self._request(
            user_id,
            bench_provider,
            bench_model,
            messages,
            max_tokens=2048,
            exception_prefix="调用 bench LLM 异常：",
        )
        return {
            "question": user_question,
            "markdown": reply.text,
            "cited_employees": cited,
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": reply.error or ("" if reply.text else "bench LLM 返回为空"),
        }

    async def minutes(self, *, report: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """将已成功生成的 ``build_all_hands_report`` 结果压缩为五段式「会议摘要」正文。

        返回 ``{ text, generated_at, model, error }``；失败时 ``text`` 可为空且 ``error`` 非空。
        """
        started_at = datetime.now(timezone.utc).isoformat()
        raw_summary = report.get("summary")
        summary = raw_summary if isinstance(raw_summary, dict) else {}
        bench_provider = str(summary.get("bench_provider") or "").strip()
        bench_model = str(summary.get("bench_model") or "").strip()
        if not bench_provider or not bench_model:
            return {
                "text": "",
                "generated_at": started_at,
                "model": "",
                "error": "平台 Bench LLM 未配置（报告 summary 中无 bench）",
            }
        raw_emp = report.get("employees") or []
        employees: List[Dict[str, Any]] = raw_emp if isinstance(raw_emp, list) else []
        parts: List[str] = []
        for row in employees:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("employee_id") or "").strip()
            name = str(row.get("name") or eid).strip()
            if not eid:
                continue
            excerpt = self.excerpt(row, max_chars=1200)
            st = str(row.get("status") or "").strip()
            parts.append(f"### [{eid}] {name}（状态：{st}）\n\n{excerpt}")
        body_emp = "\n\n".join(parts) if parts else "（无员工汇报）"
        uq = str(summary.get("user_question") or "").strip()
        synth_extra = ""
        synth = report.get("synthesized_answer")
        if isinstance(synth, dict):
            sm = str(synth.get("markdown") or "").strip()
            if sm:
                synth_extra = f"\n\n## 数字管家综合答复（员工大会问答）\n\n{sm[:4000]}"
        standby_note = ""
        if not uq:
            craft_n = sum(
                (
                    1
                    for row in employees
                    if isinstance(row, dict) and str(row.get("employee_id") or "") in self.craft_ids
                )
            )
            if craft_n:
                standby_note = f"\n\n> 说明：本次为**待机汇总**（无管理员提问），制作车间约 {craft_n} 个岗位为流水线就绪汇报；节选中的「缺上游」勿当作故障。\n"
        user_content = (
            "以下是一次员工大会收集到的各岗汇报节选，请据此撰写会议摘要（说人话、给管理员看）。\n\n"
            + (f"管理员提问：{uq}\n\n" if uq else "")
            + standby_note
            + f"## 各员工汇报节选\n\n{body_emp}{synth_extra}"
        )
        messages = [
            {"role": "system", "content": self.minutes_prompt},
            {"role": "user", "content": user_content},
        ]
        reply = await self._request(
            user_id,
            bench_provider,
            bench_model,
            messages,
            max_tokens=2048,
            exception_prefix="调用 bench LLM 异常：",
        )
        return {
            "text": reply.text,
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": reply.error or ("" if reply.text else "bench LLM 返回为空"),
        }

    async def _request(
        self,
        user_id: int,
        provider: str,
        model: str,
        messages: list[JsonObject],
        *,
        max_tokens: int,
        exception_prefix: str,
    ) -> BenchReply:
        try:
            factory = self.session_provider()
            with factory() as session:
                result = await self.dispatch(
                    session,
                    int(user_id or 0),
                    provider,
                    model,
                    messages,
                    max_tokens=max_tokens,
                )
        except RECOVERABLE_ERRORS as exc:
            logger.exception("all_hands bench dispatch failed")
            return BenchReply(error=f"{exception_prefix}{exc}")
        if not isinstance(result, dict) or not result.get("ok"):
            error = str(result.get("error") or "").strip() if isinstance(result, dict) else ""
            return BenchReply(error=error or "bench LLM 未返回有效内容")
        text = str(result.get("content") or "").strip()
        if not text:
            choices = result.get("choices")
            first = choices[0] if isinstance(choices, list) and choices else None
            message = first.get("message") if isinstance(first, dict) else None
            if isinstance(message, dict):
                text = str(message.get("content") or "").strip()
        raw = result.get("raw")
        usage = raw.get("usage") if isinstance(raw, dict) else None
        tokens = 0
        if isinstance(usage, dict):
            try:
                tokens = int(usage.get("total_tokens") or 0)
                if not tokens:
                    tokens = int(usage.get("prompt_tokens") or 0) + int(
                        usage.get("completion_tokens") or 0
                    )
            except (TypeError, ValueError, OverflowError):
                logger.warning("all_hands bench returned invalid token usage")
        return BenchReply(text=text, tokens=max(0, tokens))
