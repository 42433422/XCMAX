"""Incident recovery glue over GitHub runs and Para's existing trusted resume receipt.

No executor or task store lives here. Unknown POST results stay unresolved; only
an exact run can be rerun, or a receipted control task can be resumed.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from datetime import UTC, datetime
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
                "dispatch_comment_id": comment.get("id"),
                "dispatch_receipt": record,
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
                r"^- 工作流："
                + re.escape(f"https://github.com/{repo}/actions/runs/")
                + r"(\d+)\s*$",
                body,
                re.M,
            )
            workers = re.findall(
                r"^- Para 云端："
                + re.escape(f"https://github.com/{repo}/actions/runs/")
                + r"(\d+)\s*$",
                body,
                re.M,
            )
            plan = {
                "state": "unresolved",
                "reason": status_value,
                "control_task_id": task_id,
                "dispatch_run_id": int(run.group(1)) if run else 0,
                "para_receipt": record,
                "github_worker_run_id": int(workers[0]) if len(workers) == 1 else 0,
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


def _dispatch_run_matches(run, repo, number, request_id):
    return (
        type(run.get("id")) is int
        and run["id"] > 0
        and run.get("display_title") == f"AI Issue Implement #{number} [dispatch:{request_id}]"
        and run.get("path") == IMPLEMENT_PATH
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main"
        and (run.get("repository") or {}).get("full_name", "").casefold() == repo.casefold()
        and bool(re.fullmatch(r"[0-9a-f]{40}", str(run.get("head_sha") or "")))
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] > 0
    )


def recover_dispatch(plan, *, repo, number, get, write, dry_run):
    """Adopt only the uniquely identified original run; never repeat its POST."""
    receipt = plan.get("dispatch_receipt") or {}
    request_id = receipt.get("dispatch_request_id", "")
    if not request_id:
        return plan
    try:
        if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
            raise ValueError("invalid dispatch identity")
        since = datetime.fromtimestamp(int(receipt["requested_at"]), UTC).isoformat()
        if type(plan.get("dispatch_comment_id")) is not int or plan["dispatch_comment_id"] < 1:
            raise ValueError("original comment missing")
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**plan, "reason": "dispatch_identity_invalid"}
    runs = list(
        freshness.pages(
            get,
            f"/repos/{repo}/actions/workflows/fhd-ai-issue-implement.yml/runs",
            {"event": "workflow_dispatch", "branch": "main", "created": ">=" + since},
            key="workflow_runs",
        )
    )
    matches = [
        run
        for run in runs
        if run.get("display_title") == f"AI Issue Implement #{number} [dispatch:{request_id}]"
    ]
    if not matches:
        return {**plan, "reason": "dispatch_run_not_yet_visible"}
    if len(matches) != 1:
        return {**plan, "reason": "dispatch_run_identity_ambiguous"}
    run = matches[0]
    if not _dispatch_run_matches(run, repo, number, request_id):
        return {**plan, "reason": "dispatch_run_identity_mismatch"}
    # Save the observation before the normal next reconciliation can resume it.
    # A lost PATCH acknowledgement is harmless: the original run is only read.
    if not dry_run:
        status, _ = write(
            "PATCH",
            f"/repos/{repo}/issues/comments/{plan['dispatch_comment_id']}",
            {"body": receipt_body({**receipt, "dispatch_run_id": run["id"], "status": "observed"})},
        )
        if status != 200:
            return {**plan, "reason": "dispatch_observation_not_persisted"}
    return {
        **plan,
        "state": "observing",
        "reason": "dispatch_run_recovered",
        "dispatch_run_id": run["id"],
    }


def _original_worker_resume_matches(run, plan, source, repo, get):
    """A trusted producer receipt binds the source and task; the title only locates its worker."""
    control = plan.get("control_task_id", "")
    receipt = plan.get("para_receipt") or {}
    worker_id = plan.get("github_worker_run_id")
    if (
        source.workflow_path not in freshness.CODE_CI_PATHS
        or source.head_branch == "main"
        or not re.fullmatch(r"[0-9a-f]{32}", control)
        or type(worker_id) is not int
        or worker_id < 1
        or worker_id == run["id"]
        or receipt.get("control_task_id") != control
        or receipt.get("source_sha") != source.source_sha
        or any(
            type(receipt.get(key)) is not int or receipt[key] != expected
            for key, expected in (
                ("source_run_id", source.run_id),
                ("source_run_attempt", source.run_attempt),
            )
        )
        or not re.fullmatch(r"[0-9a-f]{40}", str(run.get("head_sha") or ""))
        or (run.get("repository") or {}).get("full_name", "").casefold() != repo.casefold()
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] < 1
    ):
        return False
    worker = freshness._get(get, f"/repos/{repo}/actions/runs/{worker_id}")
    return (
        worker.get("id") == worker_id
        and type(worker.get("workflow_id")) is int
        and worker["workflow_id"] > 0
        and worker.get("path") == ".github/workflows/fhd-para-github-worker.yml"
        and worker.get("event") == "workflow_dispatch"
        and worker.get("head_branch") == "main"
        and re.fullmatch(r"[0-9a-f]{40}", str(worker.get("head_sha") or "")) is not None
        and (worker.get("repository") or {}).get("full_name", "").casefold() == repo.casefold()
        and type(worker.get("run_attempt")) is int
        and worker["run_attempt"] == 1
        and worker.get("status") == "completed"
        and worker.get("conclusion") == "success"
        and worker.get("display_title") == f"para-workspace-{uuid.UUID(control)}"
    )


def original_repair_result(source, repo, number, get):
    if source.workflow_path not in freshness.CODE_CI_PATHS or source.head_branch == "main":
        return None
    comments = list(freshness.pages(get, f"/repos/{repo}/issues/{number}/comments"))
    intent = para.repair.prior_intent(repo, number, source.head_branch, comments)
    if not intent:
        return None
    target, repaired_sha, control_task, para_task, worker_run = intent
    result = {
        "state": "observing",
        "reason": "original_pr_awaiting_merge",
        "pull_request": target.number,
        "repaired_sha": repaired_sha,
        "control_task_id": control_task,
        "para_task_id": para_task,
        "github_worker_run_id": worker_run,
    }
    if worker_run < 1:
        return {**result, "state": "unresolved", "reason": "original_pr_cloud_receipt_missing"}
    if (
        (target.run_id, target.old_sha, target.workflow_id, target.workflow_path)
        != (source.run_id, source.source_sha, source.workflow_id, source.workflow_path)
        # Legacy already-applied intents remain read-only. A recorded attempt
        # must match this incident and can never grant a new execution.
        or target.run_attempt not in {0, source.run_attempt}
    ):
        return {**result, "state": "unresolved", "reason": "original_pr_source_receipt_mismatch"}
    pr = para.repair.open_pr(repo, target, None, get, authorize=False)
    if pr.get("merged") is not True:
        return result
    head, merged = pr["head"]["sha"], pr.get("merge_commit_sha")
    if not para.repair.SHA.fullmatch(str(merged or "")):
        return {**result, "reason": "original_pr_merge_commit_missing"}
    if head != repaired_sha:
        lineage = freshness._get(get, f"/repos/{repo}/compare/{repaired_sha}...{head}")
        if lineage.get("merge_base_commit", {}).get("sha") != repaired_sha:
            return {**result, "reason": "original_pr_repair_not_in_merged_head"}
    ci_run_id = para.repair.new_ci_run(repo, target, head, get)
    if not ci_run_id:
        return {**result, "reason": "original_pr_merge_ci_missing"}
    run = freshness._get(get, f"/repos/{repo}/actions/runs/{ci_run_id}")
    if (
        run.get("id") != ci_run_id
        or run.get("head_sha") != head
        or run.get("workflow_id") != target.workflow_id
        or run.get("path") != target.workflow_path
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        return {**result, "reason": "original_pr_merge_ci_unconfirmed"}
    comparison = freshness._get(get, f"/repos/{repo}/compare/{merged}...main")
    if comparison.get("merge_base_commit", {}).get("sha") != merged:
        return {**result, "reason": "original_pr_merge_not_on_main"}
    return {
        **result,
        "state": "recovered",
        "reason": "original_pr_merged_and_read_back",
        "merged_head_sha": head,
        "merge_commit_sha": merged,
        "ci_run_id": ci_run_id,
    }


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
        original = original_repair_result(source, repo, number, get)
        if original:
            result.update(original)
            if result["state"] != "recovered":
                return result
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
            f"原 CI 事件 `{source.run_id}/{source.run_attempt}` 对账：`{result['state']}`。"
            f"依据：`{result['reason']}`；source `{source.source_sha}`，current `{source.current_sha}`。"
        )
        if original:
            body += (
                f"\n原 PR #{original['pull_request']} 已合入 main，提交 `{original['merge_commit_sha']}`。"
                f"\nCI：https://github.com/{repo}/actions/runs/{original['ci_run_id']}"
            )
        elif source.disposition == "superseded":
            body += "\n旧来源无需继续派单，修复及发布状态须另行核验。"
        status, _ = write("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})
        if status != 201:
            return {**result, "state": "unresolved", "reason": "closure_receipt_failed"}
        status, _ = write(
            "PATCH",
            f"/repos/{repo}/issues/{number}",
            {
                "state": "closed",
                "state_reason": ("completed" if result["state"] == "recovered" else "not_planned"),
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
    run_id = int(plan.get("dispatch_run_id") or 0)
    if not run_id and plan["reason"] != "dispatch_rejected":
        return {
            **result,
            **recover_dispatch(
                plan,
                repo=repo,
                number=number,
                get=get,
                write=write,
                dry_run=dry_run,
            ),
        }
    if plan["dispatch_count"] >= MAX_RECOVERY_ATTEMPTS:
        return {**result, "reason": "recovery_attempt_budget_exhausted"}
    if not run_id:
        # A definitive rejection may be retried; timeout/204/pending never proves absence.
        action = "retry_rejected_dispatch"
    else:
        run = freshness._get(get, f"/repos/{repo}/actions/runs/{run_id}")
        if (
            run.get("id") != run_id
            or freshness.workflow_identity(run)[1] != IMPLEMENT_PATH
            or run.get("event")
            not in {"workflow_dispatch", "issues", "issue_comment", "workflow_run"}
            or run.get("head_branch") != "main"
            or (
                run.get("event") == "workflow_run"
                and not _original_worker_resume_matches(run, plan, source, repo, get)
            )
            or (
                (plan.get("dispatch_receipt") or {}).get("dispatch_request_id")
                and not _dispatch_run_matches(
                    run,
                    repo,
                    number,
                    plan["dispatch_receipt"]["dispatch_request_id"],
                )
            )
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
