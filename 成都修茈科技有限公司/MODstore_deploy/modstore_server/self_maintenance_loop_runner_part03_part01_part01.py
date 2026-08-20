# mypy: disable-error-code="attr-defined, index, no-any-return, no-redef, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _close_items_resolved_by_final(
    memory: _facade().Dict[str, _facade().Any],
    final: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    decision = final.get("policy_decision")
    if not isinstance(decision, dict):
        decision = {}
    action = str(decision.get("action") or "")
    status = str(final.get("status") or "")
    if action not in {"auto_merged_low_risk", "auto_continue"} and status != "completed_merged":
        return {"closed_count": 0, "closed_items": []}
    run_ids: _facade().List[str] = []
    task_ids: _facade().List[str] = []
    branches: _facade().List[str] = []
    resume_candidate = final.get("resume_candidate")
    if isinstance(resume_candidate, dict):
        failed_run_id = str(resume_candidate.get("failed_run_id") or "").strip()
        if failed_run_id:
            run_ids.append(failed_run_id)
        para_task_id = str(resume_candidate.get("para_task_id") or "").strip()
        if para_task_id:
            task_ids.append(para_task_id)
        branch = str(resume_candidate.get("branch") or "").strip()
        if branch:
            branches.append(branch)
    run_id = str(final.get("run_id") or "").strip()
    if run_id:
        run_ids.append(run_id)
    para_task_id = str(final.get("para_task_id") or "").strip()
    if para_task_id:
        task_ids.append(para_task_id)
    branch = str(final.get("branch") or "").strip()
    if branch:
        branches.append(branch)
    return _facade()._close_open_items_in_memory(
        memory,
        actor="self_maintenance_loop",
        branches=branches,
        resolution_reason=str(decision.get("reason") or status or "resolved_by_successful_loop"),
        run_ids=run_ids,
        task_ids=task_ids,
    )


