"""Retort and knowledge-schema holds with bounded remediation requests."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server import self_maintenance_retort_change_evidence as retort_change_evidence
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, store
from . import workspace as workspace_domain


def _evaluate_retort_clarification_before_review(
    *,
    run_id: str,
    branch: Optional[str],
    para_task_id: str,
    memory: Dict[str, Any],
) -> Dict[str, Any]:
    """Force self-maintenance review through Retort clarification gate.

    Returns ``{"blocked": True, "reason": ...}`` when human clarification is still
    required; otherwise ``{"blocked": False, ...}``. Failures in the gate itself
    are non-blocking so review can continue with evidence of the gate error.
    """
    enabled = os.environ.get(
        "MODSTORE_SELF_MAINTENANCE_RETORT_CLARIFICATION", "1"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"blocked": False, "reason": "disabled"}
    try:
        from modstore_server.retort_clarification_gate import (
            evaluate_retort_clarification_gate,
            gate_enabled,
        )
    except RECOVERABLE_ERRORS as exc:
        return {"blocked": False, "reason": f"gate_import_failed:{type(exc).__name__}"}
    if not gate_enabled():
        return {"blocked": False, "reason": "gate_disabled"}
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    target = str(branch or "").strip()
    change_evidence = retort_change_evidence.resolve_retort_change_evidence(
        run_id=run_id,
        branch=target,
        repo_url=repo_url,
        base_branch=base_branch,
        memory=memory,
        workspace_root=config._runtime_dir() / config.DEFAULT_MERGE_WORKSPACE_ROOT,
        changed_files_for_branch=lambda workspace: (
            workspace_domain._changed_files_for_branch(
                repo_url=repo_url,
                base_branch=base_branch,
                branch=target,
                workspace=workspace,
            )
        ),
        cleanup_workspace=workspace_domain._cleanup_merge_workspace,
    )
    changed_files = list(change_evidence.get("changed_files") or [])
    if change_evidence.get("skip_reason"):
        reason = str(change_evidence["skip_reason"])
        config.logger.warning(
            "retort clarification skipped run_id=%s reason=%s source=%s",
            run_id,
            reason,
            change_evidence.get("source"),
        )
        return {
            "blocked": False,
            "reason": reason,
            "changed_file_count": 0,
            "change_evidence": change_evidence,
            "para_task_id": para_task_id,
        }
    intent_bits = [
        f"self-maintenance review run {run_id}",
        f"branch {target}" if target else "",
        str((memory or {}).get("last_goal") or "").strip(),
        str((memory or {}).get("summary") or "").strip(),
    ]
    strategy_intent = " | ".join((bit for bit in intent_bits if bit))[:4000]
    try:
        gate = evaluate_retort_clarification_gate(
            strategy_intent=strategy_intent,
            changed_files=changed_files,
            proposal_id=f"self-maintenance:{run_id}",
            run_id=str(run_id or ""),
            package_id="change-request-auditor",
            auto_open=True,
        )
    except RECOVERABLE_ERRORS as exc:
        return {"blocked": False, "reason": f"gate_eval_failed:{type(exc).__name__}"}
    blockers = list(gate.get("blockers") or [])
    pending = "retort_clarification_pending" in blockers
    expired = "retort_clarification_expired" in blockers
    cancelled = "retort_clarification_cancelled" in blockers
    if pending or expired or cancelled:
        reason = (
            "retort_clarification_pending"
            if pending
            else "retort_clarification_expired" if expired else "retort_clarification_cancelled"
        )
        return {
            "blocked": True,
            "reason": reason,
            "blockers": blockers,
            "clarification": gate.get("clarification"),
            "change_evidence": change_evidence,
            "changed_file_count": len(changed_files),
            "para_task_id": para_task_id,
        }
    return {
        "blocked": False,
        "reason": "aligned_or_not_needed",
        "blockers": blockers,
        "clarification": gate.get("clarification"),
        "change_evidence": change_evidence,
        "changed_file_count": len(changed_files),
        "aligned": bool(gate.get("aligned")),
    }


def _early_kb_validation_for_branch(*, run_id: str, branch: str) -> Dict[str, Any]:
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
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    if not repo_url or not base_branch or (not branch):
        return {
            "ok": True,
            "reason": "early_kb_validation_skipped_missing_env",
            "kb_validation": None,
            "files": [],
            "workspace": "",
            "clone_error": None,
        }
    workspace = config._runtime_dir() / config.DEFAULT_MERGE_WORKSPACE_ROOT / f"{run_id}-kb-early"
    try:
        return _early_kb_validation_in_workspace(
            base_branch=base_branch,
            branch=branch,
            repo_url=repo_url,
            run_id=run_id,
            workspace=workspace,
        )
    finally:
        workspace_domain._cleanup_merge_workspace(workspace)


def _early_kb_validation_in_workspace(
    *,
    base_branch: str,
    branch: str,
    repo_url: str,
    run_id: str,
    workspace: Path,
) -> Dict[str, Any]:
    try:
        files = workspace_domain._changed_files_for_branch(
            repo_url=repo_url,
            base_branch=base_branch,
            branch=branch,
            workspace=workspace,
        )
    except RECOVERABLE_ERRORS as exc:
        config.logger.warning(
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
    kb_files = [f for f in files if workspace_domain._kb_json_kind_for_repo_path(f)]
    if not kb_files:
        return {
            "ok": True,
            "reason": "early_kb_validation_no_kb_json_changes",
            "kb_validation": None,
            "files": files,
            "workspace": str(workspace),
            "clone_error": None,
        }
    kb_validation = workspace_domain._validate_kb_json_changes_for_auto_merge(
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


def _find_pr_number_for_branch(branch: str) -> Optional[int]:
    """Find the open PR number for a branch via `gh pr list --head`.

    Returns None if gh is unavailable, not authenticated, or no open PR exists.
    Never raises — PR commenting/labeling is best-effort.
    """
    repo = os.environ.get("GITHUB_REPO", "").strip()
    cmd: List[str] = [
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except RECOVERABLE_ERRORS as exc:
        config.logger.warning("kb_schema_retry: gh pr list failed for branch=%s: %s", branch, exc)
        return None
    if proc.returncode != 0:
        config.logger.warning(
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
    repo = os.environ.get("GITHUB_REPO", "").strip()
    cmd: List[str] = ["gh", "pr", "comment", str(pr_number), "--body", body]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except RECOVERABLE_ERRORS as exc:
        config.logger.warning("kb_schema_retry: gh pr comment failed pr=%s: %s", pr_number, exc)
        return False
    if proc.returncode != 0:
        config.logger.warning(
            "kb_schema_retry: gh pr comment rc=%s pr=%s stderr=%s",
            proc.returncode,
            pr_number,
            (proc.stderr or "")[:200],
        )
        return False
    return True


def _gh_pr_add_label(pr_number: int, label: str) -> bool:
    """Best-effort PR label add via `gh pr edit --add-label`. Returns True on success."""
    repo = os.environ.get("GITHUB_REPO", "").strip()
    cmd: List[str] = [
        "gh",
        "pr",
        "edit",
        str(pr_number),
        "--add-label",
        label,
    ]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except RECOVERABLE_ERRORS as exc:
        config.logger.warning(
            "kb_schema_retry: gh pr edit --add-label %s failed pr=%s: %s",
            label,
            pr_number,
            exc,
        )
        return False
    if proc.returncode != 0:
        config.logger.warning(
            "kb_schema_retry: gh pr edit --add-label %s rc=%s pr=%s stderr=%s",
            label,
            proc.returncode,
            pr_number,
            (proc.stderr or "")[:200],
        )
        return False
    return True


def _existing_kb_schema_retry_item(
    open_items: List[Dict[str, Any]],
    *,
    branch: str,
    para_task_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Find the most recent non-escalated kb_schema_retry open_item.

    Matching priority (first match wins, scanning most-recent first):
      1. Exact branch match
      2. Exact para_task_id match
      3. Any non-escalated kb_schema_retry item within the last 24h
         (so retry_count escalates even if the employee pushes a new branch
         on each retry — common when the LLM doesn't reuse branches)
    """
    now = config._utc_now()
    fallback_within_24h: Optional[Dict[str, Any]] = None
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
        created_dt = config._parse_iso(item.get("created_at") or item.get("last_attempted_at"))
        if created_dt and (now - created_dt).total_seconds() <= 24 * 3600:
            if fallback_within_24h is None:
                fallback_within_24h = item
    return fallback_within_24h


