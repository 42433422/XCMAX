# mypy: disable-error-code="attr-defined, import-not-found, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


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
    except RECOVERABLE_ERRORS as exc:
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
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("failed to append deploy_dispatch ledger")
        try:
            _facade()._append_governance_audit({**record, "kind": "deploy_dispatch"})
        except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("failed to append deploy_freeze ledger")
        try:
            _facade()._append_governance_audit({**freeze_record, "kind": "deploy_freeze"})
        except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("deploy_callback HTTP fallback failed", exc_info=True)


def _record_verified_deploy_employee_metric(
    record: _facade().Dict[str, _facade().Any],
) -> bool:
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
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("failed to record verified deploy release employee metric")
        return False


def _append_deploy_receipt_event(record: _facade().Dict[str, _facade().Any]) -> None:
    """Write the same deployment receipt to loop and governance ledgers."""
    _facade()._append_ledger(record)
    _facade()._append_governance_audit(
        {**record, "kind": str(record.get("event") or "deployment_receipt")}
    )
    _facade()._record_verified_deploy_employee_metric(record)
