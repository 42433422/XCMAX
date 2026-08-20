# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _actions_real(
    config: _facade().Dict[str, _facade().Any],
    reasoning: _facade().Dict[str, _facade().Any],
    task: str,
    employee_id: str,
    user_id: int = 0,
) -> _facade().Dict[str, _facade().Any]:
    actions_cfg = _facade()._get_section(config, "actions")
    if employee_id == "taiyangniao-attendance-employee":
        actions_cfg = dict(actions_cfg)
        direct_cfg = dict(actions_cfg.get("direct_python") or {})
        direct_cfg.pop("default_backend_path", None)
        actions_cfg["direct_python"] = direct_cfg
        actions_cfg["handlers"] = ["direct_python"]
    handlers = actions_cfg.get("handlers") or ["echo"]
    requested_handler = str(
        (reasoning.get("input") or {}).get("handler")
        if isinstance(reasoning.get("input"), dict)
        else ""
    ).strip()
    deterministic_council_review = bool(
        employee_id == "change-request-auditor"
        and requested_handler == "direct_python"
        and ("direct_python" in handlers)
    )
    direct_input = reasoning.get("input") if isinstance(reasoning.get("input"), dict) else {}
    reviewed_direct_burn_in = _facade().is_reviewed_direct_burn_in(
        actions_cfg,
        direct_input,
        requested_handler,
        handlers,
        burn_in=_facade()._flag_enabled(direct_input.get("burn_in")),
        read_only=_facade()._flag_enabled(direct_input.get("burn_in_read_only")),
    )
    if employee_id in (
        "vibe-coding-maintainer",
        "change-request-auditor",
        "test-qa-runner",
    ) and (not (deterministic_council_review or reviewed_direct_burn_in)):
        handlers = _facade()._prefer_para_with_local_fallback(list(handlers), list(handlers))
    if employee_id == "vibe-coding-maintainer":
        handlers = _facade()._filter_handlers_vibe_coding_maintainer(handlers, reasoning, task)
    outputs: _facade().List[_facade().Dict[str, _facade().Any]] = []
    skip_local_after_para_ok = False
    _LOCAL_FALLBACK_HANDLERS = {
        "agent",
        "vibe_edit",
        "vibe_heal",
        "vibe_code",
        "cursor_delegate",
        "direct_python",
    }
    for handler in handlers:
        if skip_local_after_para_ok and str(handler) in _LOCAL_FALLBACK_HANDLERS:
            continue
        if handler == "echo":
            outputs.append({"handler": "echo", "output": reasoning.get("reasoning", "")})
        elif handler == "http_request":
            http_cfg = actions_cfg.get("http_request") or {}
            url = str(http_cfg.get("url") or "").strip()
            method = str(http_cfg.get("method") or "POST").strip().upper()
            headers = http_cfg.get("headers") or {}
            body_tpl = str(http_cfg.get("body") or "")
            body = body_tpl.replace("{{reasoning}}", str(reasoning.get("reasoning") or ""))
            body = body.replace("{{task}}", task)
            if not url:
                outputs.append({"handler": "http_request", "error": "missing url"})
                continue
            try:
                resp = _facade().httpx.request(
                    method, url, headers=headers, content=body, timeout=30.0
                )
                outputs.append(
                    {
                        "handler": "http_request",
                        "status_code": resp.status_code,
                        "response": resp.text[:2000],
                    }
                )
            except RECOVERABLE_ERRORS as e:
                outputs.append({"handler": "http_request", "error": str(e)})
        elif handler == "webhook":
            webhook_cfg = actions_cfg.get("webhook") or {}
            url = str(webhook_cfg.get("url") or "").strip()
            if not url:
                outputs.append({"handler": "webhook", "error": "missing url"})
                continue
            payload = {
                "employee_id": employee_id,
                "task": task,
                "result": reasoning.get("reasoning", ""),
            }
            try:
                resp = _facade().httpx.post(url, json=payload, timeout=30.0)
                outputs.append({"handler": "webhook", "status_code": resp.status_code})
            except RECOVERABLE_ERRORS as e:
                outputs.append({"handler": "webhook", "error": str(e)})
        elif handler == "data_sync":
            target = str((actions_cfg.get("data_sync") or {}).get("target") or "log")
            if target == "log":
                _facade().logger.info(
                    "[data_sync] employee=%s task=%s result=%s",
                    employee_id,
                    task,
                    str(reasoning.get("reasoning") or "")[:500],
                )
            outputs.append({"handler": "data_sync", "target": target, "status": "ok"})
        elif handler == "direct_python":
            outputs.append(
                _facade()._action_direct_python(actions_cfg, reasoning, task, employee_id, user_id)
            )
        elif handler == "wechat_notify":
            outputs.append(_facade()._action_wechat_notify(actions_cfg, reasoning, task))
        elif handler == "openapi_tool":
            outputs.append(
                _facade()._action_openapi_tool(actions_cfg, reasoning, task, employee_id, user_id)
            )
        elif handler == "fhd_business":
            outputs.append(_facade()._action_fhd_business(actions_cfg, reasoning, task))
        elif handler == "voice_output":
            vo = (
                actions_cfg.get("voice_output")
                if isinstance(actions_cfg.get("voice_output"), dict)
                else {}
            )
            text = str(reasoning.get("reasoning") or "").strip()
            outputs.append(
                {
                    "handler": "voice_output",
                    "status": "pending_tts",
                    "note": "未配置 TTS 服务：返回待合成文本，可由宿主接入阿里云/讯飞/OpenAI TTS",
                    "text_preview": text[:800],
                    "provider": str(vo.get("provider") or "").strip(),
                    "voice_id": str(vo.get("voice_id") or "").strip(),
                }
            )
        elif handler == "agent":
            outputs.append(
                _facade()._action_agent_runner(actions_cfg, reasoning, task, employee_id, user_id)
            )
        elif handler == "para_delegate":
            from modstore_server.para_delegate_handler import dispatch_para_delegate

            cog_in = reasoning.get("input") if isinstance(reasoning.get("input"), dict) else {}
            para_out = dispatch_para_delegate(task=task, input_data=cog_in, employee_id=employee_id)
            outputs.append(para_out)
            if isinstance(para_out, dict) and para_out.get("ok") is True:
                skip_local_after_para_ok = True
        elif handler == "cursor_delegate":
            from modstore_server.cursor_delegate_handler import dispatch_cursor_delegate

            cog_in = reasoning.get("input") if isinstance(reasoning.get("input"), dict) else {}
            outputs.append(
                dispatch_cursor_delegate(task=task, input_data=cog_in, employee_id=employee_id)
            )
        elif handler == "llm_md":
            outputs.append({"handler": "llm_md", "output": reasoning.get("reasoning", "")})
        elif handler == "specialized":
            outputs.append(
                {
                    "handler": "specialized",
                    "ok": True,
                    "output": reasoning.get("reasoning", ""),
                    "note": "specialized handler uses the employee's declared package-specific capability boundary.",
                }
            )
        elif handler in ("vibe_edit", "vibe_heal", "vibe_code"):
            try:
                from modstore_server.integrations.vibe_action_handlers import (
                    dispatch_vibe_handler,
                )

                vibe_out = dispatch_vibe_handler(
                    str(handler), actions_cfg, reasoning, task, employee_id, user_id
                )
            except RECOVERABLE_ERRORS as exc:
                _facade().logger.exception("vibe handler dispatch failed handler=%s", handler)
                vibe_out = {
                    "handler": str(handler),
                    "ok": False,
                    "error": f"dispatch error: {exc}",
                }
            outputs.append(vibe_out or {"handler": str(handler), "ok": False, "error": "no output"})
        elif handler == "doc_sync":
            from modstore_server.integrations.doc_sync_handler import (
                dispatch_doc_sync_handler,
            )

            outputs.append(
                dispatch_doc_sync_handler(actions_cfg, reasoning, task, employee_id, user_id)
            )
        elif handler in ("shell_exec", "ssh_exec"):
            from modstore_server.integrations.ops_action_handlers import (
                dispatch_ops_handler,
            )

            outputs.append(
                dispatch_ops_handler(handler, actions_cfg, reasoning, task, employee_id, user_id)
            )
        else:
            outputs.append({"handler": str(handler), "error": "unknown handler"})
    try:
        _rep_input = reasoning.get("input") if isinstance(reasoning.get("input"), dict) else {}
        _rep_body = ""
        if not _rep_input.get("im_reply_managed"):
            for _o in outputs:
                if not isinstance(_o, dict):
                    continue
                _cand = str(_o.get("answer") or _o.get("summary") or _o.get("output") or "").strip()
                if not _cand:
                    continue
                if _cand[:1] == "{" and '"answer"' in _cand:
                    try:
                        _ans = (_facade().json.loads(_cand) or {}).get("answer")
                        if _ans and str(_ans).strip():
                            _cand = str(_ans).strip()
                    except (ValueError, TypeError):
                        pass
                _rep_body = _cand
                break
        if _rep_body:
            _facade()._emp_im_notify_boss(
                employee_id,
                config if isinstance(config, dict) else {},
                _rep_body,
                "report",
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug(
            "actions_real report im hook skipped employee_id=%s",
            employee_id,
            exc_info=True,
        )
    return {
        "task": task,
        "handlers": handlers,
        "outputs": outputs,
        "summary": f"executed {len(outputs)} handlers",
    }


def _extract_token_count(reasoning: _facade().Dict[str, _facade().Any]) -> int:
    raw = reasoning.get("llm_raw") if isinstance(reasoning, dict) else {}
    usage = raw.get("usage") if isinstance(raw, dict) else {}
    total = usage.get("total_tokens")
    if isinstance(total, int):
        return total
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    return int(pt or 0) + int(ct or 0)