def _resume_review_qa_candidate(
    memory: _facade().Dict[str, _facade().Any],
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_RESUME_REVIEW_QA", True):
        return None
    if not isinstance(memory, dict):
        return None
    max_retries = int(_facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES") or "3")
    open_items_raw = memory.get("open_items")
    enqueue_success_keys: set[str] = set()
    if isinstance(open_items_raw, list):
        over_retry_items = []
        for item in open_items_raw:
            if (
                isinstance(item, dict)
                and item.get("kind") == "failed_steps"
                and (int(item.get("retry_count") or 1) >= max_retries)
            ):
                over_retry_items.append(item)
        if over_retry_items:
            try:
                from modstore_server.human_uncertainty_queue import (
                    enqueue_uncertain_item,
                )

                for item in over_retry_items:
                    steps = _facade()._open_item_steps(item)
                    item_identity = _facade()._failed_open_item_identity(item)
                    if "code" in steps:
                        _facade().logger.warning(
                            "open_item identity=%s exceeded max_retries=%d, steps include code, will retry code remediation",
                            item_identity,
                            max_retries,
                        )
                        continue
                    _facade().logger.warning(
                        "open_item identity=%s exceeded max_retries=%d, escalating to human review",
                        item_identity,
                        max_retries,
                    )
                    try:
                        result = enqueue_uncertain_item(
                            context={
                                "run_id": item.get("run_id"),
                                "failed_steps": steps,
                                "retry_count": item.get("retry_count"),
                                "branch": item.get("branch"),
                                "para_task_id": item.get("para_task_id"),
                            },
                            decision={
                                "action": "await_human_strategy_approval",
                                "reason": "max_retries_exceeded",
                            },
                            reason=f"self-maintenance step {steps} failed {item.get('retry_count')} times, exceeded max retries",
                        )
                        if result.get("queued") or result.get("reason") == "duplicate":
                            item["escalated"] = True
                            enqueue_success_keys.add(item_identity)
                            _facade().logger.info(
                                "successfully enqueued escalated item identity=%s to human queue",
                                item_identity,
                            )
                        else:
                            _facade().logger.warning(
                                "failed to enqueue escalated item identity=%s to human queue, will retry next loop",
                                item_identity,
                            )
                    except RECOVERABLE_ERRORS as exc:
                        _facade().logger.warning(
                            "failed to enqueue escalated item identity=%s to human queue: %s, will retry next loop",
                            item_identity,
                            exc,
                        )
            except RECOVERABLE_ERRORS as exc:
                _facade().logger.warning("failed to import human uncertainty queue: %s", exc)
        if enqueue_success_keys:
            memory["open_items"] = [
                item
                for item in open_items_raw
                if not (
                    isinstance(item, dict)
                    and item.get("kind") == "failed_steps"
                    and (int(item.get("retry_count") or 1) >= max_retries)
                    and ("code" not in _facade()._open_item_steps(item))
                    and (_facade()._failed_open_item_identity(item) in enqueue_success_keys)
                )
            ]
        else:
            memory["open_items"] = open_items_raw
    if isinstance(open_items_raw, list):
        for item in reversed(open_items_raw):
            if not isinstance(item, dict):
                continue
            if item.get("kind") != "kb_schema_retry":
                continue
            if item.get("escalated"):
                continue
            _facade().logger.info(
                "kb_schema_retry: resuming fresh code step for run_id=%s retry_count=%d",
                item.get("run_id"),
                int(item.get("retry_count") or 0),
            )
            return None
    last_decision = memory.get("last_policy_decision")
    last_reason = str(last_decision.get("reason") or "") if isinstance(last_decision, dict) else ""
    if last_reason == "review_or_qa_reported_risk":
        return None
    if last_reason in {"employee_step_failed", "loop_not_completed"}:
        pass
    open_items = memory.get("open_items")
    recent_runs = memory.get("recent_runs")
    if not isinstance(open_items, list) or not isinstance(recent_runs, list):
        return None
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") != "failed_steps":
            continue
        steps = item.get("steps")
        if not isinstance(steps, list) or "code" not in steps:
            continue
        retry_count = int(item.get("retry_count") or 1)
        if retry_count >= max_retries:
            continue
        if not item.get("branch") and (not item.get("para_task_id")):
            return None
        branch = str(item.get("branch") or "").strip()
        para_task_id = str(item.get("para_task_id") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        if branch and para_task_id:
            return {
                "branch": branch,
                "failed_run_id": run_id,
                "failed_steps": list(steps),
                "para_task_id": para_task_id,
                "reason": "resume_failed_code_step",
            }
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") not in {
            "automated_remediation",
            "human_strategy_approval",
        }:
            continue
        reason = _facade()._normalize_automated_remediation_reason(memory, item)
        resume_plan = _facade()._automated_remediation_resume_plan(reason)
        if resume_plan is None:
            continue
        failed_steps, continue_existing_code_task = resume_plan
        if "code" not in failed_steps:
            continue
        branch = str(item.get("branch") or "").strip()
        para_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        if not branch or not para_task_id:
            continue
        candidate: _facade().Dict[str, _facade().Any] = {
            "branch": branch,
            "failed_run_id": str(item.get("run_id") or "").strip(),
            "failed_steps": list(failed_steps),
            "para_task_id": para_task_id,
            "reason": "resume_automated_remediation_candidate",
        }
        if reason.startswith("para_merge_"):
            candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
            candidate["remediation_reason"] = reason
        elif reason == _facade().RETORT_SCOPE_REASON:
            candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
            candidate["remediation_reason"] = reason
        if continue_existing_code_task:
            if reason.startswith("para_merge_"):
                if _facade().para_merge_resume_pins_rejected_branch(item):
                    candidate["continue_existing_code_task"] = True
            elif not item.get("resume_from_clean_baseline"):
                candidate["continue_existing_code_task"] = True
        return candidate
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") not in {
            "automated_remediation",
            "human_strategy_approval",
        }:
            continue
        candidate = _facade().resume_candidate_from_para_ai_review_item(memory, item)
        if candidate is not None:
            return candidate
    review_failed_run_ids = set()
    for item in open_items:
        if not isinstance(item, dict) or item.get("kind") != "failed_steps":
            continue
        steps = item.get("steps")
        if not isinstance(steps, list):
            continue
        if any((str(step) in {"review", "qa"} for step in steps)):
            run_id = str(item.get("run_id") or "")
            if run_id:
                review_failed_run_ids.add((run_id, tuple((str(step) for step in steps))))
    for run in reversed(recent_runs):
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("run_id") or "")
        matched_steps = None
        for candidate_run_id, candidate_steps in review_failed_run_ids:
            if run_id == candidate_run_id:
                matched_steps = candidate_steps
                break
        if matched_steps is None:
            continue
        branch = str(run.get("branch") or "").strip()
        para_task_id = str(run.get("para_task_id") or "").strip()
        if branch and para_task_id:
            return {
                "branch": branch,
                "failed_run_id": run_id,
                "failed_steps": list(matched_steps),
                "para_task_id": para_task_id,
                "reason": "resume_failed_review_or_qa",
            }
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") not in {
            "automated_remediation",
            "human_strategy_approval",
        }:
            continue
        reason = _facade()._normalize_automated_remediation_reason(memory, item)
        candidate = _facade().resume_candidate_from_para_ai_review_item(memory, item)
        if candidate is not None:
            return candidate
        if reason in {
            "auto_merge_safety_score_v2_too_low",
            "auto_merge_safety_score_v3_too_low",
            "risk_score_v3_below_threshold_or_blocked",
        }:
            branch = str(item.get("branch") or "").strip()
            para_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
            run_id = str(item.get("run_id") or "").strip()
            if branch and para_task_id:
                return {
                    "branch": branch,
                    "continue_existing_code_task": True,
                    "failed_run_id": run_id,
                    "failed_steps": ["code"],
                    "para_task_id": para_task_id,
                    "reason": "resume_safety_score_remediation",
                }
            continue
        resume_plan = _facade()._automated_remediation_resume_plan(reason)
        if resume_plan is None:
            continue
        failed_steps, continue_existing_code_task = resume_plan
        branch = str(item.get("branch") or "").strip()
        para_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        if branch and para_task_id:
            candidate: _facade().Dict[str, _facade().Any] = {
                "branch": branch,
                "failed_run_id": run_id,
                "failed_steps": list(failed_steps),
                "para_task_id": para_task_id,
                "reason": "resume_automated_remediation_candidate",
            }
            if reason.startswith("para_merge_"):
                candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
                candidate["remediation_reason"] = reason
            elif reason == _facade().RETORT_SCOPE_REASON:
                candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
                candidate["remediation_reason"] = reason
            if continue_existing_code_task:
                if reason.startswith("para_merge_"):
                    if _facade().para_merge_resume_pins_rejected_branch(item):
                        candidate["continue_existing_code_task"] = True
                elif not item.get("resume_from_clean_baseline"):
                    candidate["continue_existing_code_task"] = True
            return candidate
    return None


