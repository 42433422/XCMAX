# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _employee_pack_extract_root(
    employee_id: str, manifest: _facade().Dict[str, _facade().Any]
) -> _facade().Path:
    """Extract the employee pack to a runtime directory so package-local Python files can run."""
    runtime_root = (
        _facade()
        .Path(_facade().os.environ.get("MODSTORE_RUNTIME_DIR") or "/tmp/modstore_runtime")
        .expanduser()
    )
    pack_id = str(manifest.get("id") or employee_id).strip() or employee_id
    version = str(manifest.get("version") or "dev").strip() or "dev"
    target = runtime_root / "employee_packs" / pack_id / version
    module_file = target / "backend" / "employees" / "taiyangniao_attendance.py"
    sf = _facade().get_session_factory()
    with sf() as session:
        pack = _facade().load_employee_pack_resolved(session, employee_id)
    stored = str(pack.get("stored_filename") or "").strip()
    if not stored:
        raise RuntimeError("employee pack missing stored_filename")
    zpath = _facade().files_dir() / stored
    if not zpath.is_file():
        raise RuntimeError(f"employee pack file not found: {zpath}")
    marker = target / ".source_mtime"
    source_mtime = str(zpath.stat().st_mtime_ns)
    if module_file.is_file():
        try:
            if marker.read_text(encoding="utf-8").strip() == source_mtime:
                return target
        except OSError:
            pass
    target.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        _facade().shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    with _facade().zipfile.ZipFile(zpath, "r") as zf:
        root_prefix = f"{pack_id}/"
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name.startswith(root_prefix):
                continue
            rel = name[len(root_prefix) :]
            if not rel or rel.startswith("/") or ".." in _facade().Path(rel).parts:
                continue
            dest = tmp / rel
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, dest.open("wb") as out:
                _facade().shutil.copyfileobj(src, out)
    if target.exists():
        _facade().shutil.rmtree(target, ignore_errors=True)
    tmp.replace(target)
    marker.write_text(source_mtime + "\n", encoding="utf-8")
    return target


