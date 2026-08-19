# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def execute_employee_task(
    employee_id: str,
    task: str,
    input_data: _facade().Dict[str, _facade().Any] = None,
    user_id: int = 0,
    *,
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    t0 = _facade().time.perf_counter()
    payload = dict(input_data or {})
    payload.pop("_trusted_duty_contract_execution", None)
    detail_log = _facade()._executor_detail_log_enabled()
    recovery_meta: _facade().Dict[str, _facade().Any] = {}
    _facade().logger.info(
        "employee_execute_start employee_id=%s user_id=%s task_len=%s",
        employee_id,
        user_id,
        len(task or ""),
    )
    sem = _facade()._get_executor_semaphore()
    if sem:
        sem.acquire()
    try:
        sf = _facade().get_session_factory()
        with sf() as session:
            try:
                pack = _facade().load_employee_pack_resolved(session, employee_id)
                (manifest, burn_in_eligibility) = (pack.get("manifest") or {}, {})
                (
                    reviewed_contract,
                    reviewed_manifest,
                ) = _facade()._trusted_system_duty_contract_execution(
                    employee_id, payload, user_id=user_id
                )
                if reviewed_contract and reviewed_manifest:
                    manifest = reviewed_manifest
                    payload["_trusted_duty_contract_execution"] = True
                    payload["work_contract"] = {
                        "schema": "xcagi.duty_employee_work_contracts/v1",
                        "employee_id": employee_id,
                        "mission": str(reviewed_contract.get("mission") or ""),
                        "mode": str(reviewed_contract.get("mode") or ""),
                        "risk_level": str(reviewed_contract.get("risk_level") or ""),
                        "acceptance": list(reviewed_contract.get("acceptance") or []),
                    }
                elif _facade()._flag_enabled(payload.get("burn_in")) and _facade()._flag_enabled(
                    payload.get("burn_in_read_only")
                ):
                    from modstore_server.duty_workforce_burnin import assess_burn_in_eligibility
                    from modstore_server.duty_workforce_contracts import (
                        load_reviewed_duty_manifest,
                        workforce_contract_map,
                    )

                    manifest = load_reviewed_duty_manifest(employee_id)
                    reviewed_contract = workforce_contract_map().get(employee_id) or {}
                    burn_in_eligibility = assess_burn_in_eligibility(
                        employee_id, reviewed_contract, manifest
                    )
                    if burn_in_eligibility.get("eligible") is not True:
                        raise RuntimeError(
                            "duty burn-in eligibility rejected: "
                            + str(burn_in_eligibility.get("reason") or "unknown")
                        )
                    payload["work_contract"] = {
                        "schema": "xcagi.duty_employee_work_contracts/v1",
                        "employee_id": employee_id,
                        "mission": str(reviewed_contract.get("mission") or ""),
                        "mode": str(reviewed_contract.get("mode") or ""),
                        "risk_level": str(reviewed_contract.get("risk_level") or ""),
                        "acceptance": list(reviewed_contract.get("acceptance") or []),
                    }
                config = _facade().parse_employee_config_v2(manifest)
                try:
                    from modstore_server.employee_runtime_policy import apply_policy_to_config

                    (config, runtime_policy) = apply_policy_to_config(employee_id, config)
                except Exception:
                    _facade().logger.debug(
                        "employee runtime policy apply failed employee_id=%s",
                        employee_id,
                        exc_info=True,
                    )
                    runtime_policy = {}
                config = _facade().bind_reviewed_burn_in_handlers(config, burn_in_eligibility)
                actions_section = config.get("actions") or {}
                actions_inner = (
                    actions_section.get("actions")
                    if isinstance(actions_section.get("actions"), dict)
                    else actions_section
                )
                handler_list = list((actions_inner or {}).get("handlers") or [])
                gate = _facade()._evaluate_employee_risk_gate(
                    employee_id, manifest, handler_list, payload
                )
                if not gate.get("ok"):
                    duration_ms = round((_facade().time.perf_counter() - t0) * 1000, 3)
                    session.add(
                        _facade().EmployeeExecutionMetric(
                            user_id=_facade()._resolve_metric_user_id(session, user_id),
                            employee_id=employee_id,
                            task=_facade()._metric_task_preview(task),
                            status="blocked_by_risk_gate",
                            duration_ms=duration_ms,
                            llm_tokens=0,
                        )
                    )
                    session.commit()
                    _facade().logger.info(
                        "employee_execute_finish employee_id=%s user_id=%s status=blocked_by_risk_gate duration_ms=%s",
                        employee_id,
                        user_id,
                        duration_ms,
                    )
                    return {
                        "employee_id": employee_id,
                        "pack": {"id": pack["pack_id"], "version": pack["version"]},
                        "duration_ms": duration_ms,
                        "result": {
                            "task": task,
                            "handlers": handler_list,
                            "outputs": [],
                            "summary": "blocked by risk middleware",
                            "risk_gate": gate,
                        },
                        "executed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                        "llm_tokens": 0,
                        "blocked_by_risk_gate": True,
                        "runtime_policy": runtime_policy or None,
                        "risk_level": gate.get("risk_level"),
                    }
                ctx = _facade().build_employee_context(employee_id, payload)
                perceived = _facade()._perception_real(
                    config.get("perception", {}), payload, session, user_id
                )
                try:
                    from modstore_server.employee_perception_enricher import enrich_perception

                    _project_root = (
                        str(payload.get("project_root") or "").strip()
                        if isinstance(payload, dict)
                        else ""
                    ) or _facade().os.environ.get("MODSTORE_REPO_ROOT", "")
                    enrich_perception(
                        employee_id=employee_id,
                        perceived=perceived if isinstance(perceived, dict) else {},
                        config=config,
                        session=session,
                        project_root=_facade().Path(_project_root) if _project_root else None,
                        manifest=manifest if isinstance(manifest, dict) else None,
                    )
                except Exception as _pe_exc:
                    _facade().logger.debug(
                        "perception_enricher failed employee_id=%s err=%s", employee_id, _pe_exc
                    )
                try:
                    from modstore_server.employee_task_classifier import (
                        enrich_perception_with_classification,
                    )

                    enrich_perception_with_classification(
                        employee_id=employee_id,
                        task=str(task or ""),
                        perceived=perceived if isinstance(perceived, dict) else {},
                    )
                except Exception as _tc_exc:
                    _facade().logger.debug(
                        "task_classifier failed employee_id=%s err=%s", employee_id, _tc_exc
                    )
                file_path_fast = (
                    isinstance(payload, dict)
                    and str(payload.get("file_path") or payload.get("path") or "").strip()
                )
                direct_only = handler_list == ["direct_python"] and bool(
                    file_path_fast
                    or _facade()._deterministic_direct_input_ready(
                        actions_inner if isinstance(actions_inner, dict) else {},
                        payload if isinstance(payload, dict) else {},
                    )
                    or (
                        employee_id == "change-request-auditor"
                        and str(payload.get("handler") or "").strip() == "direct_python"
                    )
                )
                if direct_only:
                    memory: _facade().Dict[str, _facade().Any] = {}
                    reasoning = {
                        "input": dict(payload) if isinstance(payload, dict) else {},
                        "reasoning": "",
                        "skipped_cognition": True,
                    }
                    recovery_meta = {}
                else:
                    memory = _facade()._memory_real(config.get("memory", {}), ctx, session, user_id)
                    (reasoning, recovery_meta) = _facade()._run_cognition_with_transient_retries(
                        config.get("cognition", {}),
                        perceived,
                        memory,
                        session,
                        user_id,
                        employee_id=employee_id,
                        task=task,
                        bench_llm_override=bench_llm_override,
                    )
                reasoning = _facade()._merge_original_input_into_reasoning(
                    reasoning if isinstance(reasoning, dict) else {},
                    payload if isinstance(payload, dict) else {},
                )
                if isinstance(reasoning, dict):
                    _llm_out_raw = reasoning.get("reasoning") or ""
                    _parsed_llm: _facade().Dict[str, _facade().Any] = {}
                    if isinstance(_llm_out_raw, str) and _llm_out_raw.strip():
                        try:
                            _parsed_llm = _facade().json.loads(_llm_out_raw) or {}
                        except (ValueError, TypeError):
                            _parsed_llm = {}
                        if not isinstance(_parsed_llm, dict):
                            import re as _re

                            _m = _re.search(
                                "```(?:json)?\\s*(\\{.*\\})\\s*```", _llm_out_raw, _re.DOTALL
                            )
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

                            _m2 = _re.search(
                                '\\{[^{}]*\\"requires_human\\"[^{}]*\\}', _llm_out_raw, _re.DOTALL
                            )
                            if _m2:
                                try:
                                    _parsed_llm = _facade().json.loads(_m2.group(0)) or {}
                                except (ValueError, TypeError):
                                    _parsed_llm = {}
                    _ask_human = None
                    _human_question_text = ""
                    if isinstance(_parsed_llm, dict):
                        _ask_human = _parsed_llm.get("requires_human") or _parsed_llm.get(
                            "ask_human"
                        )
                        _human_question_text = str(
                            _parsed_llm.get("human_question") or _parsed_llm.get("question") or ""
                        )
                    if _ask_human is None:
                        _ask_human = reasoning.get("requires_human") or reasoning.get("ask_human")
                    if not _human_question_text:
                        _human_question_text = str(
                            reasoning.get("human_question") or reasoning.get("question") or ""
                        )
                    _exhausted_flag = None
                    _handoff_intended = None
                    if isinstance(_parsed_llm, dict):
                        _exhausted_flag = _parsed_llm.get("exhausted")
                        _handoff_intended = _parsed_llm.get("handoff_to") or _parsed_llm.get(
                            "delegate_to"
                        )
                    if _exhausted_flag is None and isinstance(reasoning, dict):
                        _exhausted_flag = reasoning.get("exhausted")
                    if _handoff_intended is None and isinstance(reasoning, dict):
                        _handoff_intended = reasoning.get("handoff_to") or reasoning.get(
                            "delegate_to"
                        )
                    if _exhausted_flag is True or (
                        isinstance(_exhausted_flag, str) and _exhausted_flag.strip()
                    ):
                        reasoning["_exhausted"] = {
                            "failure_summary": str(
                                (
                                    _parsed_llm.get("failure_summary")
                                    if isinstance(_parsed_llm, dict)
                                    else ""
                                )
                                or reasoning.get("failure_summary", "")
                            )[:500],
                            "skipped_ask_human": True,
                        }
                        _facade().logger.info(
                            "employee_executor exhausted skip ask_human employee_id=%s task=%s",
                            employee_id,
                            str(task)[:200],
                        )
                    elif _handoff_intended and (
                        _ask_human is True or (isinstance(_ask_human, str) and _ask_human.strip())
                    ):
                        reasoning["_ask_human_suppressed_by_handoff"] = True
                        _facade().logger.info(
                            "employee_executor handoff suppresses ask_human employee_id=%s handoff_to=%s",
                            employee_id,
                            str(_handoff_intended)[:128],
                        )
                    elif (
                        _ask_human is True or (isinstance(_ask_human, str) and _ask_human.strip())
                    ) and _facade()._flag_enabled(payload.get("suppress_human_questions")):
                        reasoning["_ask_human_suppressed"] = "read_only_burn_in"
                    elif _ask_human is True or (isinstance(_ask_human, str) and _ask_human.strip()):
                        _question_text = (
                            _ask_human
                            if isinstance(_ask_human, str) and _ask_human.strip()
                            else _human_question_text or "需要老板决策"
                        )
                        try:
                            from modstore_server.human_uncertainty_queue import ask_human_blocking

                            _resp = ask_human_blocking(
                                employee_id=employee_id,
                                user_id=_facade()._resolve_metric_user_id(session, user_id),
                                question=_question_text,
                                task=task,
                                context={
                                    "perceived": perceived,
                                    "reasoning_summary": str(
                                        _parsed_llm.get("summary") or reasoning.get("summary", "")
                                    )[:500],
                                    "llm_parsed": (
                                        _parsed_llm if isinstance(_parsed_llm, dict) else {}
                                    ),
                                },
                                wait_for_answer=not bool(
                                    payload.get("non_blocking_human_questions")
                                ),
                            )
                            reasoning["_human_answer"] = _resp
                            reasoning["_phase_d_triggered"] = True
                            reasoning["_phase_d_question"] = _question_text[:300]
                            if _resp.get("status") == "answered":
                                reasoning["human_answer"] = _resp.get("answer", "")
                        except Exception as _exc:
                            reasoning["_human_answer_error"] = str(_exc)
                try:
                    _im_body = ""
                    if reasoning.get("_phase_d_triggered"):
                        _im_q = str(reasoning.get("_phase_d_question") or "").strip()
                        if _im_q:
                            _im_body = f"🤔 我有个问题想问你：{_im_q}\n\n（已通过任务中心发起，等你在那里回复）"
                    if _im_body and (
                        not _facade()._flag_enabled(payload.get("suppress_employee_im"))
                    ):
                        _facade()._emp_im_notify_boss(employee_id, manifest, _im_body, "cognition")
                except Exception:
                    _facade().logger.debug("cognition im hook skipped", exc_info=True)
                try:
                    from modstore_server.employee_handoff import (
                        _resolve_target_employee_id,
                        perform_handoff,
                    )

                    _handoff_to_raw = None
                    _handoff_reason = ""
                    _handoff_context = ""
                    if isinstance(_parsed_llm, dict):
                        _handoff_to_raw = _parsed_llm.get("handoff_to") or _parsed_llm.get(
                            "delegate_to"
                        )
                        _handoff_reason = str(
                            _parsed_llm.get("handoff_reason")
                            or _parsed_llm.get("delegate_reason")
                            or ""
                        )
                        _handoff_context = str(
                            _parsed_llm.get("handoff_context")
                            or _parsed_llm.get("delegate_context")
                            or ""
                        )
                    if _handoff_to_raw is None and isinstance(reasoning, dict):
                        _handoff_to_raw = reasoning.get("handoff_to") or reasoning.get(
                            "delegate_to"
                        )
                        if not _handoff_reason:
                            _handoff_reason = str(
                                reasoning.get("handoff_reason")
                                or reasoning.get("delegate_reason")
                                or ""
                            )
                        if not _handoff_context:
                            _handoff_context = str(
                                reasoning.get("handoff_context")
                                or reasoning.get("delegate_context")
                                or ""
                            )
                    _handoff_target = (
                        _resolve_target_employee_id(_handoff_to_raw) if _handoff_to_raw else ""
                    )
                    if _handoff_target and _facade()._flag_enabled(payload.get("suppress_handoff")):
                        reasoning["_handoff_suppressed"] = {
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
                            source_employee_id=employee_id,
                            target_employee_id=_handoff_target,
                            reason=_handoff_reason,
                            context=_handoff_ctx_str,
                            original_task=str(task or ""),
                            extra_payload={
                                "source_employee_id": employee_id,
                                "parsed_llm_excerpt": (
                                    str(_llm_out_raw)[:500] if isinstance(_llm_out_raw, str) else ""
                                ),
                            },
                        )
                        if isinstance(reasoning, dict):
                            reasoning["_handoff"] = _handoff_out
                except Exception as _ho_exc:
                    _facade().logger.debug(
                        "handoff perform failed employee_id=%s err=%s", employee_id, _ho_exc
                    )
                try:
                    if _handoff_target and (
                        not _facade()._flag_enabled(payload.get("suppress_employee_im"))
                    ):
                        _ho_msg = f"🔁 已转交给 {_handoff_target}"
                        if _handoff_reason:
                            _ho_msg = f"{_ho_msg}：{_handoff_reason[:200]}"
                        _ho_msg = f"{_ho_msg}\n（我仍继续做我能做的部分）"
                        _facade()._emp_im_notify_boss(employee_id, manifest, _ho_msg, "handoff")
                except Exception:
                    _facade().logger.debug("handoff im hook skipped", exc_info=True)
                result = _facade()._actions_real(
                    config.get("actions", {}), reasoning, task, employee_id, user_id
                )
                try:
                    from modstore_server.employee_path_guard import check_path_guard

                    _path_guard = check_path_guard(
                        config=config,
                        result=result if isinstance(result, dict) else {},
                        employee_id=employee_id,
                    )
                    if isinstance(result, dict):
                        result["path_guard"] = _path_guard
                except Exception as _pg_exc:
                    _facade().logger.debug(
                        "path_guard check failed employee_id=%s err=%s", employee_id, _pg_exc
                    )
                try:
                    from modstore_server.employee_verification import run_verification

                    _verif = run_verification(
                        employee_id=employee_id,
                        task=task,
                        reasoning=reasoning if isinstance(reasoning, dict) else {},
                        result=result if isinstance(result, dict) else {},
                        config=config,
                        project_root=_facade().Path(_project_root) if _project_root else None,
                    )
                    if isinstance(result, dict):
                        result["verification"] = _verif
                except Exception as _v_exc:
                    _facade().logger.debug(
                        "verification failed employee_id=%s err=%s", employee_id, _v_exc
                    )
                try:
                    _verif_dict = _verif if isinstance(_verif, dict) else {}
                    _v_status = str(
                        _verif_dict.get("status") or _verif_dict.get("ok") or ""
                    ).strip()
                    _v_summary = str(
                        _verif_dict.get("summary") or _verif_dict.get("message") or ""
                    ).strip()
                    if (_v_status or _v_summary) and (
                        not _facade()._flag_enabled(payload.get("suppress_employee_im"))
                    ):
                        _icon = (
                            "✅"
                            if _v_status.lower() in ("ok", "passed", "pass", "success", "true")
                            else (
                                "❌"
                                if _v_status.lower() in ("fail", "failed", "error", "false")
                                else "🔍"
                            )
                        )
                        _verif_body = f"{_icon} 验证：{_v_summary or _v_status}"[:300]
                        _facade()._emp_im_notify_boss(
                            employee_id, manifest, _verif_body, "verification"
                        )
                except Exception:
                    _facade().logger.debug("verification im hook skipped", exc_info=True)
                try:
                    from modstore_server.employee_self_evolution import check_evolution_signal

                    _evo = check_evolution_signal(employee_id=employee_id, session=session)
                    if isinstance(result, dict):
                        result["evolution_signal"] = _evo
                except Exception as _evo_exc:
                    _facade().logger.debug(
                        "evolution_signal check failed employee_id=%s err=%s", employee_id, _evo_exc
                    )
                _ho = reasoning.get("_handoff") if isinstance(reasoning, dict) else None
                if isinstance(_ho, dict) and isinstance(result, dict):
                    result["handoff"] = _ho
                duration_ms = round((_facade().time.perf_counter() - t0) * 1000, 3)
                llm_tokens = 0 if direct_only else _facade()._extract_token_count(reasoning)
                handler_ok = _facade()._handlers_execution_ok(
                    result if isinstance(result, dict) else {}
                )
                burn_in_acceptance: _facade().Dict[str, _facade().Any] = {}
                if _facade()._flag_enabled(payload.get("burn_in")):
                    try:
                        burn_in_deadline = float(payload.get("burn_in_deadline_epoch") or 0)
                    except (TypeError, ValueError):
                        burn_in_deadline = 0.0
                    if burn_in_deadline > 0 and _facade().time.time() > burn_in_deadline:
                        burn_in_acceptance = {
                            "passed": False,
                            "reasons": ["orchestration_deadline_exceeded"],
                        }
                    else:
                        try:
                            from modstore_server.duty_workforce_burnin import (
                                validate_burn_in_execution_result,
                            )

                            burn_in_acceptance = validate_burn_in_execution_result(
                                {"result": result if isinstance(result, dict) else {}}
                            )
                        except Exception as exc:
                            burn_in_acceptance = {
                                "passed": False,
                                "reasons": [f"acceptance_gate_error:{type(exc).__name__}"],
                            }
                    if isinstance(result, dict):
                        result["burn_in_acceptance"] = burn_in_acceptance
                    if burn_in_acceptance.get("passed") is not True:
                        handler_ok = False
                exec_status = (
                    "success"
                    if handler_ok
                    else "burnin_rejected" if burn_in_acceptance else "handler_failed"
                )
                if handler_ok:
                    metric_error = ""
                elif burn_in_acceptance:
                    metric_error = "burn-in acceptance: " + ";".join(
                        (str(item) for item in burn_in_acceptance.get("reasons") or [])
                    )
                else:
                    metric_error = _facade()._handler_failure_detail(
                        result if isinstance(result, dict) else {}
                    )
                metric_failure_kind = ""
                _pg = result.get("path_guard") if isinstance(result, dict) else None
                if isinstance(_pg, dict) and _pg.get("checked") and (not _pg.get("ok")):
                    exec_status = "blocked_by_path_guard"
                    violations = _pg.get("violations") or []
                    vstr = "; ".join(
                        (
                            f"{v.get('path', '')}({v.get('reason', '')})"
                            for v in violations[:5]
                            if isinstance(v, dict)
                        )
                    )
                    metric_error = f"path_guard violations: {vstr}"[:500]
                    metric_failure_kind = "path_guard_violation"
                    handler_ok = False
                try:
                    from modstore_server.employee_human_report import build_human_report

                    _human_report = build_human_report(
                        employee_id=employee_id,
                        task=task,
                        reasoning=reasoning if isinstance(reasoning, dict) else {},
                        result=result if isinstance(result, dict) else {},
                        duration_ms=duration_ms,
                        llm_tokens=llm_tokens,
                        exec_status=exec_status,
                        perceived=perceived if isinstance(perceived, dict) else None,
                        memory=memory if isinstance(memory, dict) else None,
                        cognition_error=(
                            str(reasoning.get("error") or "") if isinstance(reasoning, dict) else ""
                        ),
                    )
                    if isinstance(result, dict):
                        result["human_report"] = _human_report
                except Exception as _hr_exc:
                    _facade().logger.debug(
                        "build_human_report failed employee_id=%s err=%s", employee_id, _hr_exc
                    )
                if not handler_ok:
                    cog_err = (
                        str(reasoning.get("error") or "").strip()
                        if isinstance(reasoning, dict)
                        else ""
                    )
                    cog_status = reasoning.get("status") if isinstance(reasoning, dict) else None
                    metric_failure_kind = _facade().classify_failure_kind(
                        cog_err or metric_error, cog_status
                    )
                    if cog_err:
                        metric_error = f"{metric_error}; cognition_error={cog_err[:500]}"
                session.add(
                    _facade().EmployeeExecutionMetric(
                        user_id=_facade()._resolve_metric_user_id(session, user_id),
                        employee_id=employee_id,
                        task=_facade()._metric_task_preview(task),
                        status=exec_status,
                        duration_ms=duration_ms,
                        llm_tokens=llm_tokens,
                        error=metric_error,
                        failure_kind=metric_failure_kind,
                    )
                )
                session.commit()
                if not handler_ok:
                    suppress_lifecycle_events = isinstance(payload, dict) and str(
                        payload.get("suppress_lifecycle_events") or ""
                    ).strip().lower() in {"1", "true", "yes", "on"}
                    if not suppress_lifecycle_events:
                        try:
                            from modstore_server.notification_service import (
                                notify_employee_execution_done,
                            )

                            notify_employee_execution_done(user_id, employee_id, task, exec_status)
                        except Exception:
                            pass
                    return {
                        "employee_id": employee_id,
                        "pack": {"id": pack["pack_id"], "version": pack["version"]},
                        "duration_ms": duration_ms,
                        "result": result,
                        "executed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                        "llm_tokens": llm_tokens,
                        "handler_failed": True,
                        "runtime_policy": runtime_policy or None,
                    }
                if recovery_meta.get("recovered"):
                    try:
                        from modstore_server.services.change_signal import (
                            emit_execution_recovery_event,
                        )

                        emit_execution_recovery_event(
                            employee_id,
                            task,
                            recovery_action=str(
                                recovery_meta.get("recovery_action") or "cognition_retry"
                            ),
                            success=True,
                            original_error=str(recovery_meta.get("original_error") or ""),
                            attempts=int(recovery_meta.get("attempts") or 0),
                        )
                    except Exception:
                        _facade().logger.debug(
                            "emit_execution_recovery_event failed", exc_info=True
                        )
                if _facade()._flag_enabled(payload.get("suppress_change_requests")):
                    cr_bridge = {
                        "ok": True,
                        "suppressed": True,
                        "reason": "read_only_burn_in",
                        "change_request_ids": [],
                    }
                else:
                    cr_bridge = _facade()._auto_wrap_execution_result_to_change_requests(
                        employee_id,
                        user_id,
                        payload if isinstance(payload, dict) else {},
                        result if isinstance(result, dict) else {},
                    )
                if isinstance(result, dict):
                    result["change_request_bridge"] = cr_bridge
                    cids = (
                        cr_bridge.get("change_request_ids")
                        if isinstance(cr_bridge.get("change_request_ids"), list)
                        else []
                    )
                    if cids:
                        normalized_cids: _facade().List[int] = []
                        for x in cids:
                            try:
                                _cid = int(x or 0)
                            except (TypeError, ValueError):
                                _cid = 0
                            if _cid > 0:
                                normalized_cids.append(_cid)
                        result["change_request_ids"] = normalized_cids
                if not _facade()._flag_enabled(payload.get("suppress_lifecycle_events")):
                    try:
                        from modstore_server.notification_service import (
                            notify_employee_execution_done,
                        )

                        notify_employee_execution_done(user_id, employee_id, task, "success")
                    except Exception:
                        pass
                try:
                    from modstore_server.models_project_context import record_execution_outcome

                    record_execution_outcome(
                        employee_id=employee_id,
                        task=task,
                        input_data=payload if isinstance(payload, dict) else {},
                        outcome=result if isinstance(result, dict) else {},
                        status="success",
                    )
                except Exception:
                    pass
                suppress_lifecycle_events = isinstance(payload, dict) and str(
                    payload.get("suppress_lifecycle_events") or ""
                ).strip().lower() in {"1", "true", "yes", "on"}
                if not suppress_lifecycle_events:
                    try:
                        from modstore_server.services.change_signal import (
                            emit_signal_on_execution_complete,
                            emit_task_lifecycle_event,
                        )

                        emit_signal_on_execution_complete(
                            employee_id, task, {"status": "success", "result": result}
                        )
                        emit_task_lifecycle_event(
                            employee_id, task, status="success", result={"result": result}
                        )
                    except Exception:
                        pass
                cog_err = ""
                if isinstance(reasoning, dict):
                    cog_err = str(reasoning.get("error") or "").strip()
                rex = ""
                if isinstance(reasoning, dict):
                    rex = str(reasoning.get("reasoning") or "").strip()[:4000]
                cog_attempts = (
                    int(recovery_meta.get("attempts") or 1) if recovery_meta.get("recovered") else 1
                )
                if detail_log:
                    _facade().logger.info(
                        "employee_execute_finish employee_id=%s user_id=%s status=success duration_ms=%s llm_tokens=%s cognition_attempts=%s handlers=%s",
                        employee_id,
                        user_id,
                        duration_ms,
                        llm_tokens,
                        cog_attempts,
                        ",".join(handler_list),
                    )
                else:
                    _facade().logger.info(
                        "employee_execute_finish employee_id=%s user_id=%s status=success duration_ms=%s llm_tokens=%s cognition_attempts=%s",
                        employee_id,
                        user_id,
                        duration_ms,
                        llm_tokens,
                        cog_attempts,
                    )
                return {
                    "employee_id": employee_id,
                    "pack": {"id": pack["pack_id"], "version": pack["version"]},
                    "duration_ms": duration_ms,
                    "result": result,
                    "executed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                    "llm_tokens": llm_tokens,
                    "runtime_policy": runtime_policy or None,
                    "cognition_error": cog_err or None,
                    "cognition_help": (
                        "LLM 未返回有效内容。请检查 API Key、模型名、网络与平台余额。"
                        if cog_err
                        else None
                    ),
                    "reasoning_excerpt": rex or None,
                    "change_request_ids": (
                        result.get("change_request_ids")
                        if isinstance(result, dict)
                        and isinstance(result.get("change_request_ids"), list)
                        else []
                    ),
                }
            except Exception as e:
                duration_ms = round((_facade().time.perf_counter() - t0) * 1000, 3)
                err_text = str(e)
                failure_kind = _facade().classify_failure_kind(err_text)
                session.add(
                    _facade().EmployeeExecutionMetric(
                        user_id=_facade()._resolve_metric_user_id(session, user_id),
                        employee_id=employee_id,
                        task=_facade()._metric_task_preview(task),
                        status="failed",
                        duration_ms=duration_ms,
                        llm_tokens=0,
                        error=err_text,
                        failure_kind=failure_kind,
                    )
                )
                session.commit()
                if failure_kind == _facade().FAILURE_KIND_QUOTA:
                    _facade().logger.warning(
                        "employee_execute_finish employee_id=%s user_id=%s status=failed failure_kind=quota duration_ms=%s error=%s (配额/计费失败，非 prompt 问题，不应触发自进化 prompt 重写)",
                        employee_id,
                        user_id,
                        duration_ms,
                        err_text[:400],
                    )
                else:
                    _facade().logger.info(
                        "employee_execute_finish employee_id=%s user_id=%s status=failed failure_kind=%s duration_ms=%s error=%s",
                        employee_id,
                        user_id,
                        failure_kind or "unknown",
                        duration_ms,
                        err_text[:400],
                    )
                if not _facade()._flag_enabled(payload.get("suppress_lifecycle_events")):
                    try:
                        from modstore_server.notification_service import (
                            notify_employee_execution_done,
                        )

                        if user_id:
                            notify_employee_execution_done(user_id, employee_id, task, "failed")
                    except Exception:
                        pass
                try:
                    from modstore_server.models_project_context import record_execution_outcome

                    record_execution_outcome(
                        employee_id=employee_id,
                        task=task,
                        input_data=payload if isinstance(payload, dict) else {},
                        outcome={"error": str(e)},
                        status="failed",
                    )
                except Exception:
                    pass
                suppress_lifecycle_events = isinstance(payload, dict) and str(
                    payload.get("suppress_lifecycle_events") or ""
                ).strip().lower() in {"1", "true", "yes", "on"}
                if not suppress_lifecycle_events:
                    try:
                        from modstore_server.services.change_signal import emit_task_lifecycle_event

                        emit_task_lifecycle_event(employee_id, task, status="failed", error=str(e))
                    except Exception:
                        pass
                raise
    finally:
        if sem:
            sem.release()


def get_employee_status(employee_id: str) -> _facade().Dict[str, _facade().Any]:
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().EmployeeExecutionMetric)
            .filter(_facade().EmployeeExecutionMetric.employee_id == employee_id)
            .order_by(_facade().EmployeeExecutionMetric.id.desc())
            .limit(100)
            .all()
        )
        ok = len([r for r in rows if r.status == "success"])
        return {
            "status": "active",
            "employee_id": employee_id,
            "execution_stats": {
                "total_executions": len(rows),
                "success_count": ok,
                "failed_count": len(rows) - ok,
                "success_rate": ok / len(rows) * 100.0 if rows else 0,
            },
            "last_execution": rows[0].created_at.isoformat() if rows else None,
        }
