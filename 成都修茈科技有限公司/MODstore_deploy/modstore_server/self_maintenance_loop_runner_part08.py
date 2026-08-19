# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _early_kb_validation_for_branch(
    *, run_id: str, branch: str
) -> _facade().Dict[str, _facade().Any]:
    """Early KB JSON schema validation for a code-step branch.

    Clones the repo (best-effort), fetches the branch, gets the changed-files
    list, and runs ``_validate_kb_json_changes_for_auto_merge`` against any KB
    JSON files in the diff. Returns a dict with::

        {
          "ok": bool,                           # True if validation passed (or no KB files / clone failed)
          "reason": str,                        # "kb_json_schema_validation_failed" on failure
          "kb_validation": {...},               # raw _validate_kb_json_changes_for_auto_merge result
          "files": [...],                       # changed-files list (empty if clone failed)
          "workspace": str,                     # workspace path used (for cleanup/debug)
          "clone_error": str | None,            # set if clone/fetch failed (ok=True, non-blocking)
        }

    Design: clone failures are non-blocking (return ok=True with clone_error set)
    so the loop falls back to the existing auto_merge-stage validation. Only
    actual KB schema validation failures return ok=False.
    """
    repo_url = _facade().os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_branch = _facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    if not repo_url or not base_branch or (not branch):
        return {
            "ok": True,
            "reason": "early_kb_validation_skipped_missing_env",
            "kb_validation": None,
            "files": [],
            "workspace": "",
            "clone_error": None,
        }
    workspace = (
        _facade()._runtime_dir() / _facade().DEFAULT_MERGE_WORKSPACE_ROOT / f"{run_id}-kb-early"
    )
    try:
        return _facade()._early_kb_validation_in_workspace(
            base_branch=base_branch,
            branch=branch,
            repo_url=repo_url,
            run_id=run_id,
            workspace=workspace,
        )
    finally:
        _facade()._cleanup_merge_workspace(workspace)


def _early_kb_validation_in_workspace(
    *, base_branch: str, branch: str, repo_url: str, run_id: str, workspace: _facade().Path
) -> _facade().Dict[str, _facade().Any]:
    try:
        files = _facade()._changed_files_for_branch(
            repo_url=repo_url, base_branch=base_branch, branch=branch, workspace=workspace
        )
    except Exception as exc:
        _facade().logger.warning(
            "early_kb_validation: clone/fetch failed for branch=%s run_id=%s: %s",
            branch,
            run_id,
            exc,
        )
        return {
            "ok": True,
            "reason": "early_kb_validation_clone_failed",
            "kb_validation": None,
            "files": [],
            "workspace": str(workspace),
            "clone_error": str(exc)[:500],
        }
    if not files:
        return {
            "ok": True,
            "reason": "early_kb_validation_no_changed_files",
            "kb_validation": None,
            "files": [],
            "workspace": str(workspace),
            "clone_error": None,
        }
    kb_files = [f for f in files if _facade()._kb_json_kind_for_repo_path(f)]
    if not kb_files:
        return {
            "ok": True,
            "reason": "early_kb_validation_no_kb_json_changes",
            "kb_validation": None,
            "files": files,
            "workspace": str(workspace),
            "clone_error": None,
        }
    kb_validation = _facade()._validate_kb_json_changes_for_auto_merge(
        branch=branch, files=files, workspace=workspace
    )
    return {
        "ok": bool(kb_validation.get("ok")),
        "reason": str(kb_validation.get("reason") or ""),
        "kb_validation": kb_validation,
        "files": files,
        "workspace": str(workspace),
        "clone_error": None,
    }


