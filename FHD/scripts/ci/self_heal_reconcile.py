"""Incident recovery glue over GitHub runs and Para's existing trusted resume receipt.

No executor or task store lives here. Unknown POST results stay unresolved; only
an exact run can be rerun, or a receipted control task can be resumed.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any

import self_heal_freshness as freshness

from scripts.dev import para_issue_dispatch as para

DISPATCH_MARKER = "<!-- self-heal-dispatch:v1 "
IMPLEMENT_PATH = ".github/workflows/fhd-ai-issue-implement.yml"
MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_VISIBILITY_SECONDS = 10 * 60


def trusted(item: dict[str, Any]) -> bool:
    user = item.get("user") or {}
    return user.get("login") == "github-actions[bot]" and user.get("type") == "Bot"


def receipt_body(receipt: dict[str, Any]) -> str:
    return (
        DISPATCH_MARKER
        + json.dumps(receipt, sort_keys=True)
        + " -->\n"
        + ("派发状态记录，不代表修复完成；未知结果须核验原 run，不能重新创建控制任务。")
    )


def _identities(body: str, marker: str):
    for raw in re.findall(re.escape(marker) + r"(\{[^\n]+\}) -->", body):
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            yield value


def recovery_plan(
    issue: dict[str, Any], comments: list[dict[str, Any]], repo: str, branch: str
) -> dict:
    """Validate Para identity with its own guard, and bind the observer's exact run."""
    number = int(issue["number"])
    identity = {"repo": repo, "issue_number": number, "base_branch": branch}
    plan: dict[str, Any] = {"state": "unresolved", "reason": "dispatch_receipt_missing"}
    dispatch_count = 0
    pending_reruns: dict[int, int] = {}
    pending_since: dict[int, float] = {}
    for comment in comments:
        if not trusted(comment):
            continue
        body = str(comment.get("body") or "")
        for record in _identities(body, DISPATCH_MARKER):
            if any(record.get(k) != v for k, v in identity.items()):
                continue
            dispatch_count += 1
            if record.get("operation") == "rerun":
                run_id = int(record.get("dispatch_run_id") or 0)
                pending_reruns[run_id] = (
                    0 if record.get("status") == "rejected" else int(record.get("run_attempt") or 0)
                )
                pending_since[run_id] = float(record.get("requested_at") or 0)
            plan = {
                "state": "unresolved",
                "reason": f"dispatch_{record.get('status', 'unknown')}",
                "control_task_id": str(record.get("control_task_id") or ""),
                "dispatch_run_id": int(record.get("dispatch_run_id") or 0),
            }
        for record in _identities(body, para.RECEIPT_MARKER):
            if any(record.get(k) != v for k, v in identity.items()):
                continue
            task_id = str(record.get("control_task_id") or "")
            if task_id:
                para._validated_resume(
                    argparse.Namespace(
                        repo=repo,
                        issue_number=number,
                        base_branch=branch,
                        control_task_id=task_id,
                    ),
                    [comment],
                )
            status = re.search(r"处理结果：`([^`]+)`", body)
            status_value = status.group(1) if status else "observing"
            run = re.search(
                re.escape(f"https://github.com/{repo}/actions/runs/") + r"(\d+)\b", body
            )
            plan = {
                "state": "unresolved",
                "reason": status_value,
                "control_task_id": task_id,
                "dispatch_run_id": int(run.group(1)) if run else 0,
            }
    plan["dispatch_count"] = dispatch_count
    plan["rerun_from_attempt"] = pending_reruns.get(int(plan.get("dispatch_run_id") or 0), 0)
    plan["rerun_requested_at"] = pending_since.get(int(plan.get("dispatch_run_id") or 0), 0)
    # A self-heal receipt alone never grants Para resume authority.
    if plan.get("control_task_id"):
        para._validated_resume(
            argparse.Namespace(
                repo=repo,
                issue_number=number,
                base_branch=branch,
                control_task_id=plan["control_task_id"],
            ),
            comments,
        )
    return plan


