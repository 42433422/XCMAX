"""Coordinate bounded employee reports and aggregate progress and optional synthesis."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from modstore_server.all_hands_ports import (
    AllHandsProgressCallback,
    AnswerSynthesizer,
    EmployeePairResolver,
    EmployeeReport,
    JsonObject,
)
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AllHandsCoordinator:
    employee_pairs: EmployeePairResolver
    bench_model: Callable[[], tuple[str, str] | tuple[None, None]]
    report_employee: EmployeeReport
    synthesize: AnswerSynthesizer
    employee_timeout: Callable[[], float]
    area_for: Callable[[str], str | None]
    manifest: Callable[[str], JsonObject]
    failures: Callable[[str], list[JsonObject]]

    async def build(
        self,
        *,
        employee_ids: Optional[List[str]] = None,
        max_employees: int = 8,
        with_research: bool = True,
        user_id: int = 0,
        concurrency: int = 2,
        progress_cb: Optional[AllHandsProgressCallback] = None,
        user_question: Optional[str] = None,
        synthesize: bool = False,
    ) -> Dict[str, Any]:
        """全员汇报主入口。返回结构化 JSON，前端直接渲染。

        - ``employee_ids`` 为空时：取 ``duty_roster`` ∩ ``catalog`` 全集，按 ``pkg_id`` 排序；
        - ``concurrency`` 默认 2，避免一次性把平台 LLM Bench 配额打满；
        - 不抛异常：单个员工失败时 ``status='error'``，整体仍返回。
        """

        async def _emit_progress(payload: Dict[str, Any]) -> None:
            if not progress_cb:
                return
            try:
                await progress_cb(payload)
            except RECOVERABLE_ERRORS as exc:
                logger.debug("all_hands progress callback failed: %s", exc)

        started_at = datetime.now(timezone.utc).isoformat()
        pairs = self.employee_pairs(employee_ids, max_employees=max_employees)
        await _emit_progress(
            {
                "stage": "prepare",
                "total": len(pairs),
                "completed": 0,
                "ok": 0,
                "error": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if not pairs:
            return {
                "ok": False,
                "error": "无可汇报员工：duty_roster 与 catalog 交集为空",
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "employees": [],
                "summary": {},
            }
        bench_prov, bench_mdl = self.bench_model()
        if not bench_prov or not bench_mdl:
            return {
                "ok": False,
                "error": "平台 Bench LLM 未配置（MODSTORE_EMPLOYEE_BENCH_* 或平台 Key）",
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "employees": [],
                "summary": {},
            }
        other_ids = [pid for pid, _ in pairs]
        sem = asyncio.Semaphore(max(1, min(concurrency, 4)))
        stagger_sec = float(os.environ.get("MODSTORE_ALL_HANDS_STAGGER_SEC", "1.0") or "1.0")
        stagger_lock = asyncio.Lock()
        stagger_seq = 0
        done_lock = asyncio.Lock()
        done_count = 0
        done_ok = 0
        done_error = 0
        employee_timeout = self.employee_timeout()

        async def _wrapped(pid: str, name: str) -> Dict[str, Any]:
            nonlocal done_count, done_ok, done_error, stagger_seq
            async with sem:
                if stagger_sec > 0 and len(pairs) > 4:
                    async with stagger_lock:
                        idx = stagger_seq
                        stagger_seq += 1
                    await asyncio.sleep(min(idx * stagger_sec * 0.25, 6.0))
                try:
                    row = await asyncio.wait_for(
                        self.report_employee(
                            pkg_id=pid,
                            display_name=name,
                            other_employees=[x for x in other_ids if x != pid],
                            user_id=user_id,
                            bench_provider=bench_prov,
                            bench_model=bench_mdl,
                            with_research=with_research,
                            user_question=user_question,
                        ),
                        timeout=employee_timeout,
                    )
                except asyncio.TimeoutError:
                    row = self._error_row(
                        pid,
                        name,
                        f"单员工汇报超时（>{int(employee_timeout)}s）",
                        [f"超时 {int(employee_timeout)}s，已跳过该员工继续大会"],
                    )
                except BOUNDARY_ERRORS as exc:
                    # Each employee is a plugin task boundary. Cancellation and
                    # process-level BaseException signals continue to propagate.
                    logger.exception("all_hands employee report failed pkg_id=%s", pid)
                    row = self._error_row(pid, name, str(exc)[:800], [f"汇报失败：{exc}"[:200]])
            status = str(row.get("status") or "")
            async with done_lock:
                done_count += 1
                if status == "ok":
                    done_ok += 1
                elif status in {"error", "model_error", "empty"}:
                    done_error += 1
                snap_done = done_count
                snap_ok = done_ok
                snap_error = done_error
            await _emit_progress(
                {
                    "stage": "employee_done",
                    "employee_id": pid,
                    "employee_name": name,
                    "employee_status": status,
                    "total": len(pairs),
                    "completed": snap_done,
                    "ok": snap_ok,
                    "error": snap_error,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return row

        tasks = [asyncio.create_task(_wrapped(pid, name)) for pid, name in pairs]
        try:
            employees = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        ok_count = sum((1 for e in employees if e.get("status") == "ok"))
        error_count = sum(
            (1 for e in employees if e.get("status") in {"error", "model_error", "empty"})
        )
        summary = {
            "total": len(employees),
            "ok": ok_count,
            "error": error_count,
            "with_research": bool(with_research),
            "bench_provider": bench_prov,
            "bench_model": bench_mdl,
            "user_question": (user_question or "").strip(),
            "synthesized": False,
        }
        await _emit_progress(
            {
                "stage": "completed",
                "total": len(employees),
                "completed": len(employees),
                "ok": ok_count,
                "error": error_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        synthesized_answer: Optional[Dict[str, Any]] = None
        if synthesize and (user_question or "").strip():
            await _emit_progress(
                {
                    "stage": "synthesize",
                    "total": len(employees),
                    "completed": len(employees),
                    "ok": ok_count,
                    "error": error_count,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            synthesized_answer = await self.synthesize(
                user_question=user_question or "",
                employees=employees,
                bench_provider=bench_prov,
                bench_model=bench_mdl,
                user_id=user_id,
            )
            summary["synthesized"] = bool(
                synthesized_answer
                and (synthesized_answer.get("markdown") or "").strip()
                and (not (synthesized_answer.get("error") or "").strip())
            )
        return {
            "ok": True,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "employees": employees,
            "summary": summary,
            "synthesized_answer": synthesized_answer,
        }

    def _error_row(
        self, employee_id: str, name: str, error: str, warnings: list[str]
    ) -> JsonObject:
        """Keep an employee failure report usable when its fact source is also down."""
        area = ""
        manifest: JsonObject = {}
        failures: list[JsonObject] = []
        try:
            area = self.area_for(employee_id) or ""
        except RECOVERABLE_ERRORS as exc:
            warnings.append(f"岗位信息读取失败：{exc}"[:200])
        try:
            manifest = self.manifest(employee_id)
        except RECOVERABLE_ERRORS as exc:
            warnings.append(f"员工元数据读取失败：{exc}"[:200])
        try:
            failures = self.failures(employee_id)
        except RECOVERABLE_ERRORS as exc:
            warnings.append(f"执行流水读取失败：{exc}"[:200])
        timestamp = datetime.now(timezone.utc).isoformat()
        return {
            "employee_id": employee_id,
            "name": name,
            "area": area,
            "status": "error",
            "started_at": timestamp,
            "completed_at": timestamp,
            "report_markdown": "",
            "cognition_error": error,
            "warnings": warnings,
            "manifest_signals": manifest,
            "recent_failures": failures,
            "research_sources": [],
        }
