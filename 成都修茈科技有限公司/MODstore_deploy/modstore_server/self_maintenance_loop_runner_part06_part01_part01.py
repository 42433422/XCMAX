# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _fetch_para_task_report_excerpt(
    task_id: _facade().Optional[str],
    subtask_id: _facade().Optional[str],
    limit: int = 8000,
) -> str:
    if not task_id:
        return ""
    api_base = _facade().os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    if not api_base:
        return ""
    try:
        headers = _facade()._guest_auth_headers(api_base)
        with _facade().httpx.Client(
            timeout=20.0, trust_env=False, verify=_facade()._para_tls_verify()
        ) as client:
            resp = client.get(f"{api_base.rstrip('/')}/api/tasks/{task_id}", headers=headers)
            resp.raise_for_status()
            task = (resp.json() or {}).get("task") or {}
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("failed to fetch Para task report logs task_id=%s", task_id)
        return ""
    chunks: _facade().List[str] = []
    for subtask in task.get("subTasks") or task.get("subtasks") or []:
        if subtask_id and str(subtask.get("id")) != str(subtask_id):
            continue
        for log in subtask.get("logs") or []:
            content = str(log.get("content") or "").strip()
            if content:
                chunks.append(content)
    return "\n".join(chunks)[-limit:]


def _fetch_para_task_state(api_base: str, task_id: str) -> _facade().Dict[str, _facade().Any]:
    headers = _facade()._guest_auth_headers(api_base)
    with _facade().httpx.Client(
        timeout=20.0, trust_env=False, verify=_facade()._para_tls_verify()
    ) as client:
        resp = client.get(f"{api_base.rstrip('/')}/api/tasks/{task_id}", headers=headers)
        resp.raise_for_status()
        task = (resp.json() or {}).get("task") or {}
    return task if isinstance(task, dict) else {}


