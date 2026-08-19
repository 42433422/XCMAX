# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.para_delegate_handler")


def _env_bool(name: str, default: str = "0") -> bool:
    return _facade().os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def para_delegate_enabled() -> bool:
    return _facade()._env_bool("MODSTORE_PARA_DELEGATE_ENABLED", "1")


def para_delegate_ready_for_dispatch() -> bool:
    return bool(_facade()._webhook_url() or _facade()._api_base())


def _webhook_url() -> str:
    return (_facade().os.environ.get("MODSTORE_PARA_DELEGATE_WEBHOOK") or "").strip()


def _api_base() -> str:
    return (_facade().os.environ.get("MODSTORE_PARA_API_BASE") or "").strip().rstrip("/")


def _api_timeout() -> float:
    return float(_facade().os.environ.get("MODSTORE_PARA_API_TIMEOUT_SEC", "60"))


def _wait_for_completion_default() -> bool:
    return _facade()._env_bool("MODSTORE_PARA_WAIT_FOR_COMPLETION", "1")


def _wait_timeout_sec(req: _facade().Dict[str, _facade().Any]) -> float:
    raw = req.get("wait_timeout_sec")
    if raw is None:
        raw = _facade().os.environ.get("MODSTORE_PARA_WAIT_TIMEOUT_SEC") or str(
            _facade().DEFAULT_PARA_WAIT_TIMEOUT_SEC
        )
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return _facade().DEFAULT_PARA_WAIT_TIMEOUT_SEC


def _wait_poll_sec() -> float:
    try:
        return max(1.0, float(_facade().os.environ.get("MODSTORE_PARA_WAIT_POLL_SEC", "5")))
    except ValueError:
        return 5.0


def _outbox_dir() -> _facade().Path:
    raw = (
        _facade().os.environ.get("MODSTORE_PARA_OUTBOX_DIR")
        or _facade().os.environ.get("MODSTORE_RUNTIME_DIR")
        or "/tmp/modstore_runtime"
    )
    path = _facade().Path(raw).expanduser()
    if path.name != "para_outbox":
        path = path / "para_outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _project_root(input_data: _facade().Dict[str, _facade().Any]) -> str:
    return str(
        input_data.get("project_root")
        or input_data.get("workspace_root")
        or _facade().os.environ.get("MODSTORE_GIT_REPO_ROOT")
        or _facade().os.environ.get("MODSTORE_PARA_WORKSPACE_ROOT")
        or _facade().os.environ.get("MODSTORE_REPO_ROOT")
        or ""
    ).strip()


def _mode_for_employee(employee_id: str, input_data: _facade().Dict[str, _facade().Any]) -> str:
    requested = str(input_data.get("para_mode") or input_data.get("mode") or "").strip()
    if requested:
        return requested
    if employee_id == "change-request-auditor":
        return "review"
    if employee_id == "test-qa-runner":
        return "verify"
    if employee_id == "deploy-release-officer":
        return "merge_release"
    return "code"


def _build_request(
    *, task: str, input_data: _facade().Dict[str, _facade().Any], employee_id: str
) -> _facade().Dict[str, _facade().Any]:
    workspace_root = _facade()._project_root(input_data)
    mode = _facade()._mode_for_employee(employee_id, input_data)
    report_only = _facade()._coerce_bool(
        input_data.get("report_only"), mode in {"review", "verify"}
    )
    branch = (
        str(
            input_data.get("branch")
            or input_data.get("base_branch")
            or _facade().os.environ.get("MODSTORE_PARA_BRANCH")
            or "main"
        ).strip()
        or "main"
    )
    return {
        "request_id": _facade().uuid.uuid4().hex,
        "created_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        "source": "modstore_employee_loop",
        "employee_id": employee_id,
        "mode": mode,
        "report_only": report_only,
        "title": str(input_data.get("title") or task or "")[:240],
        "task": task,
        "prompt": str(input_data.get("prompt") or task or ""),
        "workspace_root": workspace_root,
        "repo_url": str(
            input_data.get("repo_url") or _facade().os.environ.get("MODSTORE_PARA_REPO_URL") or ""
        ),
        "branch": branch,
        "device_id": str(
            input_data.get("device_id") or _facade().os.environ.get("MODSTORE_PARA_DEVICE_ID") or ""
        ),
        "tool_name": str(input_data.get("tool_name") or input_data.get("dev_tool") or ""),
        "depends_on": (
            input_data.get("depends_on") if isinstance(input_data.get("depends_on"), list) else []
        ),
        "para_task_id": str(input_data.get("para_task_id") or input_data.get("task_id") or ""),
        "dispatch_line": str(input_data.get("dispatch_line") or ""),
        "priority": str(input_data.get("priority") or ""),
        "action_item_id": input_data.get("action_item_id"),
        "record_id": input_data.get("record_id"),
        "wait_for_para": input_data.get("wait_for_para"),
        "wait_timeout_sec": input_data.get("wait_timeout_sec"),
        "evidence": (
            input_data.get("evidence") if isinstance(input_data.get("evidence"), dict) else {}
        ),
        "raw_input": input_data,
    }


