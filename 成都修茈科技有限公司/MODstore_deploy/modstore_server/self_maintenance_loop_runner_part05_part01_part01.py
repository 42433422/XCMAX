# mypy: disable-error-code="arg-type, attr-defined, misc, no-any-return, no-redef, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _employee_result_ok(result: _facade().Dict[str, _facade().Any]) -> bool:
    if not result or result.get("handler_failed"):
        return False
    report_text = _facade()._extract_report_excerpt(result).lower()
    if "blocked by risk middleware" in report_text:
        return False
    if any(
        (
            marker in report_text
            for marker in (
                "[e2e-agent] codex cli 失败",
                "[e2e-agent] cursor agent 失败",
                "codex cli timeout after",
                "report-only 执行器失败",
            )
        )
    ):
        return False
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    if str(inner.get("status", "")).lower() in {"failed", "error"}:
        return False
    if not bool(inner.get("ok", True)):
        return False
    outputs = inner.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and item.get("ok") is False:
                return False
    dv_gate = _facade()._delivery_validation_gate(result)
    if dv_gate.get("found") and (not dv_gate.get("ok")):
        return False
    return True


def _delivery_validation_command_failed(command: _facade().Any) -> bool:
    return isinstance(command, dict) and command.get("exit_code") not in (0, None)