def _reconcile_requested_merge_feedback(
    memory: _facade().Dict[str, _facade().Any],
    *,
    api_base: _facade().Optional[str] = None,
    task_fetcher: _facade().Optional[_facade().Any] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Settle requested merges from Para without confusing request with success.

    ``completed_merge_requested`` remains open until Para reports a real merged
    SHA. Any terminal merge failure becomes an automated remediation item with
    the exact findings. The next code employee starts from the configured clean
    base and uses the rejected branch only as evidence, preventing retries from
    accumulating an ever-larger inherited diff.
    """
    base = (api_base or _facade().os.environ.get("MODSTORE_PARA_API_BASE") or "").strip()
    recent_runs = memory.get("recent_runs")
    open_items = memory.get("open_items")
    if not base or not isinstance(recent_runs, list):
        return {"changed": False, "merged": 0, "remediation_added": 0}
    if not isinstance(open_items, list):
        open_items = []
        memory["open_items"] = open_items
    fetcher = task_fetcher or _facade()._fetch_para_task_state
    changed = False
    merged = 0
    remediation_added = 0
    checked_task_ids: set[str] = set()
    for run in reversed(recent_runs):
        if not isinstance(run, dict):
            continue
        if str(run.get("status") or "") != "completed_merge_requested":
            continue
        task_id = str(run.get("para_task_id") or "").strip()
        if not task_id or task_id in checked_task_ids:
            continue
        checked_task_ids.add(task_id)
        try:
            task = fetcher(base, task_id)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception(
                "failed to reconcile requested Para merge task_id=%s", task_id
            )
            continue
        task_status = str(task.get("status") or "").strip().lower()
        branch = str(run.get("branch") or "").strip()
        if task_status == "merged" and str(task.get("merge_commit_sha") or "").strip():
            merge_sha = str(task.get("merge_commit_sha") or "").strip()
            existing_receipt = run.get("merge_reconciliation")
            receipt = {
                "merge_commit_sha": merge_sha,
                "reconciled_at": _facade()._iso(_facade()._utc_now()),
                "status": "merged",
                "task_id": task_id,
            }
            if not (
                isinstance(existing_receipt, dict)
                and existing_receipt.get("status") == "merged"
                and (existing_receipt.get("task_id") == task_id)
                and (existing_receipt.get("merge_commit_sha") == merge_sha)
            ):
                run["merge_reconciliation"] = receipt
                changed = True
            closed = _facade()._close_open_items_in_memory(
                memory,
                actor="para_merge_reconciler",
                branches=[branch],
                resolution_reason="para_reported_real_merge_sha",
                task_ids=[task_id],
            )
            if closed.get("closed_count"):
                changed = True
            merged += 1
            continue
        terminal_failure_statuses = {
            "cancelled",
            "dispatch_error",
            "dispatch_failed",
            "failed",
            "merge_conflict",
        }
        if task_status not in terminal_failure_statuses:
            continue
        conflict = task.get("merge_conflict")
        if not isinstance(conflict, dict):
            conflict = {}
        source = str(conflict.get("source") or "").strip()
        detail = str(
            conflict.get("detail")
            or task.get("fail_reason")
            or task.get("error")
            or f"Para merge task ended with status={task_status}"
        ).strip()[:4000]
        reason, item_kind, open_items, changed = _facade().reconcile_para_merge_failure_state(
            memory, changed, detail, source, task_id, task_status
        )
        existing_receipt = run.get("merge_reconciliation")
        receipt = {
            "detail": detail,
            "reconciled_at": _facade()._iso(_facade()._utc_now()),
            "source": source,
            "status": task_status,
            "task_id": task_id,
        }
        if not (
            isinstance(existing_receipt, dict)
            and existing_receipt.get("status") == task_status
            and (existing_receipt.get("task_id") == task_id)
            and (existing_receipt.get("source") == source)
            and (existing_receipt.get("detail") == detail)
        ):
            run["merge_reconciliation"] = receipt
            changed = True
        already_open = any(
            (
                isinstance(item, dict)
                and str(item.get("task_id") or item.get("para_task_id") or "") == task_id
                and (item.get("reason") == reason)
                and (item.get("kind") == item_kind)
                for item in open_items
            )
        )
        if not already_open:
            rejected_branch = str(conflict.get("branch_name") or branch).strip()
            resume_from_clean_baseline = _facade().resume_from_clean_baseline_for_para_merge(
                reason, detail
            )
            veto_meta = (
                _facade().classify_para_merge_review_detail(detail)
                if source == "ai-review-veto"
                else {}
            )
            open_item: _facade().Dict[str, _facade().Any] = {
                "branch": rejected_branch,
                "created_at": _facade()._iso(_facade()._utc_now()),
                "detail": detail,
                "kind": item_kind,
                "para_task_id": task_id,
                "reason": reason,
                "rejected_branch": rejected_branch,
                "resume_from_clean_baseline": resume_from_clean_baseline,
                "review_feedback": detail if source == "ai-review-veto" else "",
                "run_id": str(run.get("run_id") or "").strip(),
                "source": source,
                "task_status": task_status,
                "task_id": task_id,
            }
            if source == "ai-review-veto":
                open_item["review_actionable_findings"] = veto_meta.get("actionable_code_findings")
                open_item["review_veto_branch_hint"] = veto_meta.get("branch_hint") or ""
                open_item["review_veto_code"] = veto_meta.get("veto_code") or ""
                if veto_meta.get("review_diff_chars") is not None:
                    open_item["review_diff_chars"] = veto_meta["review_diff_chars"]
            open_items.append(open_item)
            changed = True
            remediation_added += 1
    if changed:
        memory["open_items"] = (memory.get("open_items") or [])[-50:]
        memory["updated_at"] = _facade()._iso(_facade()._utc_now())
    return {
        "changed": changed,
        "merged": merged,
        "remediation_added": remediation_added,
    }


def _base_para_input(
    extra: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    data: _facade().Dict[str, _facade().Any] = {
        "branch": _facade().os.environ.get("MODSTORE_PARA_BRANCH"),
        "device_id": _facade().os.environ.get("MODSTORE_PARA_DEVICE_ID"),
        "repo_url": _facade().os.environ.get("MODSTORE_PARA_REPO_URL"),
        "suppress_lifecycle_events": True,
        "wait_for_para": True,
        "wait_timeout_sec": _facade()._env_int("MODSTORE_PARA_WAIT_TIMEOUT_SEC", 1800),
        "project_root": _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT")
        or "/root/XCMAX",
    }
    if extra:
        data.update(extra)
    return data


_FOCUSED_TEST_CAPABILITY_CACHE = {}
_FOCUSED_TEST_CAPABILITY_TTL_SECONDS = 60.0


def _focused_test_environment_fingerprint(candidate: _facade().Path) -> tuple:
    """Describe the executable and dependency locations that affect the probe."""
    venv_root = candidate.parent.parent
    site_packages = sorted((venv_root / "lib").glob("python*/site-packages"))
    watched_paths = [candidate, venv_root / "pyvenv.cfg", *site_packages]
    for site_package in site_packages:
        for distribution in ("apscheduler", "pytest"):
            watched_paths.extend(sorted(site_package.glob(f"{distribution}*")))
    fingerprint = []
    for path in watched_paths:
        try:
            stat = path.stat()
            fingerprint.append(
                (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            )
        except OSError:
            fingerprint.append((str(path), None))
    return (
        _facade().os.environ.get("PYTHONHOME"),
        _facade().os.environ.get("PYTHONPATH"),
        tuple(fingerprint),
    )


def _python_supports_focused_tests(candidate: _facade().Path) -> bool:
    """Return whether a Python executable has the loop's test dependencies."""
    if not candidate.is_file() or not _facade().os.access(candidate, _facade().os.X_OK):
        return False
    fingerprint = _focused_test_environment_fingerprint(candidate)
    now = _facade().time.monotonic()
    cached = _FOCUSED_TEST_CAPABILITY_CACHE.get(str(candidate))
    if (
        cached
        and cached[0] == fingerprint
        and now - cached[1] < _FOCUSED_TEST_CAPABILITY_TTL_SECONDS
    ):
        return cached[2]
    try:
        probe = _facade().subprocess.run(
            [str(candidate), "-c", "import apscheduler, pytest"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, _facade().subprocess.SubprocessError):
        supported = False
    else:
        supported = probe.returncode == 0
    _FOCUSED_TEST_CAPABILITY_CACHE[str(candidate)] = (fingerprint, now, supported)
    return supported


def _focused_test_command() -> str:
    """Resolve one executable QA command from the running MODstore environment.

    The scheduler may itself run from the lighter FHD venv, which intentionally
    does not install pytest.  Prefer the MODstore venv used for repository tests
    and expose explicit overrides for production or isolated runners.
    """
    command_override = (
        _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", "").strip()
    )
    if command_override:
        return command_override
    test_python_override = (
        _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_TEST_PYTHON", "").strip()
    )
    deploy_root = _facade().Path(
        _facade().os.environ.get("MODSTORE_DEPLOY_ROOT")
        or _facade().Path(__file__).resolve().parent.parent
    )
    runtime_root = _facade().os.environ.get("MODSTORE_RUNTIME_ROOT", "").strip()
    candidates = [
        _facade().Path(test_python_override).expanduser() if test_python_override else None,
        deploy_root / ".venv" / "bin" / "python",
        (
            _facade().Path(runtime_root).expanduser()
            / "MODstore_deploy"
            / ".venv"
            / "bin"
            / "python"
            if runtime_root
            else None
        ),
        _facade().Path(_facade().sys.executable),
    ]
    test_python = next(
        (
            candidate
            for candidate in candidates
            if candidate and _facade()._python_supports_focused_tests(candidate)
        ),
        _facade().Path(_facade().sys.executable),
    )
    test_path = (
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py"
    )
    return (
        f"{_facade().shlex.quote(str(test_python))} -m pytest {_facade().shlex.quote(test_path)} -q"
    )


def _code_task_text(
    run_id: str,
    evaluation: _facade().Dict[str, _facade().Any],
    memory: _facade().Dict[str, _facade().Any],
    resume_candidate: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> str:
    gaps = ", ".join(evaluation.get("gaps") or []) or "none"
    focused_test_command = _facade()._focused_test_command()
    base_branch = _facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip() or "main"
    black_command, isort_command = _facade()._diff_quality_commands(
        base_ref=f"origin/{base_branch}", target_ref="WORKTREE"
    )
    evolution_context_dict = _facade().build_self_evolution_context(
        run_id=run_id, evaluation=evaluation, memory=memory
    )
    evolution_context = _facade().render_self_evolution_context(evolution_context_dict)
    fix_hits = evolution_context_dict.get("fix_knowledge_hits") or []
    fix_digest_parts = []
    for idx, hit in enumerate(fix_hits[:3], 1):
        symptom = str(hit.get("symptom") or "")[:200]
        root_cause = str(hit.get("root_cause") or "")[:200]
        fix_diff = str(hit.get("fix_diff") or "")[:1500]
        if not symptom and (not fix_diff):
            continue
        fix_digest_parts.append(
            f"[HISTORICAL FIX #{idx}]\n  symptom: {symptom}\n  root_cause: {root_cause}\n  fix_diff (first 1500 chars):\n{fix_diff}"
        )
    fix_digest = (
        "\n\n".join(fix_digest_parts) if fix_digest_parts else "(no historical fixes matched)"
    )
    last_decision = memory.get("last_policy_decision") if isinstance(memory, dict) else None
    selected_remediation: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    if (
        isinstance(resume_candidate, dict)
        and resume_candidate.get("reason") == "resume_safety_score_remediation"
    ):
        selected_remediation = resume_candidate
        open_items = memory.get("open_items") if isinstance(memory, dict) else None
        if isinstance(open_items, list):
            selected_branch = str(resume_candidate.get("branch") or "")
            selected_run_id = str(resume_candidate.get("failed_run_id") or "")
            selected_task_id = str(resume_candidate.get("para_task_id") or "")
            for item in reversed(open_items):
                if not isinstance(item, dict):
                    continue
                item_task_id = str(item.get("task_id") or item.get("para_task_id") or "")
                if (
                    selected_branch
                    and str(item.get("branch") or "") == selected_branch
                    or (selected_run_id and str(item.get("run_id") or "") == selected_run_id)
                    or (selected_task_id and item_task_id == selected_task_id)
                ):
                    selected_remediation = {**item, **resume_candidate}
                    break
    elif isinstance(last_decision, dict) and str(last_decision.get("reason") or "") in {
        "auto_merge_safety_score_v2_too_low",
        "auto_merge_safety_score_v3_too_low",
        "risk_score_v3_below_threshold_or_blocked",
    }:
        selected_remediation = last_decision
    external_review_remediation = _facade().external_review_remediation_prompt(resume_candidate)
    external_merge_remediation = _facade().external_merge_remediation_prompt(resume_candidate)
    retort_scope_remediation = _facade().retort_remediation.retort_scope_remediation_prompt(
        resume_candidate
    )
    structured_report_remediation = _facade().structured_report_remediation_prompt(
        memory, resume_candidate
    )
    score_remediation = ""
    if isinstance(selected_remediation, dict):
        merge_result = (
            selected_remediation.get("merge_result")
            if isinstance(selected_remediation.get("merge_result"), dict)
            else {}
        )
        v2 = (
            merge_result.get("safety_score_v2")
            if isinstance(merge_result.get("safety_score_v2"), dict)
            else {}
        )
        v3 = (
            merge_result.get("safety_score_v3")
            if isinstance(merge_result.get("safety_score_v3"), dict)
            else {}
        )
        review = (
            (v2.get("semantic_llm_analysis") or {}).get("reports", {}).get("review", {})
            if isinstance(v2.get("semantic_llm_analysis"), dict)
            else {}
        )
        remediation_evidence = {
            "branch": selected_remediation.get("branch"),
            "failed_run_id": selected_remediation.get("failed_run_id")
            or selected_remediation.get("run_id"),
            "reason": selected_remediation.get("reason"),
            "review_max_severity": review.get("max_severity"),
            "review_tested_commands": review.get("tested_commands"),
            "safety_score_v2": v2.get("score"),
            "safety_score_v2_min": v2.get("min_allowed"),
            "safety_score_v3": v3.get("score"),
            "safety_score_v3_min": v3.get("min_allowed"),
        }
        score_remediation = f"\n\n=== EXISTING BRANCH SCORE REMEDIATION ===\nYour workspace is already checked out on a newly created isolated remediation work branch whose immutable base is `{str(selected_remediation.get('branch') or '').strip()}`. Do not checkout, switch to, reset, commit, or push directly to that immutable base branch. Make the follow-up on the current checked-out work branch only; do not replace its production fix with an unrelated change. The previous independent review/score did not authorize merge. Address its missing evidence on this candidate, especially any promised focused regression test that is absent. A test-only follow-up commit is valid here because the existing candidate already contains the production fix. Run that focused test and the mandatory loop policy suite, then commit the current work branch and push HEAD to that same work-branch name. Report `git branch --show-current` and `git rev-parse HEAD` as delivery evidence. Do not lower, bypass, or game either safety threshold. Evidence: {_facade().json.dumps(remediation_evidence, ensure_ascii=False, sort_keys=True)}"
    return f"""Run a real MODstore self-maintenance improvement task. === SELF_MAINTENANCE_CANONICAL_MERGE_BASE:main === Use the previous loop memory and current evidence gaps to fix the highest-value executable gap in the self-maintenance loop. MANDATORY: Before reasoning from scratch, you MUST check the HISTORICAL FIXES below. If a historical fix's symptom matches the current gap and its fix_diff still applies safely, you MUST reuse that fix first (apply the diff or its approach) instead of inventing a new solution. Only when no historical fix applies may you reason from scratch. If there is no bug gap, choose one proactive task from performance, coverage, or tech_debt signals. When you fix a bug, write the symptom/root_cause/fix_diff triad under FHD/XCAGI/kb/fixes; every changed fix JSON MUST conform to the EXACT schema below (all fields required, no extras that break validation):\n```json\n{{\n  "schema_version": 1,\n  "kind": "fix",\n  "created_at": "2026-07-20T12:00:00+00:00",\n  "symptom": "<non-empty string: observed symptom>",\n  "root_cause": "<non-empty string: root cause>",\n  "fix_diff": "<non-empty string: diff or description>",\n  "metadata": {{"component": "...", "files": ["..."]}},\n  "executable_template": {{\n    "applicability_check": "<non-empty string>",\n    "patch_strategy": "<non-empty string>",\n    "rollback_plan": "<non-empty string>",\n    "required_tests": ["test_a.py", "test_b.py"]\n  }}\n}}\n```\nCRITICAL: executable_template MUST be an object (the executable_template object must not be a string, null, or omitted) with non-empty string fields applicability_check/patch_strategy/rollback_plan AND a string-list required_tests. Common failure: writing fix_diff as a description but forgetting executable_template, or setting executable_template to a string. MANDATORY PRE-PUSH VALIDATION: Before committing/pushing any KB JSON file, you MUST run `python -c "from modstore_server.self_evolution_knowledge import validate_kb_payload; import json; validate_kb_payload('fixes', json.load(open('FHD/XCAGI/kb/fixes/<file>.json')))"` (or 'patterns' for pattern files) and require it to return without raising. If validation raises ValueError, FIX the JSON before pushing — the loop will reject KB-schema-invalid branches with a `kb-schema-failed` PR label and retry up to 2 times before escalating to human review. Validate each changed KB JSON with self_evolution_knowledge.validate_kb_payload before reporting completion. when review/QA approves a reusable change, write the pattern under FHD/XCAGI/kb/patterns. Do not create marker-only/status-only changes as proof of completion. Prefer changes that make scheduler gating, loop memory, report-only review/QA, or policy decisions more directly executable. \n\n=== OUTPUT QUALITY REQUIREMENTS ===\n- State one evidence-backed symptom and root cause before changing code.\n- Make the smallest production change that fixes that root cause and add focused regression tests; do not submit marker-only, comment-only, formatting-only, or test-only work as the fix.\n- DIFF PROTOCOL: When describing patches in the report or KB fix_diff, emit a complete unified diff that `git apply` / `git apply --check` can consume (must include `diff --git`, `---/+++`, and `@@` hunks). Forbidden: summary-only answers, bullet paraphrases of changes, or partial hunks without file headers.\n- Prefer committing real file edits in the worktree (git add/commit/push) over pasting diffs; if you paste a patch, it must still be git-applyable.\n- Keep production scope and changed lines minimal enough for a legitimate safety_score_v2 target of at least 90; never hide, omit, or misclassify risky files or behavior to influence the score.\n- Leave review and QA to the independent report-only employees; do not self-approve or fabricate their evidence.\n- Report every verification command with its real exit code and concise passing output.\nBefore reporting completion, execute `{focused_test_command}` in the target branch and require exit code 0. Also run `{black_command}` and `{isort_command}` from `成都修茈科技有限公司/MODstore_deploy`; these commands deterministically check every changed Python file in the target diff without importing unrelated historical formatting debt. Also run `python scripts/dev/source_governance.py --top 10` from the repository root; all three are mandatory merge-readiness gates and must exit 0. If and only if there is no safe actionable source change, update `{_facade().DEFAULT_STATUS_FILE}` with LOOP_RUN_ID={run_id!r}, LOOP_KIND='scheduled_self_maintenance', BRIDGE='para_main_device', UPDATED_AT to the current UTC time, and a clear NO_ACTION_REASON explaining why no source change was safe. Do not edit runtime-only, ignored, .devfleet, or .trae files. MANDATORY SELF-VERIFICATION: Before reporting completion, you MUST run the relevant tests/lint/type-check commands for the files you changed and paste the passing output (exit code 0) in your report. If any command fails, fix your changes and retry — do NOT report completion with failing tests. The loop will reject your delivery if delivery_validation shows exit_code != 0, and you will be given the failure_reason to fix; save everyone a round by self-verifying first. Current evidence gaps: {gaps}. Previous loop memory JSON: {_facade()._memory_context(memory)}. {score_remediation}{external_review_remediation}{external_merge_remediation}{retort_scope_remediation}{structured_report_remediation}\n\n=== HISTORICAL FIXES (MUST READ FIRST) ===\n{fix_digest}\n\n=== SELF_EVOLUTION_CONTEXT JSON ===\n{evolution_context}"""