def _action_direct_python(
    actions_cfg: _facade().Dict[str, _facade().Any],
    reasoning: _facade().Dict[str, _facade().Any],
    task: str,
    employee_id: str,
    user_id: int = 0,
) -> _facade().Dict[str, _facade().Any]:
    """Run package-local backend/employees/*.py for script-style employee packs."""
    direct_cfg = (
        actions_cfg.get("direct_python")
        if isinstance(actions_cfg.get("direct_python"), dict)
        else {}
    )
    try:
        sf = _facade().get_session_factory()
        direct_input = (
            reasoning.get("input")
            if isinstance(reasoning, dict) and isinstance(reasoning.get("input"), dict)
            else {}
        )
        reviewed_burn_in = _facade()._flag_enabled(
            direct_input.get("burn_in")
        ) and _facade()._flag_enabled(direct_input.get("burn_in_read_only"))
        reviewed_duty_execution = _facade()._flag_enabled(
            direct_input.get("_trusted_duty_contract_execution")
        )
        if reviewed_burn_in or reviewed_duty_execution:
            from modstore_server.duty_workforce_contracts import resolve_reviewed_duty_employee_root

            root = resolve_reviewed_duty_employee_root(employee_id)
        else:
            with sf() as session:
                pack = _facade().load_employee_pack_resolved(session, employee_id)
            manifest = pack.get("manifest") or {}
            root = _facade()._employee_pack_extract_root(employee_id, manifest)
        module_name = (
            str(direct_cfg.get("module") or "taiyangniao_attendance").strip()
            or "taiyangniao_attendance"
        )
        module_path = root / "backend" / "employees" / f"{module_name}.py"
        if not module_path.is_file():
            return {
                "handler": "direct_python",
                "ok": False,
                "error": f"module not found: {module_path}",
            }
        spec = _facade().importlib.util.spec_from_file_location(
            f"_modstore_employee_pack_{employee_id.replace('-', '_')}_{module_name}",
            str(module_path),
        )
        if spec is None or spec.loader is None:
            return {
                "handler": "direct_python",
                "ok": False,
                "error": f"cannot load module spec: {module_path}",
            }
        module = _facade().importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        run_fn = getattr(module, "run", None)
        if not callable(run_fn):
            return {
                "handler": "direct_python",
                "ok": False,
                "error": "module has no callable run(payload, ctx)",
            }
        payload = dict(direct_input)
        if isinstance(reasoning, dict):
            for key in ("file_path", "workspace_root", "original_filename", "action"):
                if key in reasoning and key not in payload:
                    payload[key] = reasoning[key]
        payload.setdefault("task", task)
        payload.setdefault("action", str(direct_cfg.get("action") or "convert"))
        for src, dst in (
            ("default_output_relpath", "output_relpath"),
            ("default_template_relpath", "template_relpath"),
            ("default_backend_path", "taiyangniao_backend_path"),
        ):
            val = direct_cfg.get(src)
            if val and (not payload.get(dst)):
                payload[dst] = val
        if (
            direct_cfg.get("default_use_personnel_roster") is not None
            and "use_personnel_roster" not in payload
        ):
            payload["use_personnel_roster"] = bool(direct_cfg.get("default_use_personnel_roster"))

        async def _direct_call_llm(
            messages: _facade().List[_facade().Dict[str, _facade().Any]], **kwargs
        ) -> _facade().Dict[str, _facade().Any]:
            mt = int(kwargs.get("max_tokens") or 8000)
            provider = str(kwargs.get("provider") or "auto")
            model = str(kwargs.get("model") or "auto")
            uid = int(user_id or 0)
            if uid > 0 and (provider.lower() == "auto" or model.lower() == "auto"):
                from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto

                with sf() as sess:
                    urow = sess.query(_facade().User).filter(_facade().User.id == uid).first()
                    if urow:
                        (rp, rm, perr) = await resolve_llm_provider_model_auto(
                            sess, urow, None, None
                        )
                        if rp and rm and (not perr):
                            (provider, model) = (rp, rm)
            with sf() as sess:
                return await _facade().chat_dispatch_via_session(
                    sess, uid, provider, model, messages, max_tokens=mt
                )

        ctx = {
            "employee_id": employee_id,
            "user_id": user_id,
            "workspace_root": payload.get("workspace_root") or "",
            "logger": _facade().logging.getLogger(f"employee.direct_python.{employee_id}"),
            "call_llm": _direct_call_llm,
        }
        out = run_fn(payload, ctx)
        if _facade().asyncio.iscoroutine(out):
            out = _facade()._run_coro_sync(out)
        if isinstance(out, dict):
            ok = bool(out.get("ok", out.get("success", True)))
            detail = {"handler": "direct_python", "ok": ok, "output": out}
            if not ok:
                err = str(
                    out.get("error") or out.get("error_code") or out.get("summary") or ""
                ).strip()
                if err:
                    detail["error"] = err[:1000]
            return detail
        return {"handler": "direct_python", "ok": True, "output": out}
    except Exception as exc:
        _facade().logger.exception("direct_python handler failed employee_id=%s", employee_id)
        return {"handler": "direct_python", "ok": False, "error": str(exc)[:1000]}


def _prefer_para_with_local_fallback(
    selected: _facade().List[str], available: _facade().List[str]
) -> _facade().List[str]:
    """Para 优先，但保留本地 agent/vibe/cursor 回退，避免 Mac Bridge 离线整单卡死。"""
    try:
        from modstore_server.para_delegate_handler import (
            para_delegate_enabled,
            para_delegate_ready_for_dispatch,
        )
    except Exception:
        return list(selected)
    if not (para_delegate_enabled() and para_delegate_ready_for_dispatch()):
        return list(selected)
    avail = {str(h) for h in available or []}
    ordered: _facade().List[str] = ["para_delegate"]
    for handler in selected:
        name = str(handler or "").strip()
        if name and name != "para_delegate" and (name not in ordered):
            ordered.append(name)
    for handler in ("agent", "vibe_edit", "cursor_delegate", "direct_python", "llm_md"):
        if handler in avail and handler not in ordered:
            ordered.append(handler)
    return ordered