def _resume_steps(
    resume_candidate: _facade().Optional[_facade().Dict[str, _facade().Any]],
) -> set[str]:
    """Return the failed step and every downstream step that must be rerun."""
    if not resume_candidate:
        return {"code", "review", "qa"}
    failed = {str(item) for item in resume_candidate.get("failed_steps") or []}
    if "code" in failed:
        return {"code", "review", "qa"}
    if "review" in failed:
        return {"review", "qa"}
    if "qa" in failed:
        return {"qa"}
    return set()


def _resume_dispatch_context(
    resume_candidate: _facade().Optional[_facade().Dict[str, _facade().Any]],
    steps_to_run: set[str],
) -> _facade().Tuple[_facade().Optional[str], _facade().Optional[str]]:
    """Choose the Para task id and base branch for a resumed loop.

    Code retries must use a fresh Para task. A score remediation still keeps
    the prior candidate branch as its base so the production fix survives.
    A merge-review rejection starts from the configured clean base and treats
    the rejected branch as reference only; otherwise each rejection compounds
    the previous diff until the reviewer can never accept it. Review/QA-only
    retries keep the original task and branch for evidence.
    """
    if not resume_candidate:
        return (None, None)
    para_task_id = str(resume_candidate.get("para_task_id") or "").strip() or None
    code_branch = str(resume_candidate.get("branch") or "").strip() or None
    if "code" not in steps_to_run:
        return (para_task_id, code_branch)
    if resume_candidate.get("continue_existing_code_task"):
        return (None, code_branch)
    return (None, None)


def _parse_iso(value: _facade().Any) -> _facade().Optional[_facade().datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = _facade().datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_facade().timezone.utc)
        return dt.astimezone(_facade().timezone.utc)
    except ValueError:
        return None


def _file_url_to_path(repo_url: str) -> _facade().Optional[_facade().Path]:
    if not repo_url.startswith("file://"):
        return None
    parsed = _facade().urlparse(repo_url)
    return _facade().Path(_facade().unquote(parsed.path))


def _self_maintenance_actor_user_id() -> int:
    """自维护 loop 的 LLM 执行身份（默认平台身份 ``user_id=0``）。

    ``services.llm.chat_dispatch_via_session`` 仅在 ``uid > 0`` 时调
    ``quota_middleware.require_llm_credit`` 走某真实用户的个人 ``llm_calls`` 月配额闸；
    传 ``0`` 即跳过该配额、改用 ``llm_key_resolver.resolve_api_key`` 的平台密钥
    （``user_id=0`` 无 BYOK 凭证行，自然回落 ``platform_api_key``）。指标表 ``user_id``
    仍由 ``employee_executor._resolve_metric_user_id`` 回落到真实 ``users.id``，监控不丢。

    历史 bug：本函数旧实现（``_first_user_id``）取「库里第一个真实用户」作执行身份，
    使平台自治工作全部记到 owner 个人配额上；其额度耗尽后整条 loop 持续报
    ``403: 配额不足: llm_calls``（生产实测 99.6% 失败的根因）。

    运维如需按某真实用户 BYOK/配额计费，可设 ``MODSTORE_SELF_MAINTENANCE_USER_ID=<uid>``。
    """
    env_uid = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_USER_ID", "").strip()
    if env_uid:
        try:
            return int(env_uid)
        except ValueError:
            _facade().logger.warning("MODSTORE_SELF_MAINTENANCE_USER_ID not an int: %s", env_uid)
    return 0