def _public_request(req: _facade().Dict[str, _facade().Any]) -> _facade().Dict[str, _facade().Any]:
    return {
        k: req.get(k)
        for k in (
            "request_id",
            "employee_id",
            "mode",
            "title",
            "workspace_root",
            "repo_url",
            "branch",
            "device_id",
            "report_only",
        )
    }


def _write_outbox(req: _facade().Dict[str, _facade().Any]) -> _facade().Path:
    out = (
        _facade()._outbox_dir()
        / f"{req.get('created_at', '').replace(':', '').replace('+', 'Z')}-{req['request_id']}.json"
    )
    out.write_text(_facade().json.dumps(req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _outbox_response(
    req: _facade().Dict[str, _facade().Any], *, status: str, error: str, queued: bool = True
) -> _facade().Dict[str, _facade().Any]:
    outbox = _facade()._write_outbox(req)
    return {
        "handler": "para_delegate",
        "ok": False,
        "queued": queued,
        "status": status,
        "error": error,
        "outbox_path": str(outbox),
        "request": _facade()._public_request(req),
    }


def _allow_local_workdir() -> bool:
    return _facade()._env_bool("MODSTORE_PARA_ALLOW_LOCAL_WORKDIR", "0")


def _build_para_prompt(req: _facade().Dict[str, _facade().Any]) -> str:
    mode = str(req.get("mode") or "code")
    prompt = str(req.get("prompt") or req.get("task") or "").strip()
    report_only = bool(req.get("report_only"))
    guardrail = {
        "review": "只做代码审查和风险定位；不要修改文件，不要提交。",
        "verify": "执行必要验证并输出证据；不要用兜底结果冒充通过。",
        "merge_release": "只执行明确授权的发布/合并步骤；遇到权限或冲突必须停止并报告。",
    }.get(mode, "按任务要求完成代码修改；失败时输出真实阻塞点。")
    if report_only:
        guardrail = "REPORT-ONLY：不要修改业务文件，不要执行 git add/commit/push。请只输出结构化报告、风险、证据、下一步建议；Para agent 会把报告回写为完成证据。"
    context = [
        "",
        "MODstore loop context:",
        f"- employee_id: {req.get('employee_id') or ''}",
        f"- mode: {mode}",
        f"- report_only: {str(report_only).lower()}",
        f"- workspace_root: {req.get('workspace_root') or ''}",
        f"- action_item_id: {req.get('action_item_id') or ''}",
        f"- record_id: {req.get('record_id') or ''}",
        f"- guardrail: {guardrail}",
    ]
    if report_only:
        return "MODSTORE_REPORT_ONLY=1\nreport_only=true\n\n" + prompt + "\n" + "\n".join(context)
    return prompt + "\n" + "\n".join(context)


def _get_para_token(client: _facade().httpx.Client, base: str) -> _facade().Dict[str, str]:
    token = (
        _facade().os.environ.get("MODSTORE_PARA_AUTH_TOKEN")
        or _facade().os.environ.get("DEVFLEET_AUTH_TOKEN")
        or ""
    ).strip()
    if token:
        return {"token": token, "source": "env"}
    cached = _facade()._PARA_GUEST_AUTH_CACHE.get(base)
    if cached:
        return {"token": cached, "source": "guest_cache"}
    if not _facade()._env_bool("MODSTORE_PARA_GUEST_AUTH", "1"):
        raise RuntimeError("MODSTORE_PARA_AUTH_TOKEN 未配置，且 MODSTORE_PARA_GUEST_AUTH=0")
    resp = client.post(f"{base}/api/auth/guest")
    body: _facade().Any = {}
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {"raw": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(str(body.get("error") or body.get("detail") or resp.text[:500]))
    guest_token = str(body.get("token") or "").strip()
    if not guest_token:
        raise RuntimeError("Para guest auth response missing token")
    _facade()._PARA_GUEST_AUTH_CACHE[base] = guest_token
    return {"token": guest_token, "source": "guest"}


def _summarize_para_response(body: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(body, dict):
        return {"raw": str(body)[:1000]}
    task = body.get("task") if isinstance(body.get("task"), dict) else {}
    subtask = body.get("subtask") if isinstance(body.get("subtask"), dict) else {}
    if not subtask:
        subtasks = task.get("subTasks") if isinstance(task.get("subTasks"), list) else []
        subtask = subtasks[0] if subtasks and isinstance(subtasks[0], dict) else {}
    return {
        "task_id": task.get("id"),
        "task_status": task.get("status"),
        "subtask_id": subtask.get("id"),
        "subtask_status": subtask.get("status"),
        "progress": subtask.get("progress"),
        "subtask_branch": subtask.get("branch_name"),
        "device_name": subtask.get("device_name"),
        "error": body.get("error") or body.get("detail") or "",
    }


def _para_db_file() -> _facade().Path:
    raw = (
        _facade().os.environ.get("MODSTORE_PARA_DB_FILE")
        or "~/Library/Application Support/com.devfleet.desktop/devfleet.db"
    )
    return _facade().Path(raw).expanduser()


def _force_single_device_attempt(
    req: _facade().Dict[str, _facade().Any], accepted: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    """仅 report_only 强制 max_attempts=1；重负载保留 Para 默认/请求值以便 transient 重试。"""
    if not bool(req.get("report_only")):
        return {"ok": True, "enabled": False, "reason": "heavy_workload_keeps_retries"}
    if not _facade()._env_bool("MODSTORE_PARA_DISABLE_AUTO_RETRY", "1"):
        return {"ok": True, "enabled": False}
    task_id = str(accepted.get("task_id") or "").strip()
    subtask_id = str(accepted.get("subtask_id") or "").strip()
    if not task_id or not subtask_id:
        return {"ok": False, "error": "missing task_id/subtask_id"}
    try:
        import sqlite3

        db_file = _facade()._para_db_file()
        con = sqlite3.connect(str(db_file))
        try:
            con.execute(
                "update sub_tasks set max_attempts = 1 where id = ? and task_id = ?",
                (subtask_id, task_id),
            )
            con.commit()
        finally:
            con.close()
        return {"ok": True, "enabled": True, "task_id": task_id, "subtask_id": subtask_id}
    except Exception as exc:
        return {"ok": False, "enabled": True, "error": str(exc)[:500]}


def _resolve_max_attempts(req: _facade().Dict[str, _facade().Any]) -> int:
    if bool(req.get("report_only")):
        return 1
    raw = req.get("max_attempts")
    try:
        value = int(raw) if raw is not None else 3
    except (TypeError, ValueError):
        value = 3
    return max(1, min(5, value))


def _git_preflight_branch(repo_url: str, branch: str) -> _facade().Dict[str, _facade().Any]:
    """派工前校验远程分支；失败则不创建注定失败的任务。"""
    url = (repo_url or "").strip()
    ref = (branch or "main").strip() or "main"
    if not url:
        return {"ok": False, "error": "repo_url 为空", "failure_kind": "git_prep"}
    if (
        url.startswith("file://")
        or _facade().os.environ.get("MODSTORE_PARA_SKIP_GIT_PREFLIGHT") == "1"
    ):
        return {"ok": True, "skipped": True}
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "ls-remote", "--heads", "--exit-code", url, ref],
            capture_output=True,
            text=True,
            timeout=float(_facade().os.environ.get("MODSTORE_PARA_GIT_PREFLIGHT_SEC") or "12"),
            env={**_facade().os.environ, "GIT_TERMINAL_PROMPT": "0"},
            check=False,
        )
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            err = (proc.stderr or proc.stdout or "branch not found").strip()[:500]
            return {
                "ok": False,
                "error": f"Git 预检失败：远程不存在分支 {ref}（{err}）",
                "failure_kind": "git_prep",
            }
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"Git 预检异常：{exc}"[:500], "failure_kind": "git_prep"}


def _task_result_snapshot(body: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(body, dict):
        return {"raw": str(body)[:1000]}
    task = body.get("task") if isinstance(body.get("task"), dict) else {}
    subtasks = task.get("subTasks") if isinstance(task.get("subTasks"), list) else []
    normalized_subtasks = []
    logs_tail = []
    for sub in subtasks:
        if not isinstance(sub, dict):
            continue
        logs = sub.get("logs") if isinstance(sub.get("logs"), list) else []
        for item in logs[-5:]:
            if isinstance(item, dict):
                logs_tail.append(
                    {
                        "level": item.get("level"),
                        "content": str(item.get("content") or "")[:1000],
                        "timestamp": item.get("timestamp"),
                    }
                )
        normalized_subtasks.append(
            {
                "id": sub.get("id"),
                "status": sub.get("status"),
                "progress": sub.get("progress"),
                "branch": sub.get("branch_name"),
                "device_name": sub.get("device_name"),
                "last_error": sub.get("last_error"),
            }
        )
    return {
        "task_id": task.get("id"),
        "task_status": task.get("status"),
        "repo_url": task.get("repo_url"),
        "branch": task.get("branch"),
        "merge_commit_sha": task.get("merge_commit_sha"),
        "merge_conflict": task.get("merge_conflict"),
        "subtasks": normalized_subtasks,
        "logs_tail": logs_tail[-10:],
    }


def _wait_for_para_task(
    client: _facade().httpx.Client,
    base: str,
    token: str,
    task_id: str,
    req: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    deadline = _facade().time.monotonic() + _facade()._wait_timeout_sec(req)
    last_body: _facade().Any = {}
    terminal = {"completed", "merged", "failed", "merge_conflict"}
    while True:
        resp = client.get(
            f"{base}/api/tasks/{task_id}", headers={"Authorization": f"Bearer {token}"}
        )
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw": resp.text[:4000]}
        last_body = body
        if resp.status_code >= 400:
            return {
                "ok": False,
                "status": "para_task_poll_failed",
                "status_code": resp.status_code,
                "error": str(
                    body.get("error") or body.get("detail") or resp.text[:500]
                    if isinstance(body, dict)
                    else resp.text[:500]
                ),
                "snapshot": _facade()._task_result_snapshot(body),
            }
        task = (
            body.get("task")
            if isinstance(body, dict) and isinstance(body.get("task"), dict)
            else {}
        )
        status = str(task.get("status") or "").strip()
        if status in terminal:
            snapshot = _facade()._task_result_snapshot(body)
            ok = status in {"completed", "merged"}
            return {
                "ok": ok,
                "status": "para_task_" + (status or "unknown"),
                "error": "" if ok else _facade()._first_para_error(snapshot),
                "snapshot": snapshot,
            }
        if _facade().time.monotonic() >= deadline:
            snapshot = _facade()._task_result_snapshot(last_body)
            return {
                "ok": False,
                "status": "para_task_timeout",
                "error": f"Para task {task_id} 未在 {_facade()._wait_timeout_sec(req):.0f}s 内完成",
                "snapshot": snapshot,
            }
        _facade().time.sleep(_facade()._wait_poll_sec())


def _first_para_error(snapshot: _facade().Dict[str, _facade().Any]) -> str:
    for sub in snapshot.get("subtasks") or []:
        if not isinstance(sub, dict):
            continue
        err = str(sub.get("last_error") or "").strip()
        if err:
            return err[:1000]
    for item in snapshot.get("logs_tail") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("level") or "").lower() in {"error", "warn"}:
            return str(item.get("content") or "")[:1000]
    status = str(snapshot.get("task_status") or "").strip()
    return f"Para task status={status or 'unknown'}"
