# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.all_hands_report")


async def synthesize_meeting_minutes(
    *, report: _facade().Dict[str, _facade().Any], user_id: int
) -> _facade().Dict[str, _facade().Any]:
    """将已成功生成的 ``build_all_hands_report`` 结果压缩为五段式「会议摘要」正文。

    返回 ``{ text, generated_at, model, error }``；失败时 ``text`` 可为空且 ``error`` 非空。
    """
    started_at = _facade().datetime.now(_facade().timezone.utc).isoformat()
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
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
    employees: _facade().List[_facade().Dict[str, _facade().Any]] = (
        raw_emp if isinstance(raw_emp, list) else []
    )
    parts: _facade().List[str] = []
    for row in employees:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("employee_id") or "").strip()
        name = str(row.get("name") or eid).strip()
        if not eid:
            continue
        excerpt = _facade()._employee_answer_excerpt(row, max_chars=1200)
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
                if isinstance(row, dict)
                and str(row.get("employee_id") or "") in _facade().CRAFT_WORKSHOP_STANDBY_IDS
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
        {"role": "system", "content": _facade()._MEETING_MINUTES_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = _facade().get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db, int(user_id or 0), bench_provider, bench_model, messages, max_tokens=2048
            )
    except Exception as exc:
        _facade().logger.exception("synthesize_meeting_minutes dispatch failed")
        return {
            "text": "",
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": f"调用 bench LLM 异常：{exc}",
        }
    if not isinstance(result, dict) or not result.get("ok"):
        err = ""
        if isinstance(result, dict):
            err = str(result.get("error") or "").strip()
        return {
            "text": "",
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": err or "bench LLM 未返回有效内容",
        }
    md = str(result.get("content") or "").strip()
    if not md:
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            msg0 = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg0, dict):
                md = str(msg0.get("content") or "").strip()
    return {
        "text": md,
        "generated_at": started_at,
        "model": f"{bench_provider}/{bench_model}",
        "error": "" if md else "bench LLM 返回为空",
    }


async def build_all_hands_report(
    *,
    employee_ids: _facade().Optional[_facade().List[str]] = None,
    max_employees: int = 8,
    with_research: bool = True,
    user_id: int = 0,
    concurrency: int = 2,
    progress_cb: _facade().Optional[_facade().AllHandsProgressCallback] = None,
    user_question: _facade().Optional[str] = None,
    synthesize: bool = False,
) -> _facade().Dict[str, _facade().Any]:
    """全员汇报主入口。返回结构化 JSON，前端直接渲染。

    - ``employee_ids`` 为空时：取 ``duty_roster`` ∩ ``catalog`` 全集，按 ``pkg_id`` 排序；
    - ``concurrency`` 默认 2，避免一次性把平台 LLM Bench 配额打满；
    - 不抛异常：单个员工失败时 ``status='error'``，整体仍返回。
    """

    async def _emit_progress(payload: _facade().Dict[str, _facade().Any]) -> None:
        if not progress_cb:
            return
        try:
            await progress_cb(payload)
        except Exception as exc:
            _facade().logger.debug("all_hands progress callback failed: %s", exc)

    started_at = _facade().datetime.now(_facade().timezone.utc).isoformat()
    pairs = _facade()._resolve_employee_pairs(employee_ids, max_employees=max_employees)
    await _emit_progress(
        {
            "stage": "prepare",
            "total": len(pairs),
            "completed": 0,
            "ok": 0,
            "error": 0,
            "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
    )
    if not pairs:
        return {
            "ok": False,
            "error": "无可汇报员工：duty_roster 与 catalog 交集为空",
            "started_at": started_at,
            "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            "employees": [],
            "summary": {},
        }
    (bench_prov, bench_mdl) = _facade().resolve_platform_bench_llm()
    if not bench_prov or not bench_mdl:
        return {
            "ok": False,
            "error": "平台 Bench LLM 未配置（MODSTORE_EMPLOYEE_BENCH_* 或平台 Key）",
            "started_at": started_at,
            "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            "employees": [],
            "summary": {},
        }
    other_ids = [pid for (pid, _) in pairs]
    sem = _facade().asyncio.Semaphore(max(1, min(concurrency, 4)))
    stagger_sec = float(_facade().os.environ.get("MODSTORE_ALL_HANDS_STAGGER_SEC", "1.0") or "1.0")
    stagger_lock = _facade().asyncio.Lock()
    stagger_seq = 0
    done_lock = _facade().asyncio.Lock()
    done_count = 0
    done_ok = 0
    done_error = 0
    employee_timeout = _facade().all_hands_employee_timeout_sec()

    async def _wrapped(pid: str, name: str) -> _facade().Dict[str, _facade().Any]:
        nonlocal done_count, done_ok, done_error, stagger_seq
        async with sem:
            if stagger_sec > 0 and len(pairs) > 4:
                async with stagger_lock:
                    idx = stagger_seq
                    stagger_seq += 1
                await _facade().asyncio.sleep(min(idx * stagger_sec * 0.25, 6.0))
            try:
                row = await _facade().asyncio.wait_for(
                    _facade()._report_one_employee(
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
            except _facade().asyncio.TimeoutError:
                row = {
                    "employee_id": pid,
                    "name": name,
                    "area": _facade().yuangon_area_for_pkg(pid) or "",
                    "status": "error",
                    "started_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                    "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                    "report_markdown": "",
                    "cognition_error": f"单员工汇报超时（>{int(employee_timeout)}s）",
                    "warnings": [f"超时 {int(employee_timeout)}s，已跳过该员工继续大会"],
                    "manifest_signals": _facade()._manifest_signals(pid),
                    "recent_failures": _facade()._recent_failures(pid),
                    "research_sources": [],
                }
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
                "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            }
        )
        return row

    employees = await _facade().asyncio.gather(*[_wrapped(p, n) for (p, n) in pairs])
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
            "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
    )
    synthesized_answer: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    if synthesize and (user_question or "").strip():
        await _emit_progress(
            {
                "stage": "synthesize",
                "total": len(employees),
                "completed": len(employees),
                "ok": ok_count,
                "error": error_count,
                "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            }
        )
        synthesized_answer = await _facade().synthesize_all_hands_answer(
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
        "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        "employees": employees,
        "summary": summary,
        "synthesized_answer": synthesized_answer,
    }


def all_hands_concurrency_default() -> int:
    """允许通过环境变量覆盖的默认并发上限。"""
    raw = (_facade().os.environ.get("MODSTORE_ALL_HANDS_CONCURRENCY") or "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 4))
    return 2