def _filter_handlers_vibe_coding_maintainer(
    handlers: _facade().List[str], reasoning: _facade().Dict[str, _facade().Any], task: str
) -> _facade().List[str]:
    """按 payload 路由 vibe-coding-maintainer，避免每次任务跑完全部 handler。"""
    inp = reasoning.get("input") if isinstance(reasoning.get("input"), dict) else {}
    try:
        from modstore_server.para_delegate_handler import (
            para_delegate_enabled,
            para_delegate_ready_for_dispatch,
        )
    except Exception:

        def para_delegate_enabled() -> bool:
            return False

        def para_delegate_ready_for_dispatch() -> bool:
            return False

    normalized = [str(h or "").strip() for h in handlers if str(h or "").strip()]
    if normalized and set(normalized) <= {"direct_python"}:
        expanded = ["vibe_edit", "agent", "llm_md", "direct_python"]
        return _facade()._prefer_para_with_local_fallback(expanded, expanded)
    requested = str(inp.get("handler") or "").strip()
    if requested and requested in handlers:
        out = [requested]
        if "llm_md" in handlers and requested != "llm_md":
            out.append("llm_md")
        return _facade()._prefer_para_with_local_fallback(out, handlers)
    priority = str(inp.get("priority") or "").upper()
    delegate = str(inp.get("delegate") or "").lower()
    multi_step = bool(inp.get("multi_step") or inp.get("handler_mode") == "agent")
    if delegate == "cursor" or priority == "P0" or inp.get("fallback_cursor"):
        selected: _facade().List[str] = []
        if "cursor_delegate" in handlers:
            selected.append("cursor_delegate")
        elif _facade().os.environ.get("MODSTORE_CURSOR_DELEGATE_ENABLED", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            selected.append("cursor_delegate")
        if "direct_python" in handlers:
            selected.append("direct_python")
        if "llm_md" in handlers:
            selected.append("llm_md")
        return _facade()._prefer_para_with_local_fallback(selected or list(handlers), handlers)
    if multi_step and "agent" in handlers:
        selected = ["agent"]
        if "llm_md" in handlers:
            selected.append("llm_md")
        return _facade()._prefer_para_with_local_fallback(selected, handlers)
    selected = []
    if "vibe_edit" in handlers:
        selected.append("vibe_edit")
    if "agent" in handlers:
        selected.append("agent")
    if "llm_md" in handlers:
        selected.append("llm_md")
    base = selected or list(handlers)
    if para_delegate_enabled() and para_delegate_ready_for_dispatch():
        return _facade()._prefer_para_with_local_fallback(base, handlers)
    return base


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
    if employee_id in ("vibe-coding-maintainer", "change-request-auditor", "test-qa-runner") and (
        not (deterministic_council_review or reviewed_direct_burn_in)
    ):
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
            except Exception as e:
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
            except Exception as e:
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
                from modstore_server.integrations.vibe_action_handlers import dispatch_vibe_handler

                vibe_out = dispatch_vibe_handler(
                    str(handler), actions_cfg, reasoning, task, employee_id, user_id
                )
            except Exception as exc:
                _facade().logger.exception("vibe handler dispatch failed handler=%s", handler)
                vibe_out = {"handler": str(handler), "ok": False, "error": f"dispatch error: {exc}"}
            outputs.append(vibe_out or {"handler": str(handler), "ok": False, "error": "no output"})
        elif handler == "doc_sync":
            from modstore_server.integrations.doc_sync_handler import dispatch_doc_sync_handler

            outputs.append(
                dispatch_doc_sync_handler(actions_cfg, reasoning, task, employee_id, user_id)
            )
        elif handler in ("shell_exec", "ssh_exec"):
            from modstore_server.integrations.ops_action_handlers import dispatch_ops_handler

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
                employee_id, config if isinstance(config, dict) else {}, _rep_body, "report"
            )
    except Exception:
        _facade().logger.debug(
            "actions_real report im hook skipped employee_id=%s", employee_id, exc_info=True
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
