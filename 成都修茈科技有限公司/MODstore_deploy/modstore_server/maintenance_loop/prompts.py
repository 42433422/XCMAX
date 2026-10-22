"""Create code/review/QA tasks from explicit branch and memory evidence."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from modstore_server import (
    self_evolution_knowledge,
    self_maintenance_quality_gate,
    self_maintenance_remediation_prompts,
)
from modstore_server import self_maintenance_retort_remediation as retort_remediation

from . import config
from . import memory as memory_domain
from . import review as review_domain
from . import store


def _code_task_text(
    run_id: str,
    evaluation: Dict[str, Any],
    memory: Dict[str, Any],
    resume_candidate: Optional[Dict[str, Any]] = None,
) -> str:
    gaps = ", ".join(evaluation.get("gaps") or []) or "none"
    focused_test_command = review_domain._focused_test_command()
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip() or "main"
    black_command, isort_command = self_maintenance_quality_gate.diff_quality_commands(
        base_ref=f"origin/{base_branch}", target_ref="WORKTREE"
    )
    evolution_context_dict = self_evolution_knowledge.build_self_evolution_context(
        run_id=run_id, evaluation=evaluation, memory=memory
    )
    evolution_context = self_evolution_knowledge.render_self_evolution_context(
        evolution_context_dict
    )
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
    selected_remediation: Optional[Dict[str, Any]] = None
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
    external_review_remediation = (
        self_maintenance_remediation_prompts.external_review_remediation_prompt(resume_candidate)
    )
    external_merge_remediation = (
        self_maintenance_remediation_prompts.external_merge_remediation_prompt(resume_candidate)
    )
    retort_scope_remediation = retort_remediation.retort_scope_remediation_prompt(resume_candidate)
    structured_report_remediation = (
        self_maintenance_remediation_prompts.structured_report_remediation_prompt(
            memory, resume_candidate
        )
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
        score_remediation = f"\n\n=== EXISTING BRANCH SCORE REMEDIATION ===\nYour workspace is already checked out on a newly created isolated remediation work branch whose immutable base is `{str(selected_remediation.get('branch') or '').strip()}`. Do not checkout, switch to, reset, commit, or push directly to that immutable base branch. Make the follow-up on the current checked-out work branch only; do not replace its production fix with an unrelated change. The previous independent review/score did not authorize merge. Address its missing evidence on this candidate, especially any promised focused regression test that is absent. A test-only follow-up commit is valid here because the existing candidate already contains the production fix. Run that focused test and the mandatory loop policy suite, then commit the current work branch and push HEAD to that same work-branch name. Report `git branch --show-current` and `git rev-parse HEAD` as delivery evidence. Do not lower, bypass, or game either safety threshold. Evidence: {json.dumps(remediation_evidence, ensure_ascii=False, sort_keys=True)}"
    return f"""Run a real MODstore self-maintenance improvement task. === SELF_MAINTENANCE_CANONICAL_MERGE_BASE:main === Use the previous loop memory and current evidence gaps to fix the highest-value executable gap in the self-maintenance loop. MANDATORY: Before reasoning from scratch, you MUST check the HISTORICAL FIXES below. If a historical fix's symptom matches the current gap and its fix_diff still applies safely, you MUST reuse that fix first (apply the diff or its approach) instead of inventing a new solution. Only when no historical fix applies may you reason from scratch. If there is no bug gap, choose one proactive task from performance, coverage, or tech_debt signals. When you fix a bug, write the symptom/root_cause/fix_diff triad under FHD/XCAGI/kb/fixes; every changed fix JSON MUST conform to the EXACT schema below (all fields required, no extras that break validation):\n```json\n{{\n  "schema_version": 1,\n  "kind": "fix",\n  "created_at": "2026-07-20T12:00:00+00:00",\n  "symptom": "<non-empty string: observed symptom>",\n  "root_cause": "<non-empty string: root cause>",\n  "fix_diff": "<non-empty string: diff or description>",\n  "metadata": {{"component": "...", "files": ["..."]}},\n  "executable_template": {{\n    "applicability_check": "<non-empty string>",\n    "patch_strategy": "<non-empty string>",\n    "rollback_plan": "<non-empty string>",\n    "required_tests": ["test_a.py", "test_b.py"]\n  }}\n}}\n```\nCRITICAL: executable_template MUST be an object (the executable_template object must not be a string, null, or omitted) with non-empty string fields applicability_check/patch_strategy/rollback_plan AND a string-list required_tests. Common failure: writing fix_diff as a description but forgetting executable_template, or setting executable_template to a string. MANDATORY PRE-PUSH VALIDATION: Before committing/pushing any KB JSON file, you MUST run `python -c "from modstore_server.self_evolution_knowledge import validate_kb_payload; import json; validate_kb_payload('fixes', json.load(open('FHD/XCAGI/kb/fixes/<file>.json')))"` (or 'patterns' for pattern files) and require it to return without raising. If validation raises ValueError, FIX the JSON before pushing — the loop will reject KB-schema-invalid branches with a `kb-schema-failed` PR label and retry up to 2 times before escalating to human review. Validate each changed KB JSON with self_evolution_knowledge.validate_kb_payload before reporting completion. when review/QA approves a reusable change, write the pattern under FHD/XCAGI/kb/patterns. Do not create marker-only/status-only changes as proof of completion. Prefer changes that make scheduler gating, loop memory, report-only review/QA, or policy decisions more directly executable. \n\n=== OUTPUT QUALITY REQUIREMENTS ===\n- State one evidence-backed symptom and root cause before changing code.\n- Make the smallest production change that fixes that root cause and add focused regression tests; do not submit marker-only, comment-only, formatting-only, or test-only work as the fix.\n- DIFF PROTOCOL: When describing patches in the report or KB fix_diff, emit a complete unified diff that `git apply` / `git apply --check` can consume (must include `diff --git`, `---/+++`, and `@@` hunks). Forbidden: summary-only answers, bullet paraphrases of changes, or partial hunks without file headers.\n- Prefer committing real file edits in the worktree (git add/commit/push) over pasting diffs; if you paste a patch, it must still be git-applyable.\n- Keep production scope and changed lines minimal enough for a legitimate safety_score_v2 target of at least 90; never hide, omit, or misclassify risky files or behavior to influence the score.\n- Leave review and QA to the independent report-only employees; do not self-approve or fabricate their evidence.\n- Report every verification command with its real exit code and concise passing output.\nBefore reporting completion, execute `{focused_test_command}` in the target branch and require exit code 0. Also run `{black_command}` and `{isort_command}` from `成都修茈科技有限公司/MODstore_deploy`; these commands deterministically check every changed Python file in the target diff without importing unrelated historical formatting debt. Also run `python scripts/dev/source_governance.py --top 10` from the repository root; all three are mandatory merge-readiness gates and must exit 0. If and only if there is no safe actionable source change, update `{config.DEFAULT_STATUS_FILE}` with LOOP_RUN_ID={run_id!r}, LOOP_KIND='scheduled_self_maintenance', BRIDGE='para_main_device', UPDATED_AT to the current UTC time, and a clear NO_ACTION_REASON explaining why no source change was safe. Do not edit runtime-only, ignored, .devfleet, or .trae files. MANDATORY SELF-VERIFICATION: Before reporting completion, you MUST run the relevant tests/lint/type-check commands for the files you changed and paste the passing output (exit code 0) in your report. If any command fails, fix your changes and retry — do NOT report completion with failing tests. The loop will reject your delivery if delivery_validation shows exit_code != 0, and you will be given the failure_reason to fix; save everyone a round by self-verifying first. Current evidence gaps: {gaps}. Previous loop memory JSON: {memory_domain._memory_context(memory)}. {score_remediation}{external_review_remediation}{external_merge_remediation}{retort_scope_remediation}{structured_report_remediation}\n\n=== HISTORICAL FIXES (MUST READ FIRST) ===\n{fix_digest}\n\n=== SELF_EVOLUTION_CONTEXT JSON ===\n{evolution_context}"""


