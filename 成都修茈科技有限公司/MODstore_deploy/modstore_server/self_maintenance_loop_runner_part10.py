# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
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
                        return {**last_status, "reason": "online_after_stale_current_task_clear"}
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
        except Exception as exc:
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


def _request_para_task_merge(*, api_base: str, task_id: str) -> _facade().Dict[str, _facade().Any]:
    """Queue the already-pushed Para workspace only after loop gates pass.

    The CVM cannot reach GitHub directly, while the Para worker on the Mac can.
    Keeping this request here makes review, QA and ``autonomy_guard`` the sole
    authorization path; the device agent only prepares and pushes the branch.
    """
    workspace_root = (
        _facade().os.environ.get("MODSTORE_PARA_WORKSPACE_ROOT")
        or "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace"
    ).strip()
    workspace_path = str(_facade().Path(workspace_root).expanduser() / task_id)
    headers = _facade()._guest_auth_headers(api_base)
    with _facade().httpx.Client(
        timeout=30.0, trust_env=False, verify=_facade()._para_tls_verify()
    ) as client:
        resp = client.post(
            f"{api_base.rstrip('/')}/api/tasks/{task_id}/request-merge",
            headers=headers,
            json={"workspace_path": workspace_path, "auto_merge": True},
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
    steps: _facade().List[_facade().Dict[str, _facade().Any]]
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
    except Exception as exc:
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
    except Exception as exc:
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
        if base_head_sha and branch_head_sha == base_head_sha:
            return {
                "ok": False,
                "reason": "remote_branch_not_advanced",
                "branch": branch,
                "branch_head_sha": branch_head_sha,
            }
        head_verification = (
            "verified_on_cvm" if branch_head_sha else "delegated_to_para_merge_worker"
        )
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
            request_result = _facade()._request_para_task_merge(api_base=api_base, task_id=task_id)
        except Exception as exc:
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


def _auto_merge_local_repo(
    *,
    api_base: str,
    base_branch: str,
    branch: str,
    repo_url: str,
    run_id: str,
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]],
    task_id: str,
    workspace: _facade().Path,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.autonomy_guard_delegate import evaluate_risk

    decision = evaluate_risk(
        "self_maintenance_l1_merge",
        action_id=f"loop:{run_id}:self_maintenance_l1_merge",
        source="self_maintenance_loop.auto_merge",
    )
    if not decision.allowed:
        return {
            "ok": False,
            "reason": "autonomy_guard_blocked",
            "risk_decision": decision.to_dict(),
        }
    files = _facade()._changed_files_for_branch(
        repo_url=repo_url, base_branch=base_branch, branch=branch, workspace=workspace
    )
    if not files:
        return {
            "ok": False,
            "reason": "branch_not_on_remote_or_empty",
            "branch": branch,
            "changed_files": [],
        }
    diff_stats = _facade()._diff_numstat_for_branch(
        base_branch=base_branch, branch=branch, workspace=workspace
    )
    diff_excerpt = _facade()._run_cmd_excerpt(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--find-renames",
            "--unified=3",
            f"origin/{base_branch}...origin/{branch}",
        ],
        cwd=workspace,
        timeout=180,
        max_chars=20000,
    )
    kb_validation = _facade()._validate_kb_json_changes_for_auto_merge(
        branch=branch, files=files, workspace=workspace
    )
    if not kb_validation.get("ok"):
        return {
            "changed_files": files,
            "kb_validation": kb_validation,
            "ok": False,
            "reason": "kb_json_schema_validation_failed",
        }
    policy = _facade()._assess_branch_auto_merge_policy(
        files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        kb_validation=kb_validation,
        memory=_facade()._load_loop_memory(),
        steps=steps,
    )
    if not policy.get("ok"):
        return policy
    _facade()._run_cmd(["git", "merge", "--no-ff", "--no-edit", f"origin/{branch}"], cwd=workspace)
    merge_sha = _facade()._run_cmd(["git", "rev-parse", "HEAD"], cwd=workspace)
    _push_proc = _facade().subprocess.run(
        ["git", "push", "origin", f"HEAD:{base_branch}"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if _push_proc.returncode != 0:
        return {
            "ok": False,
            "reason": "push_to_origin_failed",
            "merge_sha": merge_sha,
            "push_stderr": (_push_proc.stderr or "")[:500],
            "branch": branch,
        }
    para_update = _facade()._mark_para_task_merged(
        api_base=api_base, task_id=task_id, merge_sha=merge_sha
    )
    return {
        **policy,
        "diff_excerpt": diff_excerpt,
        "kb_validation": kb_validation,
        "merge_commit_sha": merge_sha,
        "ok": True,
        "para_update": para_update,
        "reason": "merged_low_risk_branch",
        "workspace": str(workspace),
    }


def _auto_dispatch_deploy_envs() -> _facade().List[str]:
    """Return ordered deploy envs when auto-dispatch master switch is on.

    默认仅 staging；production 必须显式写在 ENVS 中才会出现。
    staging always precedes production when both are requested.
    """
    if not _facade()._auto_dispatch_deploy_enabled():
        return []
    raw = str(
        _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_ENVS", "") or ""
    ).strip()
    if not raw:
        return ["staging"]
    requested: _facade().List[str] = []
    for part in raw.split(","):
        env = part.strip().lower()
        if env in {"staging", "production"} and env not in requested:
            requested.append(env)
    return [env for env in ("staging", "production") if env in requested]


def _dispatch_fhd_deploy_action(
    *, environment: str, action: str, action_id: str
) -> _facade().Dict[str, _facade().Any]:
    """Dispatch ``fhd-deploy.yml`` via ``gh workflow run`` (or dry-run skip)."""
    gh_command = f"gh workflow run fhd-deploy.yml -f environment={environment} -f action={action} -f action_id={action_id}"
    deploy_cwd = _facade().os.environ.get("MODSTORE_GIT_REPO_ROOT") or None
    if _facade()._env_flag_enabled("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_DRY_RUN"):
        return {
            "ok": True,
            "reason": "dry_run_skipped",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": "",
            "gh_exit_code": 0,
            "action_id": action_id,
            "deploy_cwd": deploy_cwd,
        }
    try:
        proc = _facade().subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                "fhd-deploy.yml",
                "-f",
                f"environment={environment}",
                "-f",
                f"action={action}",
                "-f",
                f"action_id={action_id}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=deploy_cwd,
        )
        ok = proc.returncode == 0
        output = f"{proc.stdout or ''}{proc.stderr or ''}".strip()
        return {
            "ok": ok,
            "reason": "dispatched" if ok else "gh_non_zero_exit",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": output,
            "gh_exit_code": int(proc.returncode),
            "action_id": action_id,
            "deploy_cwd": deploy_cwd,
        }
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"dispatch_threw:{exc}",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": str(exc),
            "gh_exit_code": -1,
            "action_id": action_id,
        }


