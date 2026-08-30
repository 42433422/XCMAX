# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _evaluate_retort_clarification_before_review(
    *,
    run_id: str,
    branch: _facade().Optional[str],
    para_task_id: str,
    memory: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    """Force self-maintenance review through Retort clarification gate.

    Returns ``{"blocked": True, "reason": ...}`` when human clarification is still
    required; otherwise ``{"blocked": False, ...}``. Failures in the gate itself
    are non-blocking so review can continue with evidence of the gate error.
    """
    enabled = _facade().os.environ.get(
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
    base_branch = _facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = _facade().os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    target = str(branch or "").strip()
    change_evidence = _facade().retort_change_evidence.resolve_retort_change_evidence(
        run_id=run_id,
        branch=target,
        repo_url=repo_url,
        base_branch=base_branch,
        memory=memory,
        workspace_root=_facade()._runtime_dir() / _facade().DEFAULT_MERGE_WORKSPACE_ROOT,
        changed_files_for_branch=lambda workspace: _facade()._changed_files_for_branch(
            repo_url=repo_url,
            base_branch=base_branch,
            branch=target,
            workspace=workspace,
        ),
        cleanup_workspace=_facade()._cleanup_merge_workspace,
    )
    changed_files = list(change_evidence.get("changed_files") or [])
    if change_evidence.get("skip_reason"):
        reason = str(change_evidence["skip_reason"])
        _facade().logger.warning(
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


def _review_task_text(
    run_id: str,
    branch: _facade().Optional[str],
    memory: _facade().Dict[str, _facade().Any],
) -> str:
    base_branch = _facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = _facade().os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    return f"""MODSTORE_REPORT_ONLY=1. Report-only review task. Do not change files, do not commit, and do not push. Review the self-maintenance loop run {run_id}. Target branch to inspect: `{branch or ""}`. Base branch: `{base_branch}`. Repo URL: `{repo_url}`. Do not inspect your own report-only task branch as the target branch. The report-only workspace bootstrap has already fetched `origin/<base>` and `origin/<target>`. Use those pre-fetched refs read-only. Do not run git fetch, clone, checkout, or any command that writes `.git`; the executor sandbox intentionally blocks it. Verify both refs with `git cat-file -e` and compare `origin/<base>...origin/<target>`. Only report target_branch_unavailable when a pre-fetched ref cannot be resolved. \n\n=== MANDATORY REVIEW DIMENSIONS (all three required) ===\n1) security — injection, secrets, unsafe deserialization, authz bypass, shell=True, etc.\n2) business_logic — wrong control flow, broken invariants, missing error handling, incorrect state transitions, API contract breakage, silent data loss, feature regressions.\n3) performance — obvious slow queries (SELECT * / missing LIMIT on hot paths), N+1 (ORM query inside loops), unbounded while/for loops, sync sleep on request path, unbounded list/buffer growth.\nFor each dimension set status to pass|fail|n/a and list concrete findings (empty list only when status is pass or n/a). Any dimension status=fail MUST also appear in blocking_findings and raise max_severity to at least medium (high/critical when warranted).\nReturn concrete findings, risks, and missing evidence. PROTOCOL STRICT: At the end, output exactly one JSON object after the marker {_facade().STRUCTURED_REVIEW_MARKER}: with schema {{"max_severity":"none|low|medium|high|critical","blocking_findings":[],"risk_class":"low|medium|high","target_branch_available":true,"tested_commands":[],"dimensions":{{"security":{{"status":"pass|fail|n/a","findings":[]}},"business_logic":{{"status":"pass|fail|n/a","findings":[]}},"performance":{{"status":"pass|fail|n/a","findings":[]}}}}}}. If you omit dimensions or use wrong enums, the loop will REJECT and re-run you. Previous loop memory JSON: {_facade()._memory_context(memory)}"""


def _qa_task_text(
    run_id: str,
    branch: _facade().Optional[str],
    memory: _facade().Dict[str, _facade().Any],
) -> str:
    base_branch = _facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = _facade().os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    focused_test_command = _facade()._focused_test_command()
    base_ref = f"origin/{base_branch or 'main'}"
    target_ref = f"origin/{str(branch or '').strip()}" if branch else "HEAD"
    black_command, isort_command = _facade()._diff_quality_commands(
        base_ref=base_ref, target_ref=target_ref
    )
    python_probe = (
        "for candidate in python3.13 python3.12 python3.11 python3 python; do "
        'command -v "$candidate" >/dev/null 2>&1 || continue; '
        '"$candidate" -c \'import sys, apscheduler, black, isort, pytest; '
        "raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1 || continue; "
        "printf '%s\\n' \"$candidate\"; break; done"
    )
    return f"""MODSTORE_REPORT_ONLY=1. Report-only QA task. Do not change files, do not commit, and do not push. Verify the executable evidence for self-maintenance loop run {run_id}. Target branch to verify: `{branch or ""}`. Base branch: `{base_branch}`. Repo URL: `{repo_url}`. Do not inspect your own report-only task branch as the target branch. The report-only workspace bootstrap has already fetched `origin/<base>` and `origin/<target>`. Use those pre-fetched refs read-only. Do not run git fetch, clone, checkout, or any command that writes `.git`; the executor sandbox intentionally blocks it. Verify both refs with `git cat-file -e` and compare `origin/<base>...origin/<target>`. Only report target_branch_unavailable when a pre-fetched ref cannot be resolved. Evaluate the target branch, tests, changed files, and previous loop memory as merge-readiness evidence. You MUST execute the focused verification command `{focused_test_command}` and include its exact command, real exit code, and status in tested_commands. If that command's absolute Python path does not exist on this worker, continue with this platform fallback. Materialize the COMPLETE target ref into a temporary directory (for example `git archive origin/<target> | tar -x`), then select a platform-equivalent local Python by running `{python_probe}` from that complete target tree. The probe must print exactly one Python >=3.11 executable that can import apscheduler, black, isort, and pytest; if it prints nothing, return FAIL. Use the printed interpreter to execute `-m pytest 成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py -q`, and include both the unavailable absolute-path attempt and the concrete successful equivalent command in tested_commands. The equivalent command is valid evidence only when it executes the same focused test file successfully; a syntax-only check or a different test target is not a substitute; do not archive only `成都修茈科技有限公司/MODstore_deploy`, because focused policy tests read the sibling `FHD/` autonomy-guard SSOT. Run pytest from that complete target tree. If the complete-tree equivalent command cannot finish, times out, or exits nonzero, return FAIL even when the failure looks environmental; never report PASS with no successful focused tested_commands entry. Do not fail solely because the scheduler's absolute Python path is unavailable when the complete-tree equivalent focused command passes. From the target branch archive, you MUST also run `{black_command}` and `{isort_command}` from `成都修茈科技有限公司/MODstore_deploy`; when their leading `python` is unavailable or is older than 3.11, replace only that token with the interpreter selected by the probe. These commands deterministically check every changed Python file in the target diff. Also use the selected Python >=3.11 interpreter to run `scripts/dev/source_governance.py --top 10` from the repository root; do not fall back to Python 3.9 or an unverified bare `python`. Record the exact concrete commands, real exit codes, and statuses in quality_checks. Use CLEAN_BASELINE_JSON to separate existing allowed failures from new failures; FAIL only for new failures, missing target branch, blocking findings, or unsafe evidence. Do not fail only because the final terminal ledger record for this in-flight run does not exist yet; that record is written after QA returns. Return PASS only when the target branch is executable and no new review/QA risk remains; return FAIL for real missing executable evidence, unsafe scope, new failed tests, or unresolved review findings. At the end, output exactly one JSON object after the marker {_facade().STRUCTURED_QA_MARKER}: with schema {{"verdict":"PASS|FAIL","blocking_findings":[],"tested_commands":[{{"command":"...","exit_code":0,"status":"passed|failed"}}],"quality_checks":{{"black":{{"command":"...","exit_code":0,"status":"passed|failed"}},"isort":{{"command":"...","exit_code":0,"status":"passed|failed"}},"source_governance":{{"command":"...","exit_code":0,"status":"passed|failed"}}}},"target_branch_available":true,"test_delta":{{"baseline_id":"...","new_failures":[],"new_errors":[]}},"changed_files_scope":"low|medium|high","risk_class":"low|medium|high"}}. CLEAN_BASELINE_JSON: {_facade()._clean_baseline_context()}. Previous loop memory JSON: {_facade()._memory_context(memory)}"""


def _json_after_marker(
    text: str, marker: str
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    report = text or ""
    positions: _facade().List[int] = []
    start = 0
    while True:
        idx = report.find(marker, start)
        if idx < 0:
            break
        positions.append(idx)
        start = idx + len(marker)
    for idx in reversed(positions):
        tail = report[idx + len(marker) :]
        tail = tail.lstrip(" \t\r\n:=`")
        if tail.startswith("json"):
            tail = tail[4:].lstrip(" \t\r\n")
        try:
            obj, _ = _facade().json.JSONDecoder().raw_decode(tail)
        except (TypeError, ValueError, _facade().json.JSONDecodeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None