def _review_task_text(
    run_id: str,
    branch: Optional[str],
    memory: Dict[str, Any],
) -> str:
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    return f"""MODSTORE_REPORT_ONLY=1. Report-only review task. Do not change files, do not commit, and do not push. Review the self-maintenance loop run {run_id}. Target branch to inspect: `{branch or ""}`. Base branch: `{base_branch}`. Repo URL: `{repo_url}`. Do not inspect your own report-only task branch as the target branch. The report-only workspace bootstrap has already fetched `origin/<base>` and `origin/<target>`. Use those pre-fetched refs read-only. Do not run git fetch, clone, checkout, or any command that writes `.git`; the executor sandbox intentionally blocks it. Verify both refs with `git cat-file -e` and compare `origin/<base>...origin/<target>`. Only report target_branch_unavailable when a pre-fetched ref cannot be resolved. \n\n=== MANDATORY REVIEW DIMENSIONS (all three required) ===\n1) security — injection, secrets, unsafe deserialization, authz bypass, shell=True, etc.\n2) business_logic — wrong control flow, broken invariants, missing error handling, incorrect state transitions, API contract breakage, silent data loss, feature regressions.\n3) performance — obvious slow queries (SELECT * / missing LIMIT on hot paths), N+1 (ORM query inside loops), unbounded while/for loops, sync sleep on request path, unbounded list/buffer growth.\nFor each dimension set status to pass|fail|n/a and list concrete findings (empty list only when status is pass or n/a). Any dimension status=fail MUST also appear in blocking_findings and raise max_severity to at least medium (high/critical when warranted).\nReturn concrete findings, risks, and missing evidence. PROTOCOL STRICT: At the end, output exactly one JSON object after the marker {config.STRUCTURED_REVIEW_MARKER}: with schema {{"max_severity":"none|low|medium|high|critical","blocking_findings":[],"risk_class":"low|medium|high","target_branch_available":true,"tested_commands":[],"dimensions":{{"security":{{"status":"pass|fail|n/a","findings":[]}},"business_logic":{{"status":"pass|fail|n/a","findings":[]}},"performance":{{"status":"pass|fail|n/a","findings":[]}}}}}}. If you omit dimensions or use wrong enums, the loop will REJECT and re-run you. Previous loop memory JSON: {memory_domain._memory_context(memory)}"""