def _delivery_validation_gate(
    result: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    """Evaluate nested delivery_validation for closed-loop completion evidence.

    Returns a stable dict used by validate/writeback completion checks:
      found / ok / reason / delivery_validation
    """
    dv = _facade()._find_delivery_validation(result)
    if not isinstance(dv, dict):
        return {
            "delivery_validation": None,
            "found": False,
            "ok": True,
            "reason": "delivery_validation_absent",
        }
    cmds = dv.get("commands")
    if not isinstance(cmds, list) or not cmds:
        return {
            "delivery_validation": dv,
            "found": True,
            "ok": True,
            "reason": "delivery_validation_no_commands",
        }
    failed_cmds = [c for c in cmds if _facade()._delivery_validation_command_failed(c)]
    if failed_cmds:
        return {
            "delivery_validation": dv,
            "failed_commands": failed_cmds[:3],
            "found": True,
            "ok": False,
            "reason": "delivery_validation_failed",
        }
    return {
        "delivery_validation": dv,
        "found": True,
        "ok": True,
        "reason": "delivery_validation_passed",
    }


def _find_delivery_validation(
    obj: _facade().Any, depth: int = 0
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """递归查找 result 里的 delivery_validation dict（Para 远端返回）。

    delivery_validation 不在本地代码产出，由 Para 平台返回时嵌在
    result.result.outputs[].response / para_result 等任意层级，故需递归。

    Determinism contract:
    - Prefer canonical Para nests (``para_result`` / ``response`` / ``outputs`` / …)
      before other keys.
    - Remaining dict keys are visited in sorted order (not insertion order).
    - Lists keep the first 12 items; depth is capped at 6.
    - When multiple DVs exist, prefer the one with a ``commands`` list (and among
      those, the one with non-zero exit_code evidence).
    """
    candidates: _facade().List[
        _facade().Tuple[_facade().Tuple[int, int, int, int], _facade().Dict[str, _facade().Any]]
    ] = []
    _facade()._collect_delivery_validation_candidates(obj, depth=depth, out=candidates)
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (item[0][0], item[0][1], item[0][2], -item[0][3]))
    return best[1]


def _collect_delivery_validation_candidates(
    obj: _facade().Any,
    *,
    depth: int,
    out: _facade().List[
        _facade().Tuple[_facade().Tuple[int, int, int, int], _facade().Dict[str, _facade().Any]]
    ],
    rank: int = 0,
) -> int:
    """Collect scored delivery_validation candidates; returns next discovery rank."""
    if depth > 6 or not isinstance(obj, (dict, list)):
        return rank
    if isinstance(obj, dict):
        dv = obj.get("delivery_validation")
        if isinstance(dv, dict):
            cmds = dv.get("commands") if isinstance(dv.get("commands"), list) else []
            failed = sum((1 for c in cmds if _facade()._delivery_validation_command_failed(c)))
            out.append(((1 if cmds else 0, failed, len(cmds), rank), dv))
            rank += 1
        preferred_present = [
            key
            for key in _facade()._DELIVERY_VALIDATION_PREFERRED_KEYS
            if key in obj and key != "delivery_validation"
        ]
        remaining = sorted(
            (
                key
                for key in obj.keys()
                if key not in _facade()._DELIVERY_VALIDATION_PREFERRED_KEYS
                and key != "delivery_validation"
            )
        )
        for key in preferred_present + remaining:
            rank = _collect_delivery_validation_candidates(
                obj.get(key), depth=depth + 1, out=out, rank=rank
            )
        return rank
    for item in obj[:12]:
        rank = _collect_delivery_validation_candidates(item, depth=depth + 1, out=out, rank=rank)
    return rank


def _extract_failure_reason(
    result: _facade().Dict[str, _facade().Any],
    para_meta: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> str:
    """Extract a human-readable failure reason from an employee execution result.

    Used to enrich ledger records so failures stop being silent (ok=False with
    no explanation). Order: explicit error fields > status markers > report text.
    """
    if not result:
        return "empty_result"
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    inner_outputs_failure = ""
    if isinstance(inner, dict):
        outputs = inner.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if isinstance(item, dict) and item.get("ok") is False:
                    handler = str(item.get("handler") or item.get("name") or "")
                    err = item.get("error") or item.get("message") or item.get("stderr")
                    detail = item.get("detail") or item.get("reason")
                    parts = [f"handler={handler}"] if handler else []
                    if err:
                        parts.append(f"error={str(err)[:200]}")
                    if detail:
                        parts.append(f"detail={str(detail)[:120]}")
                    inner_outputs_failure = (
                        "output_failed: " + " ".join(parts) if parts else "output ok=False"
                    )
                    break
    path_guard_failure = ""
    if isinstance(inner, dict):
        pg = inner.get("path_guard")
        if isinstance(pg, dict) and pg.get("checked") and (not pg.get("ok")):
            violations = pg.get("violations") or []
            vstr = "; ".join(
                (
                    f"{v.get('path', '')}({v.get('reason', '')})"
                    for v in violations[:5]
                    if isinstance(v, dict)
                )
            )
            path_guard_failure = (
                f"path_guard_violation: {vstr}"[:300] if vstr else "path_guard_violation"
            )
    if result.get("handler_failed"):
        msg = result.get("handler_failed_message") or result.get("error")
        if msg:
            return f"handler_failed: {str(msg)[:300]}"
        if path_guard_failure:
            return path_guard_failure
        if inner_outputs_failure:
            return inner_outputs_failure
        return "handler_failed"
    if path_guard_failure:
        return path_guard_failure
    if inner_outputs_failure:
        return inner_outputs_failure
    dv_gate = _facade()._delivery_validation_gate(result)
    if dv_gate.get("found") and (not dv_gate.get("ok")):
        failed_cmds = dv_gate.get("failed_commands") or []
        parts: _facade().List[str] = []
        for c in failed_cmds[:3]:
            if not isinstance(c, dict):
                continue
            ec = c.get("exit_code")
            cmd = str(c.get("command") or "")[:80]
            tail = str(c.get("output_tail") or c.get("output") or "")[:120]
            seg = f"exit={ec}"
            if cmd:
                seg += f" cmd={cmd}"
            if tail:
                seg += f" tail={tail}"
            parts.append(seg)
        if parts:
            return "delivery_validation_failed: " + " | ".join(parts)[:300]
        return "delivery_validation_failed"
    if isinstance(para_meta, dict):
        para_err = para_meta.get("error")
        if para_err:
            return f"para_error: {str(para_err)[:300]}"
        para_status = str(para_meta.get("para_status") or "").lower()
        if para_status and para_status not in {"completed", "ok", "success", ""}:
            return f"para_status={para_status}"
    if isinstance(inner, dict):
        status = str(inner.get("status") or "").lower()
        if status in {"failed", "error"}:
            return f"inner_status={status}: {str(inner.get('error') or inner.get('message') or '')[:200]}"
    report = _facade()._extract_report_excerpt(result).lower()
    markers = (
        ("blocked by risk middleware", "blocked_by_risk_middleware"),
        ("codex cli 失败", "codex_cli_failed"),
        ("cursor agent 失败", "cursor_agent_failed"),
        ("codex cli timeout after", "codex_cli_timeout"),
        ("report-only 执行器失败", "report_only_executor_failed"),
        ("无法完成", "agent_gave_up"),
        ("无法完成修复", "agent_gave_up_fix"),
        ("需要更多轮次或人工介入", "agent_needs_human"),
        ("达到最大工具调用轮次", "agent_max_rounds_reached"),
    )
    for marker, label in markers:
        if marker in report:
            return label
    return "ok_false_unknown_reason"


def _extract_para_meta(
    result: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    outputs = inner.get("outputs") if isinstance(inner, dict) else None
    output = None
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and item.get("handler") == "para_delegate":
                output = item
                break
    if output is None and isinstance(inner, dict):
        output = inner
    response = output.get("response") if isinstance(output, dict) else None
    para_result = output.get("para_result") if isinstance(output, dict) else None
    if not isinstance(response, dict):
        response = {}
    if not isinstance(para_result, dict):
        para_result = {}
    subtasks = para_result.get("subtasks")
    first_subtask = subtasks[0] if isinstance(subtasks, list) and subtasks else {}
    return {
        "branch": first_subtask.get("branch") or first_subtask.get("branchName"),
        "completed_at": para_result.get("completed_at"),
        "error": output.get("error") if isinstance(output, dict) else None,
        "para_status": para_result.get("status"),
        "subtask_id": first_subtask.get("id") or response.get("subtaskId"),
        "task_id": para_result.get("task_id") or para_result.get("id") or response.get("taskId"),
    }


def _collect_text_fields(value: _facade().Any, out: _facade().List[str], depth: int = 0) -> None:
    if depth > 6 or len(out) >= 24:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
        return
    if isinstance(value, list):
        for item in value[:12]:
            _collect_text_fields(item, out, depth + 1)
        return
    if isinstance(value, dict):
        preferred = {
            "content",
            "detail",
            "error",
            "message",
            "output",
            "report",
            "stderr",
            "stdout",
            "summary",
        }
        for key in preferred:
            if key in value:
                _collect_text_fields(value.get(key), out, depth + 1)
        for key, item in list(value.items())[:24]:
            if key not in preferred:
                _collect_text_fields(item, out, depth + 1)


def _extract_report_excerpt(result: _facade().Dict[str, _facade().Any], limit: int = 4000) -> str:
    texts: _facade().List[str] = []
    _facade()._collect_text_fields(result, texts)
    seen = set()
    compact: _facade().List[str] = []
    for text in texts:
        normalized = " ".join(text.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        compact.append(normalized)
        if sum((len(x) for x in compact)) >= limit:
            break
    return "\n".join(compact)[:limit]


def _is_transient_employee_dispatch_failure(
    result: _facade().Dict[str, _facade().Any],
) -> bool:
    if _facade()._is_accepted_para_wait_timeout(result):
        return False
    return _facade().is_transient_dispatch_failure(result)


def _coerce_truthy_flag(value: _facade().Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _para_item_is_accepted_wait_timeout(item: _facade().Any) -> bool:
    if not isinstance(item, dict):
        return False
    handler = str(item.get("handler") or "").strip()
    if handler and handler != "para_delegate":
        return False
    if not _facade()._coerce_truthy_flag(item.get("accepted")):
        return False
    status = str(item.get("status") or "").strip().lower()
    if status == "para_task_timeout":
        return True
    for nest_key in ("para_result", "snapshot", "response"):
        nested = item.get(nest_key)
        if isinstance(nested, dict):
            nested_status = str(nested.get("status") or "").strip().lower()
            if nested_status == "para_task_timeout":
                return True
    return False


def _is_accepted_para_wait_timeout(result: _facade().Dict[str, _facade().Any]) -> bool:
    """Detect an accepted Para task whose synchronous wait expired.

    Shapes covered (all mean: task accepted, do NOT start code_fix redispatch):
    - ``result.outputs[]`` para_delegate item with accepted + para_task_timeout
    - flat handler dict at top-level / ``result``
    - accepted flag as bool/1/"true"; timeout status on item or nested para_result
    """
    if not isinstance(result, dict):
        return False
    if _facade()._para_item_is_accepted_wait_timeout(result):
        return True
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    if _facade()._para_item_is_accepted_wait_timeout(inner):
        return True
    outputs = inner.get("outputs") if isinstance(inner, dict) else None
    if not isinstance(outputs, list):
        return False
    return any((_facade()._para_item_is_accepted_wait_timeout(item) for item in outputs))


def _loop_platform_bench_override() -> _facade().Optional[tuple]:
    """后台自维护/进化 loop 默认走平台派发：LLM 成本记平台密钥、不查/扣用户 ``llm_calls`` 配额。

    与 digest 产线一致——后台自治 loop 不该按「用户调用」计量。``_first_user_id()`` 返回的是
    第一个真实用户，挂到其月度配额上几小时就 ``403 配额不足: llm_calls``（生产实测疯跑 99.6%
    失败、进化引擎误把配额失败当 prompt 问题狂改的根因）。返回平台 bench (provider, model) 作为
    ``bench_llm_override`` → cognition ``use_platform_dispatch=True`` → 不经 require_llm_credit；
    ``user_id`` 仍透传给 RAG/指标。关闭（回退按用户配额）：``MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM=0``。
    """
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM", True):
        return None
    try:
        from modstore_server.services.llm import resolve_platform_bench_llm

        rp, rm = resolve_platform_bench_llm()
        if rp and rm:
            return (rp, rm)
    except RECOVERABLE_ERRORS:
        return None
    return None