def _find_pr_number_for_branch(branch: str) -> _facade().Optional[int]:
    """Find the open PR number for a branch via `gh pr list --head`.

    Returns None if gh is unavailable, not authenticated, or no open PR exists.
    Never raises — PR commenting/labeling is best-effort.
    """
    repo = _facade().os.environ.get("GITHUB_REPO", "").strip()
    cmd: _facade().List[str] = [
        "gh",
        "pr",
        "list",
        "--head",
        branch,
        "--state",
        "open",
        "--json",
        "number",
        "--jq",
        ".[0].number",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = _facade().subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except Exception as exc:
        _facade().logger.warning(
            "kb_schema_retry: gh pr list failed for branch=%s: %s", branch, exc
        )
        return None
    if proc.returncode != 0:
        _facade().logger.warning(
            "kb_schema_retry: gh pr list rc=%s for branch=%s stderr=%s",
            proc.returncode,
            branch,
            (proc.stderr or "")[:200],
        )
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _gh_pr_comment(pr_number: int, body: str) -> bool:
    """Best-effort PR comment via `gh pr comment`. Returns True on success."""
    repo = _facade().os.environ.get("GITHUB_REPO", "").strip()
    cmd: _facade().List[str] = ["gh", "pr", "comment", str(pr_number), "--body", body]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = _facade().subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except Exception as exc:
        _facade().logger.warning("kb_schema_retry: gh pr comment failed pr=%s: %s", pr_number, exc)
        return False
    if proc.returncode != 0:
        _facade().logger.warning(
            "kb_schema_retry: gh pr comment rc=%s pr=%s stderr=%s",
            proc.returncode,
            pr_number,
            (proc.stderr or "")[:200],
        )
        return False
    return True


def _gh_pr_add_label(pr_number: int, label: str) -> bool:
    """Best-effort PR label add via `gh pr edit --add-label`. Returns True on success."""
    repo = _facade().os.environ.get("GITHUB_REPO", "").strip()
    cmd: _facade().List[str] = ["gh", "pr", "edit", str(pr_number), "--add-label", label]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = _facade().subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except Exception as exc:
        _facade().logger.warning(
            "kb_schema_retry: gh pr edit --add-label %s failed pr=%s: %s", label, pr_number, exc
        )
        return False
    if proc.returncode != 0:
        _facade().logger.warning(
            "kb_schema_retry: gh pr edit --add-label %s rc=%s pr=%s stderr=%s",
            label,
            proc.returncode,
            pr_number,
            (proc.stderr or "")[:200],
        )
        return False
    return True


def _existing_kb_schema_retry_item(
    open_items: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    branch: str,
    para_task_id: _facade().Optional[str],
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """Find the most recent non-escalated kb_schema_retry open_item.

    Matching priority (first match wins, scanning most-recent first):
      1. Exact branch match
      2. Exact para_task_id match
      3. Any non-escalated kb_schema_retry item within the last 24h
         (so retry_count escalates even if the employee pushes a new branch
         on each retry — common when the LLM doesn't reuse branches)
    """
    now = _facade()._utc_now()
    fallback_within_24h: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    for item in reversed(open_items):
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "kb_schema_retry":
            continue
        if item.get("escalated"):
            continue
        item_branch = str(item.get("branch") or "").strip()
        item_task_id = str(item.get("para_task_id") or "").strip()
        if branch and item_branch == branch:
            return item
        if para_task_id and item_task_id == para_task_id:
            return item
        created_dt = _facade()._parse_iso(item.get("created_at") or item.get("last_attempted_at"))
        if created_dt and (now - created_dt).total_seconds() <= 24 * 3600:
            if fallback_within_24h is None:
                fallback_within_24h = item
    return fallback_within_24h


def _reject_and_retry_kb_schema_failure(
    *,
    run_id: str,
    branch: str,
    para_task_id: _facade().Optional[str],
    kb_validation: _facade().Dict[str, _facade().Any],
    steps: _facade().List[_facade().Dict[str, _facade().Any]],
    gate: _facade().Dict[str, _facade().Any],
    triggered_by: str = "scheduled_self_maintenance",
    started_at: _facade().Optional[_facade().datetime] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Reject KB-schema-invalid branch and retry code step (or escalate to human).

    Called immediately after code step completes when KB JSON schema validation fails.
    Actions (best-effort, never raises):
      1. Comment on the PR (find by branch via `gh pr list --head`)
      2. Add ``kb-schema-failed`` label to the PR
      3. Write/refresh a ``kb_schema_retry`` open_item in loop memory (retry_count++)
      4. If retry_count >= KB_SCHEMA_RETRY_MAX: add ``needs-human`` label, mark escalated
      5. Return a final state dict with policy_decision.action=hold_for_automated_remediation

    Next LOOP iteration sees the ``kb_schema_retry`` open_item and re-runs the code step
    (see ``_resume_review_qa_candidate``). After KB_SCHEMA_RETRY_MAX retries without
    resolution, the item is marked escalated so the loop stops retrying and waits for
    human review.
    """
    errors = kb_validation.get("errors") if isinstance(kb_validation, dict) else None
    if not isinstance(errors, list) or not errors:
        errors = [{"error": "unknown kb schema validation failure", "file": "", "kind": ""}]
    error_bullets = "\n".join(
        (
            f"- file: `{e.get('file') or '?'}` kind: `{e.get('kind') or '?'}` error: {(e.get('error') or '')[:300]}"
            for e in errors[:8]
        )
    )
    checked_files = kb_validation.get("checked") if isinstance(kb_validation, dict) else []
    checked_str = ", ".join((str(f) for f in checked_files)) if checked_files else "(none)"
    memory = _facade()._load_loop_memory()
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    existing = _facade()._existing_kb_schema_retry_item(
        open_items, branch=branch, para_task_id=para_task_id
    )
    if existing is not None:
        retry_count = int(existing.get("retry_count") or 0) + 1
    else:
        retry_count = 1
    escalated = retry_count >= _facade().KB_SCHEMA_RETRY_MAX
    pr_number = _facade()._find_pr_number_for_branch(branch)
    comment_body = f"""## KB JSON schema validation failed (attempt {retry_count}/{_facade().KB_SCHEMA_RETRY_MAX})\n\nThe KB JSON file(s) in this branch failed schema validation. Please fix the schema errors below and re-push.\n\n**Checked files:** {checked_str}\n\n**Errors:**\n{error_bullets}\n\n**Required schema for fix KB** (`FHD/XCAGI/kb/fixes/*.json`):\n```json\n{{\n  "schema_version": 1,\n  "kind": "fix",\n  "created_at": "<ISO-8601>",\n  "symptom": "<non-empty string>",\n  "root_cause": "<non-empty string>",\n  "fix_diff": "<non-empty string>",\n  "metadata": {{}},\n  "executable_template": {{\n    "applicability_check": "<non-empty string>",\n    "patch_strategy": "<non-empty string>",\n    "rollback_plan": "<non-empty string>",\n    "required_tests": ["test_a.py"]\n  }}\n}}\n```\n\nValidate before push:\n```\npython -c "from modstore_server.self_evolution_knowledge import validate_kb_payload; import json; validate_kb_payload('fixes', json.load(open('<file>')))"\n```\n"""
    if escalated:
        comment_body += f"\n\n**Escalated to human review** after {retry_count} retry attempts. Manual fix required. The `needs-human` label has been applied."
    if pr_number is not None:
        _facade()._gh_pr_comment(pr_number, comment_body)
        _facade()._gh_pr_add_label(pr_number, _facade().KB_SCHEMA_FAILED_LABEL)
        if escalated:
            _facade()._gh_pr_add_label(pr_number, _facade().NEEDS_HUMAN_LABEL)
    else:
        _facade().logger.warning(
            "kb_schema_retry: no open PR found for branch=%s; skipping PR comment/label", branch
        )
    now = _facade()._utc_now()
    if existing is not None:
        existing["retry_count"] = retry_count
        existing["last_attempted_at"] = _facade()._iso(now)
        existing["kb_validation_errors"] = errors[:10]
        existing["run_id"] = run_id
        existing["escalated"] = escalated
        if para_task_id:
            existing["para_task_id"] = para_task_id
    else:
        new_item: _facade().Dict[str, _facade().Any] = {
            "branch": branch,
            "created_at": _facade()._iso(now),
            "escalated": escalated,
            "kind": "kb_schema_retry",
            "kb_validation_errors": errors[:10],
            "last_attempted_at": _facade()._iso(now),
            "para_task_id": para_task_id,
            "retry_count": retry_count,
            "run_id": run_id,
            "steps": ["code"],
        }
        open_items.append(new_item)
    memory["open_items"] = open_items
    memory["updated_at"] = _facade()._iso(now)
    _facade()._write_loop_memory(memory)
    audit_record = {
        "action": "kb_schema_retry",
        "actor": "auto",
        "branch": branch,
        "escalated": escalated,
        "created_at": _facade()._iso(now),
        "kb_validation_errors": errors[:10],
        "ok": False,
        "pr_number": pr_number,
        "reason": "kb_json_schema_validation_failed",
        "retry_count": retry_count,
        "run_id": run_id,
        "source": "self_maintenance_loop_runner",
        "status": "escalated" if escalated else "retrying",
    }
    try:
        _facade()._append_governance_audit(audit_record)
    except Exception:
        _facade().logger.exception("kb_schema_retry: failed to write governance audit")
    final_status = (
        "completed_waiting_human_strategy" if escalated else _facade().KB_SCHEMA_FAILED_STATUS
    )
    policy_decision = {
        "action": "hold_for_automated_remediation",
        "active_gates": {
            "kb_schema_gate": {
                "ok": False,
                "blocking": True,
                "label": _facade().KB_SCHEMA_FAILED_LABEL,
                "reason": "kb_json_schema_validation_failed",
                "retry_count": retry_count,
                "escalated": escalated,
                "status": final_status,
            }
        },
        "governance_gate": audit_record,
        "kb_validation": kb_validation,
        "reason": "kb_json_schema_validation_failed",
        "retry_count": retry_count,
        "escalated": escalated,
        "status": final_status,
    }
    final = {
        "branch": branch,
        "completed_at": _facade()._iso(now),
        "error": "kb_json_schema_validation_failed",
        "failed_step": "code",
        "failure_kind": _facade().KB_SCHEMA_FAILED_STATUS,
        "kb_schema_failed": True,
        "kb_schema_retry": True,
        "para_task_id": para_task_id,
        "phase": "complete",
        "policy_decision": policy_decision,
        "run_id": run_id,
        "started_at": _facade()._iso(started_at) if started_at else _facade()._iso(now),
        "status": final_status,
        "steps": steps,
        "triggered_by": triggered_by,
    }
    _facade()._append_ledger(final)
    return final


def _normalize_repo_path(file_name: str) -> str:
    return _facade()._shared_normalize_repo_path(file_name)


def _diff_stats_changed_files_consistency(
    files: _facade().List[str], diff_stats: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(diff_stats, dict) or diff_stats.get("source") != "git_diff_numstat":
        return {"ok": True, "reason": "diff_stats_consistency_not_enforced_for_legacy_input"}
    expected = {_facade()._normalize_repo_path(file_name) for file_name in files if file_name}
    stats_changed = diff_stats.get("changed_files")
    if not isinstance(stats_changed, list):
        file_stats = diff_stats.get("files") if isinstance(diff_stats.get("files"), dict) else {}
        binary_files = (
            diff_stats.get("binary_files")
            if isinstance(diff_stats.get("binary_files"), list)
            else []
        )
        stats_changed = list(file_stats.keys()) + binary_files
    actual = {
        _facade()._normalize_repo_path(str(file_name))
        for file_name in stats_changed
        if str(file_name)
    }
    missing_from_numstat = sorted(expected - actual)
    extra_in_numstat = sorted(actual - expected)
    if missing_from_numstat or extra_in_numstat:
        return {
            "expected_name_only_files": sorted(expected),
            "extra_in_numstat": extra_in_numstat,
            "missing_from_numstat": missing_from_numstat,
            "numstat_files": sorted(actual),
            "ok": False,
            "reason": "changed_files_diff_stats_mismatch",
        }
    return {
        "checked_files": sorted(expected),
        "ok": True,
        "reason": "changed_files_diff_stats_match",
    }


def _file_matches_any_glob(file_name: str, globs: _facade().List[str]) -> bool:
    return _facade()._shared_file_matches_any_glob(file_name, globs)


def _files_match_allowed_globs(files: _facade().List[str], globs: _facade().List[str]) -> bool:
    if not files:
        return False
    for file_name in files:
        if not _facade()._file_matches_any_glob(file_name, globs):
            return False
    return True


def _auto_merge_max_risk_score() -> int:
    return max(
        0, min(_facade()._env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", 40), 100)
    )


def _auto_merge_min_safety_score_v2() -> int:
    return max(
        0,
        min(
            _facade()._env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V2", 90), 100
        ),
    )


def _historical_auto_merge_success_rate(
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]]
) -> _facade().Optional[float]:
    if not isinstance(memory, dict):
        return None
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        return None
    considered = 0
    successes = 0
    for run in recent_runs[-30:]:
        if not isinstance(run, dict):
            continue
        decision = run.get("policy_decision")
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "")
        reason = str(decision.get("reason") or "")
        if action == "auto_merged_low_risk" or "auto_merge" in reason or "low_risk" in reason:
            considered += 1
            status = str(run.get("status") or "")
            if action == "auto_merged_low_risk" or status == "completed_merged":
                successes += 1
    if considered <= 0:
        return None
    return successes / considered


def _historical_rollback_rate(
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]]
) -> _facade().Optional[float]:
    if not isinstance(memory, dict):
        return None
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        return None
    considered = 0
    rollbacks = 0
    for run in recent_runs[-50:]:
        if not isinstance(run, dict):
            continue
        decision = run.get("policy_decision")
        decision = decision if isinstance(decision, dict) else {}
        if (
            str(decision.get("action") or "") != "auto_merged_low_risk"
            and str(run.get("status") or "") != "completed_merged"
        ):
            continue
        considered += 1
        merge_result = decision.get("merge_result")
        merge_result = merge_result if isinstance(merge_result, dict) else {}
        rollback_records = [
            run.get("rollback"),
            decision.get("rollback"),
            merge_result.get("rollback"),
        ]
        explicit_statuses = {
            str(run.get("status") or "").lower(),
            str(run.get("rollback_status") or "").lower(),
            str(decision.get("action") or "").lower(),
            str(decision.get("outcome") or "").lower(),
            str(merge_result.get("outcome") or "").lower(),
        }
        rolled_back = bool(
            explicit_statuses
            & {
                "auto_rollback",
                "completed_rolled_back",
                "rollback_completed",
                "rollback_executed",
                "rolled_back",
            }
        )
        if not rolled_back:
            for record in rollback_records:
                if not isinstance(record, dict):
                    continue
                status = str(record.get("status") or record.get("outcome") or "").lower()
                if record.get("executed") is True or status in {
                    "completed",
                    "executed",
                    "rolled_back",
                    "success",
                }:
                    rolled_back = True
                    break
        if rolled_back:
            rollbacks += 1
    if considered <= 0:
        return None
    return rollbacks / considered