def _qa_task_text(
    run_id: str,
    branch: Optional[str],
    memory: Dict[str, Any],
) -> str:
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    focused_test_command = review_domain._focused_test_command()
    base_ref = f"origin/{base_branch or 'main'}"
    target_ref = f"origin/{str(branch or '').strip()}" if branch else "HEAD"
    black_command, isort_command = self_maintenance_quality_gate.diff_quality_commands(
        base_ref=base_ref, target_ref=target_ref
    )
    return f"""MODSTORE_REPORT_ONLY=1. Report-only QA task. Do not change files, do not commit, and do not push. Verify the executable evidence for self-maintenance loop run {run_id}. Target branch to verify: `{branch or ""}`. Base branch: `{base_branch}`. Repo URL: `{repo_url}`. Do not inspect your own report-only task branch as the target branch. The report-only workspace bootstrap has already fetched `origin/<base>` and `origin/<target>`. Use those pre-fetched refs read-only. Do not run git fetch, clone, checkout, or any command that writes `.git`; the executor sandbox intentionally blocks it. Verify both refs with `git cat-file -e` and compare `origin/<base>...origin/<target>`. Only report target_branch_unavailable when a pre-fetched ref cannot be resolved. Evaluate the target branch, tests, changed files, and previous loop memory as merge-readiness evidence. You MUST execute the focused verification command `{focused_test_command}` and include its exact command, real exit code, and status in tested_commands. If that command's absolute Python path does not exist on this worker, also run a platform-equivalent local `python -m pytest` command against the same focused test file, and include both attempts in tested_commands. The equivalent command is valid evidence only when it executes the same pytest target successfully; a syntax-only check or a different test target is not a substitute. Materialize the COMPLETE target ref into a temporary directory (for example `git archive origin/<target> | tar -x`) before running the equivalent command; do not archive only `成都修茈科技有限公司/MODstore_deploy`, because focused policy tests read the sibling `FHD/` autonomy-guard SSOT. Run pytest from that complete target tree. If the complete-tree equivalent command cannot finish, times out, or exits nonzero, return FAIL even when the failure looks environmental; never report PASS with no successful focused tested_commands entry. Do not fail solely because the scheduler's absolute Python path is unavailable when the complete-tree equivalent focused command passes. From the target branch archive, you MUST also run `{black_command}` and `{isort_command}` from `成都修茈科技有限公司/MODstore_deploy`; these commands deterministically check every changed Python file in the target diff. Also run `python scripts/dev/source_governance.py --top 10` from the repository root. Record their exact commands, real exit codes, and statuses in quality_checks. Use CLEAN_BASELINE_JSON to separate existing allowed failures from new failures; FAIL only for new failures, missing target branch, blocking findings, or unsafe evidence. Do not fail only because the final terminal ledger record for this in-flight run does not exist yet; that record is written after QA returns. Return PASS only when the target branch is executable and no new review/QA risk remains; return FAIL for real missing executable evidence, unsafe scope, new failed tests, or unresolved review findings. At the end, output exactly one JSON object after the marker {config.STRUCTURED_QA_MARKER}: with schema {{"verdict":"PASS|FAIL","blocking_findings":[],"tested_commands":[{{"command":"...","exit_code":0,"status":"passed|failed"}}],"quality_checks":{{"black":{{"command":"...","exit_code":0,"status":"passed|failed"}},"isort":{{"command":"...","exit_code":0,"status":"passed|failed"}},"source_governance":{{"command":"...","exit_code":0,"status":"passed|failed"}}}},"target_branch_available":true,"test_delta":{{"baseline_id":"...","new_failures":[],"new_errors":[]}},"changed_files_scope":"low|medium|high","risk_class":"low|medium|high"}}. CLEAN_BASELINE_JSON: {store._clean_baseline_context()}. Previous loop memory JSON: {memory_domain._memory_context(memory)}"""
