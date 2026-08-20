"""Employee execution transaction phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _execute_employee_phase_02(state):
    if isinstance(state["reasoning"], dict):
        _llm_out_raw = state["reasoning"].get("reasoning") or ""
        _parsed_llm: _facade().Dict[str, _facade().Any] = {}
        if isinstance(_llm_out_raw, str) and _llm_out_raw.strip():
            try:
                _parsed_llm = _facade().json.loads(_llm_out_raw) or {}
            except (ValueError, TypeError):
                _parsed_llm = {}
            if not isinstance(_parsed_llm, dict):
                import re as _re

                _m = _re.search("```(?:json)?\\s*(\\{.*\\})\\s*```", _llm_out_raw, _re.DOTALL)
                if _m:
                    try:
                        _parsed_llm = _facade().json.loads(_m.group(1)) or {}
                    except (ValueError, TypeError):
                        _parsed_llm = {}
            if not isinstance(_parsed_llm, dict):
                _stripped = _llm_out_raw.strip()
                if _stripped.startswith("```"):
                    _stripped = _re.sub("^```(?:json)?\\s*", "", _stripped)
                    _stripped = _re.sub("\\s*```\\s*$", "", _stripped)
                    try:
                        _parsed_llm = _facade().json.loads(_stripped) or {}
                    except (ValueError, TypeError):
                        _parsed_llm = {}
            if not isinstance(_parsed_llm, dict):
                import re as _re

                _m2 = _re.search('\\{[^{}]*\\"requires_human\\"[^{}]*\\}', _llm_out_raw, _re.DOTALL)
                if _m2:
                    try:
                        _parsed_llm = _facade().json.loads(_m2.group(0)) or {}
                    except (ValueError, TypeError):
                        _parsed_llm = {}
        _ask_human = None
        _human_question_text = ""
        if isinstance(_parsed_llm, dict):
            _ask_human = _parsed_llm.get("requires_human") or _parsed_llm.get("ask_human")
            _human_question_text = str(
                _parsed_llm.get("human_question") or _parsed_llm.get("question") or ""
            )
        if _ask_human is None:
            _ask_human = state["reasoning"].get("requires_human") or state["reasoning"].get(
                "ask_human"
            )
        if not _human_question_text:
            _human_question_text = str(
                state["reasoning"].get("human_question") or state["reasoning"].get("question") or ""
            )
        _exhausted_flag = None
        _handoff_intended = None
        if isinstance(_parsed_llm, dict):
            _exhausted_flag = _parsed_llm.get("exhausted")
            _handoff_intended = _parsed_llm.get("handoff_to") or _parsed_llm.get("delegate_to")
        if _exhausted_flag is None and isinstance(state["reasoning"], dict):
            _exhausted_flag = state["reasoning"].get("exhausted")
        if _handoff_intended is None and isinstance(state["reasoning"], dict):
            _handoff_intended = state["reasoning"].get("handoff_to") or state["reasoning"].get(
                "delegate_to"
            )
        if _exhausted_flag is True or (
            isinstance(_exhausted_flag, str) and _exhausted_flag.strip()
        ):
            state["reasoning"]["_exhausted"] = {
                "failure_summary": str(
                    (_parsed_llm.get("failure_summary") if isinstance(_parsed_llm, dict) else "")
                    or state["reasoning"].get("failure_summary", "")
                )[:500],
                "skipped_ask_human": True,
            }
            _facade().logger.info(
                "employee_executor exhausted skip ask_human employee_id=%s task=%s",
                state["employee_id"],
                str(state["task"])[:200],
            )
        elif _handoff_intended and (
            _ask_human is True or (isinstance(_ask_human, str) and _ask_human.strip())
        ):
            state["reasoning"]["_ask_human_suppressed_by_handoff"] = True
            _facade().logger.info(
                "employee_executor handoff suppresses ask_human employee_id=%s handoff_to=%s",
                state["employee_id"],
                str(_handoff_intended)[:128],
            )
        elif (
            _ask_human is True or (isinstance(_ask_human, str) and _ask_human.strip())
        ) and _facade()._flag_enabled(state["payload"].get("suppress_human_questions")):
            state["reasoning"]["_ask_human_suppressed"] = "read_only_burn_in"
        elif _ask_human is True or (isinstance(_ask_human, str) and _ask_human.strip()):
            _question_text = (
                _ask_human
                if isinstance(_ask_human, str) and _ask_human.strip()
                else _human_question_text or "需要老板决策"
            )
            try:
                from modstore_server.human_uncertainty_queue import ask_human_blocking

                _resp = ask_human_blocking(
                    employee_id=state["employee_id"],
                    user_id=_facade()._resolve_metric_user_id(state["session"], state["user_id"]),
                    question=_question_text,
                    task=state["task"],
                    context={
                        "perceived": state["perceived"],
                        "reasoning_summary": str(
                            _parsed_llm.get("summary") or state["reasoning"].get("summary", "")
                        )[:500],
                        "llm_parsed": _parsed_llm if isinstance(_parsed_llm, dict) else {},
                    },
                    wait_for_answer=not bool(state["payload"].get("non_blocking_human_questions")),
                )
                state["reasoning"]["_human_answer"] = _resp
                state["reasoning"]["_phase_d_triggered"] = True
                state["reasoning"]["_phase_d_question"] = _question_text[:300]
                if _resp.get("status") == "answered":
                    state["reasoning"]["human_answer"] = _resp.get("answer", "")
            except RECOVERABLE_ERRORS as _exc:
                state["reasoning"]["_human_answer_error"] = str(_exc)
    try:
        _im_body = ""
        if state["reasoning"].get("_phase_d_triggered"):
            _im_q = str(state["reasoning"].get("_phase_d_question") or "").strip()
            if _im_q:
                _im_body = f"🤔 我有个问题想问你：{_im_q}\n\n（已通过任务中心发起，等你在那里回复）"
        if _im_body and (not _facade()._flag_enabled(state["payload"].get("suppress_employee_im"))):
            _facade()._emp_im_notify_boss(
                state["employee_id"], state["manifest"], _im_body, "cognition"
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("cognition im hook skipped", exc_info=True)
    try:
        from modstore_server.employee_handoff import _resolve_target_employee_id, perform_handoff

        _handoff_to_raw = None
        _handoff_reason = ""
        _handoff_context = ""
        if isinstance(_parsed_llm, dict):
            _handoff_to_raw = _parsed_llm.get("handoff_to") or _parsed_llm.get("delegate_to")
            _handoff_reason = str(
                _parsed_llm.get("handoff_reason") or _parsed_llm.get("delegate_reason") or ""
            )
            _handoff_context = str(
                _parsed_llm.get("handoff_context") or _parsed_llm.get("delegate_context") or ""
            )
        if _handoff_to_raw is None and isinstance(state["reasoning"], dict):
            _handoff_to_raw = state["reasoning"].get("handoff_to") or state["reasoning"].get(
                "delegate_to"
            )
            if not _handoff_reason:
                _handoff_reason = str(
                    state["reasoning"].get("handoff_reason")
                    or state["reasoning"].get("delegate_reason")
                    or ""
                )
            if not _handoff_context:
                _handoff_context = str(
                    state["reasoning"].get("handoff_context")
                    or state["reasoning"].get("delegate_context")
                    or ""
                )
        _handoff_target = _resolve_target_employee_id(_handoff_to_raw) if _handoff_to_raw else ""
        if _handoff_target and _facade()._flag_enabled(state["payload"].get("suppress_handoff")):
            state["reasoning"]["_handoff_suppressed"] = {
                "target": _handoff_target,
                "reason": "read_only_burn_in",
            }
            _handoff_target = ""
        if _handoff_target:
            _ctx_parts = []
            if _handoff_context:
                _ctx_parts.append(_handoff_context[:500])
            if isinstance(_parsed_llm, dict) and _parsed_llm.get("summary"):
                _ctx_parts.append(f"LLM 摘要：{str(_parsed_llm.get('summary'))[:300]}")
            _handoff_ctx_str = " | ".join(_ctx_parts)[:1500]
            _handoff_out = perform_handoff(
                source_employee_id=state["employee_id"],
                target_employee_id=_handoff_target,
                reason=_handoff_reason,
                context=_handoff_ctx_str,
                original_task=str(state["task"] or ""),
                extra_payload={
                    "source_employee_id": state["employee_id"],
                    "parsed_llm_excerpt": (
                        str(_llm_out_raw)[:500] if isinstance(_llm_out_raw, str) else ""
                    ),
                },
            )
            if isinstance(state["reasoning"], dict):
                state["reasoning"]["_handoff"] = _handoff_out
    except RECOVERABLE_ERRORS as _ho_exc:
        _facade().logger.debug(
            "handoff perform failed employee_id=%s err=%s", state["employee_id"], _ho_exc
        )
    try:
        if _handoff_target and (
            not _facade()._flag_enabled(state["payload"].get("suppress_employee_im"))
        ):
            _ho_msg = f"🔁 已转交给 {_handoff_target}"
            if _handoff_reason:
                _ho_msg = f"{_ho_msg}：{_handoff_reason[:200]}"
            _ho_msg = f"{_ho_msg}\n（我仍继续做我能做的部分）"
            _facade()._emp_im_notify_boss(
                state["employee_id"], state["manifest"], _ho_msg, "handoff"
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("handoff im hook skipped", exc_info=True)
    state["result"] = _facade()._actions_real(
        state["config"].get("actions", {}),
        state["reasoning"],
        state["task"],
        state["employee_id"],
        state["user_id"],
    )
    try:
        from modstore_server.employee_path_guard import check_path_guard

        _path_guard = check_path_guard(
            config=state["config"],
            result=state["result"] if isinstance(state["result"], dict) else {},
            employee_id=state["employee_id"],
        )
        if isinstance(state["result"], dict):
            state["result"]["path_guard"] = _path_guard
    except RECOVERABLE_ERRORS as _pg_exc:
        _facade().logger.debug(
            "path_guard check failed employee_id=%s err=%s", state["employee_id"], _pg_exc
        )
    try:
        from modstore_server.employee_verification import run_verification

        _verif = run_verification(
            employee_id=state["employee_id"],
            task=state["task"],
            reasoning=state["reasoning"] if isinstance(state["reasoning"], dict) else {},
            result=state["result"] if isinstance(state["result"], dict) else {},
            config=state["config"],
            project_root=_facade().Path(state["_project_root"]) if state["_project_root"] else None,
        )
        if isinstance(state["result"], dict):
            state["result"]["verification"] = _verif
    except RECOVERABLE_ERRORS as _v_exc:
        _facade().logger.debug(
            "verification failed employee_id=%s err=%s", state["employee_id"], _v_exc
        )
    try:
        _verif_dict = _verif if isinstance(_verif, dict) else {}
        _v_status = str(_verif_dict.get("status") or _verif_dict.get("ok") or "").strip()
        _v_summary = str(_verif_dict.get("summary") or _verif_dict.get("message") or "").strip()
        if (_v_status or _v_summary) and (
            not _facade()._flag_enabled(state["payload"].get("suppress_employee_im"))
        ):
            _icon = (
                "✅"
                if _v_status.lower() in ("ok", "passed", "pass", "success", "true")
                else "❌" if _v_status.lower() in ("fail", "failed", "error", "false") else "🔍"
            )
            _verif_body = f"{_icon} 验证：{_v_summary or _v_status}"[:300]
            _facade()._emp_im_notify_boss(
                state["employee_id"], state["manifest"], _verif_body, "verification"
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("verification im hook skipped", exc_info=True)
    try:
        from modstore_server.employee_self_evolution import check_evolution_signal

        _evo = check_evolution_signal(employee_id=state["employee_id"], session=state["session"])
        if isinstance(state["result"], dict):
            state["result"]["evolution_signal"] = _evo
    except RECOVERABLE_ERRORS as _evo_exc:
        _facade().logger.debug(
            "evolution_signal check failed employee_id=%s err=%s", state["employee_id"], _evo_exc
        )
    _ho = state["reasoning"].get("_handoff") if isinstance(state["reasoning"], dict) else None
    if isinstance(_ho, dict) and isinstance(state["result"], dict):
        state["result"]["handoff"] = _ho
    return (False, None)
