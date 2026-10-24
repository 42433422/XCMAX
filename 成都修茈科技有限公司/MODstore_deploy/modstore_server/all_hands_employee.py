"""Prepare grounded employee input and execute one bounded report request."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from modstore_server.all_hands_ports import (
    EmployeeExecutor,
    JsonObject,
    ResearchBuilder,
    StandbyPolicy,
    StandbyReport,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmployeeReporter:
    research_brief: Callable[[str, str], str]
    research: ResearchBuilder
    pack_excerpt: Callable[[str], tuple[str, list[str]]]
    failures: Callable[[str], list[JsonObject]]
    metadata: Callable[[str], JsonObject]
    manifest: Callable[[str], JsonObject]
    role_context: Callable[[str], JsonObject]
    area_for: Callable[[str], str | None]
    qa_template: str
    report_template: str
    standby_policy: StandbyPolicy
    standby_report: StandbyReport
    coerce_excerpt: Callable[[str, JsonObject], str]
    execute: EmployeeExecutor

    async def report(
        self,
        *,
        pkg_id: str,
        display_name: str,
        other_employees: List[str],
        user_id: int,
        bench_provider: str,
        bench_model: str,
        with_research: bool,
        user_question: Optional[str] = None,
    ) -> Dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat()
        warns: List[str] = []
        research_pack = ""
        research_sources: List[Dict[str, str]] = []
        if with_research:
            seed = self.research_brief(pkg_id, display_name)
            try:
                rc = await self.research(
                    brief=seed,
                    intent="employee",
                    max_repos=2,
                    max_chars=5000,
                    max_web=6,
                    user_id=user_id,
                    rate_limit_bucket="agent_tool",
                )
                if rc.get("ok"):
                    research_pack = str(rc.get("context_pack") or "")
                    research_sources = [
                        {"title": str(s.get("title") or ""), "url": str(s.get("url") or "")}
                        for s in rc.get("sources") or []
                        if isinstance(s, dict)
                    ][:8]
                else:
                    warns.append(str(rc.get("error") or "research failed"))
                for w in rc.get("warnings") or []:
                    warns.append(str(w))
            except RECOVERABLE_ERRORS as exc:
                logger.warning("all_hands research failed pkg_id=%s err=%s", pkg_id, exc)
                warns.append(f"research 失败：{exc}")
        excerpt, yg_warns = self.pack_excerpt(pkg_id)
        warns.extend(yg_warns)
        failures = self.failures(pkg_id)
        yuangon_meta = self.metadata(pkg_id)
        signals = self.manifest(pkg_id)
        user_q = (user_question or "").strip()
        if user_q:
            task_text = self.qa_template.format(employee_id=pkg_id, user_question=user_q)
        else:
            task_text = self.report_template.format(employee_id=pkg_id)
        inp: Dict[str, Any] = {
            "research_context": research_pack,
            "research_sources": research_sources,
            "yuangon_pack_excerpt": excerpt,
            "recent_failures": failures,
            "context_availability": {
                "yuangon_excerpt": bool(excerpt.strip()),
                "research_pack": bool(research_pack.strip()),
                "execution_failures": bool(failures),
            },
            "employee_id": pkg_id,
            "employee_label": display_name,
            "manifest_signals": signals,
            "other_employees": other_employees,
            "yuangon_area": self.area_for(pkg_id) or "",
            "yuangon_employee_meta": yuangon_meta,
            "role_context": self.role_context(pkg_id),
            "user_question": user_q,
            "all_hands_standby": not bool(user_q),
            "allow_high_risk_real_run": True,
        }
        _hr_gate = (os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN") or "").strip()
        if _hr_gate:
            inp["high_risk_gate_token"] = _hr_gate
        use_standby_bench = self.standby_policy(pkg_id, user_question=user_q)
        llm_tokens = 0
        duration_ms = 0.0
        if use_standby_bench:
            text, cog_err, llm_tokens = await self.standby_report(
                pkg_id=pkg_id,
                display_name=display_name,
                task_text=task_text,
                inp=inp,
                user_id=user_id,
                bench_provider=bench_provider,
                bench_model=bench_model,
            )
            if text:
                text = self.coerce_excerpt(
                    text, {"employee_id": pkg_id, "name": display_name, "area": signals.get("area")}
                )
            completed = datetime.now(timezone.utc).isoformat()
            return {
                "employee_id": pkg_id,
                "name": display_name,
                "area": self.area_for(pkg_id) or "",
                "status": "ok" if text else "model_error" if cog_err else "empty",
                "started_at": started_at,
                "completed_at": completed,
                "report_markdown": text,
                "cognition_error": cog_err[:800],
                "warnings": warns,
                "manifest_signals": signals,
                "recent_failures": failures,
                "research_sources": research_sources,
                "duration_ms": duration_ms,
                "llm_tokens": llm_tokens,
                "report_mode": "standby_manifest_bench",
            }

        def _run() -> Dict[str, Any]:
            return self.execute(
                pkg_id, task_text, inp, user_id, bench_llm_override=(bench_provider, bench_model)
            )

        out: Dict[str, Any] = {}
        try:
            from modstore_server.employee_executor import _is_transient_llm_error

            for attempt in range(3):
                out = await asyncio.to_thread(_run)
                cog_err = str(out.get("cognition_error") or "").strip()
                cog_err_lower = cog_err.lower()
                if (
                    attempt < 2
                    and cog_err
                    and (
                        "429" in cog_err_lower
                        or "rate limit" in cog_err_lower
                        or "too many requests" in cog_err_lower
                        or _is_transient_llm_error(cog_err)
                    )
                ):
                    await asyncio.sleep(2.5 * (attempt + 1))
                    continue
                break
        except RECOVERABLE_ERRORS as exc:
            logger.exception("all_hands employee execute failed pkg_id=%s", pkg_id)
            return {
                "employee_id": pkg_id,
                "name": display_name,
                "area": self.area_for(pkg_id) or "",
                "status": "error",
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "report_markdown": "",
                "cognition_error": str(exc)[:800],
                "warnings": warns + [f"执行抛异常：{exc}"[:200]],
                "manifest_signals": signals,
                "recent_failures": failures,
                "research_sources": research_sources,
            }
        text = (out.get("reasoning_excerpt") or "").strip()
        if inp.get("all_hands_standby"):
            text = self.coerce_excerpt(
                text,
                {"employee_id": pkg_id, "name": display_name, "area": self.area_for(pkg_id) or ""},
            )
        cog_err = (out.get("cognition_error") or "").strip()
        return {
            "employee_id": pkg_id,
            "name": display_name,
            "area": self.area_for(pkg_id) or "",
            "status": "ok" if text else "model_error" if cog_err else "empty",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "report_markdown": text,
            "cognition_error": cog_err[:800],
            "warnings": warns,
            "manifest_signals": signals,
            "recent_failures": failures,
            "research_sources": research_sources,
            "duration_ms": float(out.get("duration_ms") or 0.0),
            "llm_tokens": int(out.get("llm_tokens") or 0),
        }