def reconcile_one(issue: dict[str, Any], *, repo: str, get, write, dispatch, dry_run: bool) -> dict:
    """Reconcile one owned incident; APIs failing or lacking evidence cannot close it."""
    number = int(issue.get("number") or 0)
    result: dict[str, Any] = {
        "issue_number": number,
        "state": "unresolved",
        "reason": "untrusted_incident",
    }
    labels = {str(v.get("name")) for v in issue.get("labels", []) if isinstance(v, dict)}
    if (
        not number
        or not trusted(issue)
        or "auto-incident" not in labels
        or issue.get("pull_request")
    ):
        return result
    if issue.get("state") == "closed":
        return {**result, "state": "already_closed", "reason": "issue_closed"}
    if issue.get("state") != "open":
        return {**result, "reason": "incident_state_missing"}
    source = freshness.reconcile_source(issue, repo, get)
    result.update(
        reason=source.reason,
        source_run_id=source.run_id,
        workflow_path=source.workflow_path,
    )
    if source.action == freshness.BLOCK:
        return result
    if source.action == freshness.SKIP:
        result["state"] = source.disposition
        if dry_run:
            return result
        fresh = freshness.reconcile_source(issue, repo, get)
        if fresh.action != freshness.SKIP or fresh.disposition != source.disposition:
            return {
                **result,
                "state": "unresolved",
                "reason": "source_changed_before_close",
            }
        body = (
            f"<!-- self-heal-reconcile:v1 {json.dumps(result, sort_keys=True)} -->\n"
            f"原 CI 事件 `{source.run_id}/{source.run_attempt}` 对账：`{source.disposition}`。"
            f"依据：`{source.reason}`；source `{source.source_sha}`，current `{source.current_sha}`。"
            "\n替代表示旧来源不再需要派单，不表示修复或发布验收通过。"
        )
        status, _ = write("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})
        if status != 201:
            return {**result, "state": "unresolved", "reason": "closure_receipt_failed"}
        status, _ = write(
            "PATCH",
            f"/repos/{repo}/issues/{number}",
            {
                "state": "closed",
                "state_reason": (
                    "completed" if source.disposition == "recovered" else "not_planned"
                ),
            },
        )
        return (
            result
            if status == 200
            else {**result, "state": "unresolved", "reason": "closure_failed"}
        )
    if "ai-implement" not in labels or source.head_repo.casefold() != repo.casefold():
        return {**result, "reason": "implementation_not_authorized_for_source"}
    comments = list(freshness.pages(get, f"/repos/{repo}/issues/{number}/comments"))
    plan = recovery_plan(issue, comments, repo, source.head_branch)
    result.update(plan)
    if plan["reason"] in {
        "rejected_too_large",
        "waiting_confirmation",
        "invalid_resume",
        "no_label",
        "para_failed",
        "head_mismatch",
        "verification_failed",
        "no_branch",
        "pr_created",
    }:
        return result
    if plan["dispatch_count"] >= MAX_RECOVERY_ATTEMPTS:
        return {**result, "reason": "recovery_attempt_budget_exhausted"}
    run_id = int(plan.get("dispatch_run_id") or 0)
    if not run_id:
        # A definitive rejection may be retried; timeout/204/pending never proves absence.
        if plan["reason"] != "dispatch_rejected":
            return result
        action = "retry_rejected_dispatch"
    else:
        run = freshness._get(get, f"/repos/{repo}/actions/runs/{run_id}")
        if (
            run.get("id") != run_id
            or freshness.workflow_identity(run)[1] != IMPLEMENT_PATH
            or run.get("event") not in {"workflow_dispatch", "issues", "issue_comment"}
            or run.get("head_branch") != "main"
        ):
            return {**result, "reason": "implementation_run_identity_mismatch"}
        if not run.get("run_attempt") or not run.get("status"):
            return {**result, "reason": "implementation_run_state_missing"}
        if int(run["run_attempt"]) <= plan["rerun_from_attempt"]:
            if time.time() - plan["rerun_requested_at"] >= RECOVERY_VISIBILITY_SECONDS:
                return {
                    **result,
                    "state": "unresolved",
                    "reason": "rerun_result_unconfirmed",
                }
            return {
                **result,
                "state": "observing",
                "reason": "rerun_pending_observation",
            }
        if run.get("status") != "completed":
            return {
                **result,
                "state": "observing",
                "reason": "implementation_run_active",
            }
        if plan.get("control_task_id"):
            action = "resume_control_task"
        elif run.get("conclusion") in {"failure", "timed_out", "cancelled"}:
            if not 0 < int(run.get("run_attempt") or 0) < MAX_RECOVERY_ATTEMPTS:
                return {**result, "reason": "run_attempt_budget_exhausted"}
            action = "rerun_original_run"
        else:
            return {**result, "reason": "completed_run_without_task_receipt"}
    result.update(state="resumable", reason=action)
    if dry_run:
        return result
    if freshness.reconcile_source(issue, repo, get).action != freshness.PROCEED:
        return {
            **result,
            "state": "unresolved",
            "reason": "source_changed_before_resume",
        }
    if action == "rerun_original_run":
        # A lost rerun response must not cause repeated POSTs before the API's
        # attempt advances. The original run id also preserves Para request_key.
        receipt = {
            "repo": repo,
            "issue_number": number,
            "base_branch": source.head_branch,
            "control_task_id": "",
            "dispatch_run_id": run_id,
            "operation": "rerun",
            "status": "pending",
            "run_attempt": int(run["run_attempt"]),
            "requested_at": time.time(),
        }
        status, intent = write(
            "POST",
            f"/repos/{repo}/issues/{number}/comments",
            {"body": receipt_body(receipt)},
        )
        if status != 201 or not isinstance(intent, dict) or not intent.get("id"):
            return {**result, "state": "unresolved", "reason": "rerun_intent_failed"}
        status, _ = write("POST", f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs", {})
        ok = status == 201
        if status in {400, 401, 403, 404, 422}:
            receipt["status"] = "rejected"
            saved, _ = write(
                "PATCH",
                f"/repos/{repo}/issues/comments/{int(intent['id'])}",
                {"body": receipt_body(receipt)},
            )
            if saved != 200:
                return {
                    **result,
                    "state": "unresolved",
                    "reason": "rerun_rejection_receipt_failed",
                }
    else:
        ok = dispatch(
            f"https://github.com/{repo}/issues/{number}",
            target_branch=source.head_branch,
            control_task_id=plan.get("control_task_id", ""),
        )
    return {
        **result,
        "state": "resumed" if ok else "unresolved",
        "reason": action if ok else "resume_result_unconfirmed",
    }
