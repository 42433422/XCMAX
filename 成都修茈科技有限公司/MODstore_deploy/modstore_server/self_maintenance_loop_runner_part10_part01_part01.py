# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _wait_for_para_device_online() -> _facade().Dict[str, _facade().Any]:
    api_base = _facade().os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    device_id = _facade().os.environ.get("MODSTORE_PARA_DEVICE_ID", "").strip()
    if not api_base or not device_id:
        return {"online": False, "reason": "missing_para_api_base_or_device_id"}
    timeout_sec = max(0, _facade()._env_int("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC", 60))
    poll_sec = max(1, _facade()._env_int("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_POLL_SEC", 5))
    deadline = _facade().time.monotonic() + timeout_sec
    last_status: _facade().Dict[str, _facade().Any] = {}
    last_error = ""
    headers: _facade().Optional[_facade().Dict[str, str]] = None
    kickstart_result: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    while True:
        try:
            if headers is None:
                headers = _facade()._guest_auth_headers(api_base)
            with _facade().httpx.Client(
                timeout=15.0, trust_env=False, verify=_facade()._para_tls_verify()
            ) as client:
                resp = client.get(f"{api_base.rstrip('/')}/api/devices", headers=headers)
                if resp.status_code in {401, 403}:
                    headers = None
                    _facade()._PARA_GUEST_AUTH_CACHE.pop(api_base.rstrip("/"), None)
                    raise RuntimeError(f"device status auth failed: {resp.status_code}")
                resp.raise_for_status()
                payload = resp.json() or {}
            devices = payload.get("devices") if isinstance(payload, dict) else payload
            if not isinstance(devices, list):
                devices = []
            target = None
            for item in devices:
                if isinstance(item, dict) and str(item.get("id") or "") == device_id:
                    target = item
                    break
            if target is None:
                last_status = {"reason": "device_not_found", "device_id": device_id}
            else:
                status = str(target.get("status") or "").lower()
                online = bool(target.get("online")) or status == "online"
                codex_tool = {}
                tools = target.get("tools")
                if isinstance(tools, list):
                    for tool in tools:
                        if isinstance(tool, dict) and str(tool.get("toolName") or "") == "codex":
                            codex_tool = tool
                            break
                tool_status = str(codex_tool.get("status") or "").lower()
                current_task = str(codex_tool.get("currentTask") or "").strip()
                stale_clear: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
                if online and current_task and (tool_status in {"", "idle"}):
                    stale_clear = _facade()._clear_stale_para_current_task(
                        device_id=device_id, current_task=current_task
                    )
                    if stale_clear.get("cleared"):
                        last_status = {
                            "codex_tool": codex_tool,
                            "device_id": device_id,
                            "name": target.get("name"),
                            "online": online,
                            "stale_clear": stale_clear,
                            "status": target.get("status"),
                        }
                        return {
                            **last_status,
                            "reason": "online_after_stale_current_task_clear",
                        }
                if online and current_task:
                    last_status = {
                        "codex_tool": codex_tool,
                        "device_id": device_id,
                        "name": target.get("name"),
                        "online": True,
                        "busy": True,
                        "stale_clear": stale_clear,
                        "status": target.get("status"),
                    }
                    if _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE", False):
                        return {**last_status, "reason": "online_busy_allowed"}
                    if kickstart_result is None:
                        kickstart_result = _facade()._kickstart_para_agent()
                        headers = None
                else:
                    orphan_reconcile: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
                    if online and (not current_task) and (tool_status in {"", "idle"}):
                        orphan_reconcile = _facade()._reconcile_orphan_para_running_tasks(
                            device_id=device_id
                        )
                    last_status = {
                        "codex_tool": codex_tool,
                        "device_id": device_id,
                        "name": target.get("name"),
                        "online": online,
                        "orphan_reconcile": orphan_reconcile,
                        "status": target.get("status"),
                    }
                    if online:
                        return {**last_status, "reason": "online"}
                    if kickstart_result is None:
                        kickstart_result = _facade()._kickstart_para_agent()
                        headers = None
        except RECOVERABLE_ERRORS as exc:
            last_error = str(exc)
            if kickstart_result is None:
                kickstart_result = _facade()._kickstart_para_agent()
                headers = None
        if _facade().time.monotonic() >= deadline:
            was_online = bool(last_status.get("online")) or bool(last_status.get("busy"))
            return {
                **last_status,
                "error": last_error,
                "kickstart": kickstart_result,
                "online": was_online,
                "reason": (
                    "device_busy_wait_timeout"
                    if last_status.get("busy")
                    else "device_online_wait_timeout"
                ),
                "timeout_sec": timeout_sec,
            }
        _facade().time.sleep(poll_sec)