def _reject_and_retry_kb_schema_failure(
    *,
    run_id: str,
    branch: str,
    para_task_id: Optional[str],
    kb_validation: Dict[str, Any],
    steps: List[Dict[str, Any]],
    gate: Dict[str, Any],
    triggered_by: str = "scheduled_self_maintenance",
    started_at: Optional[datetime] = None,
) -> Dict[str, Any]:
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
    memory = store._load_loop_memory()
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    existing = _existing_kb_schema_retry_item(open_items, branch=branch, para_task_id=para_task_id)
    if existing is not None:
        retry_count = int(existing.get("retry_count") or 0) + 1
    else:
        retry_count = 1
    escalated = retry_count >= config.KB_SCHEMA_RETRY_MAX
    pr_number = _find_pr_number_for_branch(branch)
    comment_body = f"""## KB JSON schema validation failed (attempt {retry_count}/{config.KB_SCHEMA_RETRY_MAX})\n\nThe KB JSON file(s) in this branch failed schema validation. Please fix the schema errors below and re-push.\n\n**Checked files:** {checked_str}\n\n**Errors:**\n{error_bullets}\n\n**Required schema for fix KB** (`FHD/XCAGI/kb/fixes/*.json`):\n```json\n{{\n  "schema_version": 1,\n  "kind": "fix",\n  "created_at": "<ISO-8601>",\n  "symptom": "<non-empty string>",\n  "root_cause": "<non-empty string>",\n  "fix_diff": "<non-empty string>",\n  "metadata": {{}},\n  "executable_template": {{\n    "applicability_check": "<non-empty string>",\n    "patch_strategy": "<non-empty string>",\n    "rollback_plan": "<non-empty string>",\n    "required_tests": ["test_a.py"]\n  }}\n}}\n```\n\nValidate before push:\n```\npython -c "from modstore_server.self_evolution_knowledge import validate_kb_payload; import json; validate_kb_payload('fixes', json.load(open('<file>')))"\n```\n"""
    if escalated:
        comment_body += f"\n\n**Escalated to human review** after {retry_count} retry attempts. Manual fix required. The `needs-human` label has been applied."
    if pr_number is not None:
        _gh_pr_comment(pr_number, comment_body)
        _gh_pr_add_label(pr_number, config.KB_SCHEMA_FAILED_LABEL)
        if escalated:
            _gh_pr_add_label(pr_number, config.NEEDS_HUMAN_LABEL)
    else:
        config.logger.warning(
            "kb_schema_retry: no open PR found for branch=%s; skipping PR comment/label",
            branch,
        )
    now = config._utc_now()
    if existing is not None:
        existing["retry_count"] = retry_count
        existing["last_attempted_at"] = config._iso(now)
        existing["kb_validation_errors"] = errors[:10]
        existing["run_id"] = run_id
        existing["escalated"] = escalated
        if para_task_id:
            existing["para_task_id"] = para_task_id
    else:
        new_item: Dict[str, Any] = {
            "branch": branch,
            "created_at": config._iso(now),
            "escalated": escalated,
            "kind": "kb_schema_retry",
            "kb_validation_errors": errors[:10],
            "last_attempted_at": config._iso(now),
            "para_task_id": para_task_id,
            "retry_count": retry_count,
            "run_id": run_id,
            "steps": ["code"],
        }
        open_items.append(new_item)
    memory["open_items"] = open_items
    memory["updated_at"] = config._iso(now)
    store._write_loop_memory(memory)
    audit_record = {
        "action": "kb_schema_retry",
        "actor": "auto",
        "branch": branch,
        "escalated": escalated,
        "created_at": config._iso(now),
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
        store._append_governance_audit(audit_record)
    except RECOVERABLE_ERRORS:
        config.logger.exception("kb_schema_retry: failed to write governance audit")
    final_status = (
        "completed_waiting_human_strategy" if escalated else config.KB_SCHEMA_FAILED_STATUS
    )
    policy_decision = {
        "action": "hold_for_automated_remediation",
        "active_gates": {
            "kb_schema_gate": {
                "ok": False,
                "blocking": True,
                "label": config.KB_SCHEMA_FAILED_LABEL,
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
        "completed_at": config._iso(now),
        "error": "kb_json_schema_validation_failed",
        "failed_step": "code",
        "failure_kind": config.KB_SCHEMA_FAILED_STATUS,
        "kb_schema_failed": True,
        "kb_schema_retry": True,
        "para_task_id": para_task_id,
        "phase": "complete",
        "policy_decision": policy_decision,
        "run_id": run_id,
        "started_at": config._iso(started_at) if started_at else config._iso(now),
        "status": final_status,
        "steps": steps,
        "triggered_by": triggered_by,
    }
    store._append_ledger(final)
    return final