def _dispatch_deploy_for_merge(
    *, run_id: str, branch: str, environments: _facade().List[str]
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """Apply-latest per env after low-risk merge; freeze and stop on first failure."""
    results: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for environment in environments:
        action_id = f"loop:{run_id}:deploy:{environment}"
        result = _facade()._dispatch_fhd_deploy_action(
            environment=environment, action="apply-latest", action_id=action_id
        )
        record = {
            "event": "deploy_dispatch",
            "run_id": run_id,
            "branch": branch,
            "environment": environment,
            "action": "apply-latest",
            "ok": bool(result.get("ok")),
            "reason": result.get("reason"),
            "action_id": action_id,
            "gh_command": result.get("gh_command"),
            "gh_exit_code": result.get("gh_exit_code"),
        }
        try:
            _facade()._append_ledger(record)
        except Exception:
            _facade().logger.exception("failed to append deploy_dispatch ledger")
        try:
            _facade()._append_governance_audit({**record, "kind": "deploy_dispatch"})
        except Exception:
            _facade().logger.exception("failed to append deploy_dispatch governance audit")
        results.append(result)
        if result.get("ok"):
            continue
        freeze_id = f"loop:{run_id}:freeze:{environment}"
        freeze_result = _facade()._dispatch_fhd_deploy_action(
            environment=environment, action="freeze-manifest", action_id=freeze_id
        )
        freeze_record = {
            "event": "deploy_freeze",
            "run_id": run_id,
            "branch": branch,
            "environment": environment,
            "action": "freeze-manifest",
            "ok": bool(freeze_result.get("ok")),
            "reason": freeze_result.get("reason"),
            "action_id": freeze_id,
            "triggered_by": action_id,
        }
        try:
            _facade()._append_ledger(freeze_record)
        except Exception:
            _facade().logger.exception("failed to append deploy_freeze ledger")
        try:
            _facade()._append_governance_audit({**freeze_record, "kind": "deploy_freeze"})
        except Exception:
            _facade().logger.exception("failed to append deploy_freeze governance audit")
        try:
            _facade()._emit_deploy_callback(
                phase="dispatch_failed",
                payload={
                    **record,
                    "freeze_ok": bool(freeze_result.get("ok")),
                    "freeze_action_id": freeze_id,
                },
                action_id=action_id,
            )
            _facade()._emit_deploy_callback(
                phase="freeze_manifest", payload=freeze_record, action_id=freeze_id
            )
        except Exception:
            _facade().logger.exception("failed to emit deploy_callback after freeze")
        break
    return results


def _emit_deploy_callback(
    *,
    phase: str,
    payload: _facade().Dict[str, _facade().Any],
    action_id: _facade().Optional[str] = None,
) -> None:
    """Fail-open 调用 FHD autonomy deploy_callback（或等价 ingest HTTP）。"""
    try:
        autonomy_scripts = (
            _facade().Path(__file__).resolve().parents[3] / "FHD" / "scripts" / "autonomy"
        )
        candidates = [
            autonomy_scripts,
            _facade().Path(_facade().os.environ.get("XCAGI_FHD_RUNTIME_ROOT", ""))
            / "scripts"
            / "autonomy",
            _facade().Path(__file__).resolve().parents[2] / "FHD" / "scripts" / "autonomy",
        ]
        for candidate in candidates:
            if candidate and (candidate / "autonomy_callback.py").is_file():
                if str(candidate) not in _facade().sys.path:
                    _facade().sys.path.insert(0, str(candidate))
                from autonomy_callback import deploy_callback

                deploy_callback(phase, payload, source="self_maintenance", action_id=action_id)
                return
    except Exception:
        _facade().logger.debug("deploy_callback import path failed", exc_info=True)
    base_url = (_facade().os.environ.get("FHD_API_BASE_URL") or "").strip()
    token = (
        _facade().os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or _facade().os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()
    if not base_url or not token:
        return
    body: _facade().Dict[str, _facade().Any] = {
        "action": f"deploy:{phase}",
        "payload": {**payload, "callback_event": f"deploy:{phase}"},
        "source": "self_maintenance",
    }
    if action_id:
        body["action_id"] = action_id
    try:
        with _facade().httpx.Client(timeout=10.0) as client:
            client.post(
                f"{base_url.rstrip('/')}/api/ops/autonomy/actions/ingest",
                headers={"X-Autonomy-Token": token, "Content-Type": "application/json"},
                json=body,
            )
    except Exception:
        _facade().logger.debug("deploy_callback HTTP fallback failed", exc_info=True)


def _record_verified_deploy_employee_metric(record: _facade().Dict[str, _facade().Any]) -> bool:
    """Credit the release officer only for an exact verified production deploy.

    Dispatch acceptance, staging success and uncorrelated health checks are not
    employee evidence.  The deterministic task marker makes callback retries
    idempotent.
    """
    if not (
        str(record.get("event") or "") == "post_deploy_verified"
        and str(record.get("environment") or "").strip().lower() == "production"
        and (record.get("ok") is True)
        and (record.get("identity_verified") is True)
        and (str(record.get("status") or "").strip().lower() == "verified")
    ):
        return False
    run_id = str(record.get("run_id") or "").strip()
    merge_sha = str(record.get("merge_sha") or "").strip().lower()
    workflow_run_id = str(record.get("workflow_run_id") or "").strip()
    if (
        not run_id
        or not _facade().re.fullmatch("[0-9a-f]{40,64}", merge_sha)
        or (not workflow_run_id)
    ):
        return False
    marker = f"[deploy-receipt:{run_id}:{merge_sha[:12]}:{workflow_run_id}]"[:128]
    try:
        sf = _facade().get_session_factory()
        with sf() as session:
            exists = (
                session.query(_facade().EmployeeExecutionMetric.id)
                .filter(
                    _facade().EmployeeExecutionMetric.employee_id == "deploy-release-officer",
                    _facade().EmployeeExecutionMetric.task == marker,
                    _facade().EmployeeExecutionMetric.status == "success",
                )
                .first()
            )
            if exists:
                return False
            user = (
                session.query(_facade().User)
                .filter(_facade().User.is_admin.is_(True))
                .order_by(_facade().User.id.asc())
                .first()
                or session.query(_facade().User).order_by(_facade().User.id.asc()).first()
            )
            if user is None:
                _facade().logger.warning("deploy receipt metric skipped: no user row")
                return False
            session.add(
                _facade().EmployeeExecutionMetric(
                    user_id=int(user.id),
                    employee_id="deploy-release-officer",
                    task=marker,
                    status="success",
                    duration_ms=0.0,
                    llm_tokens=0,
                    error="",
                    failure_kind="",
                )
            )
            session.commit()
        return True
    except Exception:
        _facade().logger.exception("failed to record verified deploy release employee metric")
        return False


def _append_deploy_receipt_event(record: _facade().Dict[str, _facade().Any]) -> None:
    """Write the same deployment receipt to loop and governance ledgers."""
    _facade()._append_ledger(record)
    _facade()._append_governance_audit(
        {**record, "kind": str(record.get("event") or "deployment_receipt")}
    )
    _facade()._record_verified_deploy_employee_metric(record)


def _run_deploy_receipts_after_merge(
    *, run_id: str, merge_result: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    """Run staging receipts only after a concrete pushed merge.

    This path is inert by default. It uses a new switch so a legacy dispatch
    flag cannot silently activate it. Production requires its own explicit
    switch and remains gated on a verified staging receipt.
    """
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", False):
        return {"enabled": False, "reason": "deploy_receipts_disabled"}
    if bool(merge_result.get("merge_requested")):
        return {"enabled": True, "ok": False, "reason": "merge_not_completed"}
    merge_sha = str(merge_result.get("merge_commit_sha") or "").strip()
    if not merge_sha:
        return {"enabled": True, "ok": False, "reason": "merge_sha_missing"}
    repo_root_text = str(_facade().os.environ.get("MODSTORE_GIT_REPO_ROOT") or "").strip()
    deploy_ref = str(
        _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_DEPLOY_REF")
        or _facade().os.environ.get("MODSTORE_PARA_BRANCH")
        or ""
    ).strip()
    try:
        from modstore_server.self_maintenance_deploy_receipts import (
            GhActionsDeploymentGateway,
            run_staged_deployment_chain,
        )

        gateway = GhActionsDeploymentGateway.from_environment(
            repo_root=_facade().Path(repo_root_text).expanduser(), ref=deploy_ref
        )
        result = run_staged_deployment_chain(
            gateway=gateway,
            record_event=_facade()._append_deploy_receipt_event,
            run_id=run_id,
            merge_sha=merge_sha,
            allow_production=_facade()._env_bool(
                "MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", False
            ),
        )
        return {"enabled": True, **result}
    except Exception as exc:
        failure = {
            "event": "deploy_verification_failed",
            "phase": "deployment",
            "run_id": run_id,
            "merge_sha": merge_sha,
            "environment": "staging",
            "status": "failed",
            "ok": False,
            "reason": "deploy_receipt_setup_failed",
            "error_type": type(exc).__name__,
        }
        _facade()._append_deploy_receipt_event(failure)
        return {"enabled": True, "ok": False, "reason": "deploy_receipt_setup_failed"}