def _file_type_risk(file_name: str) -> int:
    lower = file_name.lower()
    if _facade()._kb_json_kind_for_repo_path(file_name):
        return 8
    if lower.endswith((".md", ".txt", ".json")):
        return 10
    if "/tests/" in lower or lower.startswith("tests/"):
        return 12
    if any((part in lower for part in ("/scripts/dev/", "self_maintenance", "self_evolution"))):
        return 18
    if any((part in lower for part in ("/api/", "routes", "scheduler", "workflow", "employee"))):
        return 32
    if any(
        (
            part in lower
            for part in (
                "models.py",
                "/models/",
                "migration",
                "alembic",
                "payment",
                "auth",
                "security",
            )
        )
    ):
        return 55
    if lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return 25
    return 20


def _auto_merge_risk_score_v1(
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Deterministic Phase-A risk score for 100% auto-merge decisions.

    The score is intentionally transparent: file type risk, changed lines,
    sensitive keywords and historical same-loop merge success rate.
    """
    normalized_files = [
        _facade()._normalize_repo_path(file_name) for file_name in files if file_name
    ]
    line_changes = int((diff_stats or {}).get("line_changes") or 0)
    per_file_scores = [
        {"file": file_name, "score": _facade()._file_type_risk(file_name)}
        for file_name in normalized_files
    ]
    file_score = max([int(item["score"]) for item in per_file_scores] or [0])
    line_score = min(25, line_changes // 20)
    keyword_terms = (
        "auth",
        "credential",
        "delete",
        "docker",
        "drop",
        "migration",
        "payment",
        "permission",
        "secret",
        "security",
        "token",
    )
    keyword_hits = sorted(
        {
            term
            for term in keyword_terms
            if any((term in file_name.lower() for file_name in normalized_files))
        }
    )
    keyword_score = min(25, len(keyword_hits) * 8)
    success_rate = _facade()._historical_auto_merge_success_rate(memory)
    history_score = 8 if success_rate is None else int(round((1.0 - success_rate) * 20))
    raw_score = file_score + line_score + keyword_score + history_score
    score = max(0, min(100, raw_score))
    if score <= 39:
        risk_class = "low"
    elif score <= 69:
        risk_class = "medium"
    else:
        risk_class = "high"
    return {
        "components": {
            "file_score": file_score,
            "history_score": history_score,
            "keyword_score": keyword_score,
            "line_score": line_score,
        },
        "file_scores": per_file_scores,
        "historical_auto_merge_success_rate": success_rate,
        "keyword_hits": keyword_hits,
        "line_changes": line_changes,
        "max_allowed": _facade()._auto_merge_max_risk_score(),
        "risk_class": risk_class,
        "schema_version": 1,
        "score": score,
    }


def _semantic_review_qa_analysis(
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]]
) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(steps, list):
        return {"available": False, "penalty": 8, "reason": "no_structured_llm_reports"}
    penalty = 0
    reports: _facade().Dict[str, _facade().Any] = {}
    review_steps = [
        step for step in steps if isinstance(step, dict) and step.get("step") == "review"
    ]
    qa_steps = [step for step in steps if isinstance(step, dict) and step.get("step") == "qa"]
    if review_steps:
        review_json = _facade()._structured_report_from_step(
            review_steps[-1], _facade().STRUCTURED_REVIEW_MARKER
        )
        if isinstance(review_json, dict):
            reports["review"] = review_json
            severity = str(review_json.get("max_severity") or "medium").lower()
            penalty += {"none": 0, "low": 2, "medium": 8, "high": 30, "critical": 50}.get(
                severity, 15
            )
            if review_json.get("blocking_findings"):
                penalty += 40
        else:
            penalty += 12
    else:
        penalty += 6
    if qa_steps:
        qa_json = _facade()._structured_report_from_step(
            qa_steps[-1], _facade().STRUCTURED_QA_MARKER
        )
        if isinstance(qa_json, dict):
            reports["qa"] = qa_json
            verdict = str(qa_json.get("verdict") or "").upper()
            penalty += 0 if verdict == "PASS" else 50
            risk_class = str(qa_json.get("risk_class") or "medium").lower()
            penalty += {"low": 0, "medium": 8, "high": 30}.get(risk_class, 12)
            if qa_json.get("blocking_findings"):
                penalty += 40
        else:
            penalty += 12
    else:
        penalty += 6
    return {
        "available": bool(reports),
        "penalty": min(80, penalty),
        "reports": reports,
        "source": "structured_review_qa_llm_reports",
    }