def _mark_para_task_merged(
    *, api_base: str, task_id: str, merge_sha: str
) -> _facade().Dict[str, _facade().Any]:
    headers = _facade()._guest_auth_headers(api_base)
    with _facade().httpx.Client(
        timeout=30.0, trust_env=False, verify=_facade()._para_tls_verify()
    ) as client:
        resp = client.post(
            f"{api_base.rstrip('/')}/api/tasks/{task_id}/merge",
            headers=headers,
            json={"merge_commit_sha": merge_sha},
        )
        resp.raise_for_status()
        return resp.json()


def _request_para_task_merge(
    *,
    api_base: str,
    task_id: str,
    verified_base_sha: str,
    verified_target_sha: str,
) -> _facade().Dict[str, _facade().Any]:
    """Queue the already-pushed Para workspace only after loop gates pass.

    The CVM cannot reach GitHub directly, while the Para worker on the Mac can.
    Keeping this request here makes review, QA and ``autonomy_guard`` the sole
    authorization path; the device agent only prepares and pushes the branch.
    """
    workspace_root = (
        _facade().os.environ.get("MODSTORE_PARA_WORKSPACE_ROOT")
        or "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace"
    ).strip()
    verified_base_sha = str(verified_base_sha or "").strip().lower()
    verified_target_sha = str(verified_target_sha or "").strip().lower()
    if any(
        not _facade().re.fullmatch(r"[0-9a-f]{40}", sha)
        for sha in (verified_base_sha, verified_target_sha)
    ):
        raise ValueError("verified_merge_sha_invalid")
    workspace_path = str(_facade().Path(workspace_root).expanduser() / task_id)
    persisted_workspace_path = (
        f"{workspace_path}::xcmax-merge-binding-v1::" f"{verified_base_sha}::{verified_target_sha}"
    )
    headers = _facade()._guest_auth_headers(api_base)
    with _facade().httpx.Client(
        timeout=30.0, trust_env=False, verify=_facade()._para_tls_verify()
    ) as client:
        resp = client.post(
            f"{api_base.rstrip('/')}/api/tasks/{task_id}/request-merge",
            headers=headers,
            json={
                "workspace_path": persisted_workspace_path,
                "auto_merge": True,
                "verified_base_sha": verified_base_sha,
                "verified_target_sha": verified_target_sha,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    return {
        "ok": True,
        "para_response": payload,
        "reason": "merge_requested_after_loop_risk_gate",
        "workspace_path": workspace_path,
    }


def _loop_steps_roster_gate(
    steps: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    participant_ids: set[str] = set()

    def _collect(value: _facade().Any) -> None:
        if isinstance(value, dict):
            for key in (
                "employee_id",
                "employeeId",
                "emp_id",
                "empId",
                "actor",
                "assignee",
                "worker_id",
                "role_employee_id",
            ):
                text = str(value.get(key) or "").strip()
                if text:
                    participant_ids.add(text)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    _collect(child)
        elif isinstance(value, list):
            for item in value:
                _collect(item)

    _collect(steps)
    try:
        planned_ids = set(_facade().all_planned_employee_ids())
    except RECOVERABLE_ERRORS as exc:
        return {
            "action": "unknown",
            "blocking": True,
            "error": str(exc)[:300],
            "ok": False,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "duty_roster_load_error",
        }
    try:
        deployed_ids = set(_facade().duty_employee_records().keys())
    except RECOVERABLE_ERRORS as exc:
        return {
            "action": "unknown",
            "blocking": True,
            "error": str(exc)[:300],
            "ok": False,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "duty_employee_registry_load_error",
        }
    in_roster_ids = sorted((emp_id for emp_id in participant_ids if emp_id in planned_ids))
    out_of_roster_ids = sorted((emp_id for emp_id in participant_ids if emp_id not in planned_ids))
    not_deployed_ids = sorted((emp_id for emp_id in in_roster_ids if emp_id not in deployed_ids))
    if out_of_roster_ids:
        return {
            "action": "isolate",
            "blocking": True,
            "in_roster_ids": in_roster_ids,
            "ok": False,
            "out_of_roster_ids": out_of_roster_ids,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "out_of_roster_participants_detected",
        }
    if not_deployed_ids:
        return {
            "action": "hold",
            "blocking": True,
            "in_roster_ids": in_roster_ids,
            "not_deployed_ids": not_deployed_ids,
            "ok": False,
            "out_of_roster_ids": [],
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "in_roster_but_not_registered_duty_employee",
        }
    if not participant_ids:
        return {
            "action": "wait",
            "blocking": True,
            "in_roster_ids": [],
            "ok": False,
            "out_of_roster_ids": [],
            "participant_count": 0,
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "no_loop_participants_detected",
        }
    return {
        "action": "allow",
        "blocking": False,
        "in_roster_ids": in_roster_ids,
        "ok": True,
        "out_of_roster_ids": [],
        "participant_count": len(participant_ids),
        "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
        "reason": "all_participants_are_in_duty_roster",
    }


def _auto_merge_low_risk_branch(
    *,
    run_id: str,
    task_id: _facade().Optional[str],
    branch: _facade().Optional[str],
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
    if not task_id or not branch:
        return {"ok": False, "reason": "missing_task_or_branch"}
    repo_url = _facade().os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_branch = _facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    api_base = _facade().os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    allow_remote = _facade()._env_bool("MODSTORE_AUTO_MERGE_ALLOW_REMOTE", False)
    if not repo_url.startswith("file://") and (
        not (allow_remote and repo_url.startswith(("http://", "https://")))
    ):
        return {"ok": False, "reason": "repo_url_not_file_url", "repo_url": repo_url}
    if not base_branch:
        return {"ok": False, "reason": "missing_base_branch"}
    if not api_base:
        return {"ok": False, "reason": "missing_api_base"}
    if repo_url.startswith(("http://", "https://")):
        report_gate = _facade()._structured_report_gate(steps or [], branch)
        if not report_gate.get("ok"):
            return {
                "ok": False,
                "reason": report_gate.get("reason") or "structured_reports_not_passed",
                "structured_report_gate": report_gate,
            }
        branch_head_sha = _facade()._remote_branch_head(repo_url, branch)
        base_head_sha = _facade()._remote_branch_head(repo_url, base_branch)
        if not base_head_sha or not branch_head_sha:
            return {
                "ok": False,
                "reason": "remote_merge_heads_unverified",
                "base_head_sha": base_head_sha or "",
                "branch_head_sha": branch_head_sha or "",
            }
        if base_head_sha and branch_head_sha == base_head_sha:
            return {
                "ok": False,
                "reason": "remote_branch_not_advanced",
                "branch": branch,
                "branch_head_sha": branch_head_sha,
            }
        head_verification = "verified_on_cvm_and_bound_to_para_worker"
        from modstore_server.autonomy_guard_delegate import evaluate_risk

        decision = evaluate_risk(
            "self_maintenance_l1_merge",
            action_id=f"loop:{run_id}:self_maintenance_l1_merge",
            source="self_maintenance_loop.remote_merge_request",
        )
        if not decision.allowed:
            return {
                "ok": False,
                "reason": "autonomy_guard_blocked",
                "risk_decision": decision.to_dict(),
            }
        try:
            request_result = _facade()._request_para_task_merge(
                api_base=api_base,
                task_id=task_id,
                verified_base_sha=base_head_sha,
                verified_target_sha=branch_head_sha,
            )
        except RECOVERABLE_ERRORS as exc:
            return {
                "ok": False,
                "error": str(exc)[:500],
                "reason": "para_merge_request_failed",
                "risk_decision": decision.to_dict(),
            }
        merge_request_record = {
            "base_branch": base_branch,
            "base_head_sha": base_head_sha or "",
            "branch": branch,
            "branch_head_sha": branch_head_sha or "",
            "created_at": _facade()._iso(_facade()._utc_now()),
            "event": "merge_requested",
            "head_verification": head_verification,
            "ok": True,
            "para_task_id": task_id,
            "phase": "merge",
            "run_id": run_id,
            "status": "pending",
        }
        _facade()._append_ledger(merge_request_record)
        _facade()._append_governance_audit({**merge_request_record, "kind": "merge_requested"})
        return {
            "ok": True,
            "base_head_sha": base_head_sha or "",
            "branch_head_sha": branch_head_sha or "",
            "head_verification": head_verification,
            "merge_requested": True,
            "para_request": request_result,
            "reason": "merge_requested_after_loop_risk_gate",
            "risk_decision": decision.to_dict(),
            "structured_report_gate": report_gate,
        }
    workspace = _facade()._runtime_dir() / _facade().DEFAULT_MERGE_WORKSPACE_ROOT / run_id
    try:
        return _facade()._auto_merge_local_repo(
            api_base=api_base,
            base_branch=base_branch,
            branch=branch,
            repo_url=repo_url,
            run_id=run_id,
            steps=steps,
            task_id=task_id,
            workspace=workspace,
        )
    finally:
        _facade()._cleanup_merge_workspace(workspace)
