"""Promote an approved capability proposal into the controlled AI queue.

The promotion boundary is deliberately narrow:

* only an open, generated ``capability-proposal`` issue is eligible;
* the approval must be an exact repository-owner comment;
* ``ai-implement`` is added before an explicit workflow dispatch;
* a durable issue-comment receipt prevents duplicate dispatch on reruns.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

FHD_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = FHD_ROOT / "test_reports"
APPROVAL_COMMANDS = {"确认实现", "/approve-implementation"}
REQUIRED_LABELS = {"capability-proposal", "auto-generated", "needs-human"}
IMPLEMENT_LABEL = "ai-implement"
WORKFLOW_PATH = "fhd-ai-issue-implement.yml"
RECEIPT_PREFIX = "xcagi-capability-promotion"


@dataclass
class PromotionResult:
    issue_number: int
    repo: str
    approval_comment_id: int
    started_at: str
    finished_at: str = ""
    ok: bool = False
    status: str = "init"
    reason: str = ""
    workflow: str = WORKFLOW_PATH
    workflow_ref: str = "main"
    target_branch: str = "main"
    receipt_comment_id: int = 0
    dispatch_requested: bool = False


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_report(result: PromotionResult) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"capability_promotion_{result.issue_number}.json"
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_request(
    url: str,
    token: str,
    *,
    method: str,
    body: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_gh_headers(token), method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API {method} {exc.code}: {detail}") from exc
    return json.loads(raw) if raw else {}


def _gh_get(url: str, token: str) -> Any:
    return _gh_request(url, token, method="GET")


def _gh_post(url: str, token: str, body: dict[str, Any]) -> Any:
    return _gh_request(url, token, method="POST", body=body)


def _gh_patch(url: str, token: str, body: dict[str, Any]) -> Any:
    return _gh_request(url, token, method="PATCH", body=body)


def _gh_delete_label(repo: str, issue_number: int, label: str, token: str) -> None:
    encoded = urllib.parse.quote(label, safe="")
    _gh_request(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels/{encoded}",
        token,
        method="DELETE",
    )


def _label_names(issue: dict[str, Any]) -> set[str]:
    return {
        str(label.get("name") or "").strip()
        for label in issue.get("labels") or []
        if isinstance(label, dict) and str(label.get("name") or "").strip()
    }


def _validate_branch(value: str, *, name: str) -> str:
    branch = value.strip()
    if not branch or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch):
        raise ValueError(f"invalid {name}: {value!r}")
    if (
        branch.startswith("refs/")
        or branch == "HEAD"
        or ".." in branch
        or "//" in branch
        or branch.endswith(("/", ".lock"))
    ):
        raise ValueError(f"invalid {name}: {value!r}")
    return branch


def _validate_promotion(
    issue: dict[str, Any],
    comment: dict[str, Any],
    *,
    issue_number: int,
) -> tuple[bool, str]:
    if str(issue.get("state") or "").lower() != "open":
        return False, "capability proposal is not open"
    if "pull_request" in issue:
        return False, "pull requests cannot be promoted as capability proposals"

    labels = _label_names(issue)
    missing = sorted(REQUIRED_LABELS - labels)
    if missing:
        return False, f"missing required proposal labels: {', '.join(missing)}"

    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    if not title.startswith("[capability-proposal]"):
        return False, "issue title is not a generated capability proposal"
    for marker in ("来源：能力提案 (capability_proposal)", "## 结构化上下文", "## 治理门禁"):
        if marker not in body:
            return False, f"missing governed proposal marker: {marker}"

    association = str(comment.get("author_association") or "").strip().upper()
    command = str(comment.get("body") or "").strip().casefold()
    if association != "OWNER":
        return False, "approval comment is not from the repository owner"
    if command not in {item.casefold() for item in APPROVAL_COMMANDS}:
        return False, "approval comment is not an exact approval command"

    issue_url = str(comment.get("issue_url") or "")
    if issue_url and not issue_url.rstrip("/").endswith(f"/issues/{issue_number}"):
        return False, "approval comment belongs to a different issue"
    return True, "repository owner approved a governed capability proposal"


def _receipt_marker(issue_number: int, approval_comment_id: int) -> str:
    return f"<!-- {RECEIPT_PREFIX}:{issue_number}:{approval_comment_id} -->"


def _find_receipt(comments: list[dict[str, Any]], marker: str) -> tuple[int, str] | None:
    matches: list[tuple[int, str]] = []
    for comment in comments:
        body = str(comment.get("body") or "")
        if marker not in body:
            continue
        status_match = re.search(r"promotion-status:([a-z_]+)", body)
        status = status_match.group(1) if status_match else "unknown"
        matches.append((int(comment.get("id") or 0), status))
    if not matches:
        return None
    # A completed receipt always wins, even if a stale failed receipt appears
    # earlier in the issue timeline. Otherwise use the newest attempt.
    for receipt in reversed(matches):
        if receipt[1] == "dispatched":
            return receipt
    return matches[-1]


def _receipt_body(
    marker: str,
    *,
    status: str,
    issue_number: int,
    approval_comment_id: int,
    workflow_ref: str,
    target_branch: str,
    detail: str = "",
) -> str:
    icon = "✅" if status == "dispatched" else ("⏳" if status == "dispatching" else "⚠️")
    detail_line = f"\n- 详情：{detail}" if detail else ""
    return (
        f"{marker}\n"
        f"<!-- promotion-status:{status} -->\n"
        f"{icon} 能力提案治理晋级：{status}\n\n"
        f"- 提案：#{issue_number}\n"
        f"- 所有者批准评论：{approval_comment_id}\n"
        f"- 实现工作流：{WORKFLOW_PATH}@{workflow_ref}\n"
        f"- 目标分支：{target_branch}"
        f"{detail_line}\n\n"
        "实现产出的代码仍必须进入 risk:r2 独立审查，不能由本批准直接合并。"
    )


def _finish(result: PromotionResult, *, ok: bool, status: str, reason: str) -> int:
    result.ok = ok
    result.status = status
    result.reason = reason
    result.finished_at = _utc_now()
    _write_report(result)
    if ok:
        logger.info("%s", reason)
        return 0
    logger.error("%s", reason)
    return 1


def run(args: argparse.Namespace) -> int:
    issue_number = int(args.issue_number)
    approval_comment_id = int(args.comment_id)
    result = PromotionResult(
        issue_number=issue_number,
        repo=args.repo,
        approval_comment_id=approval_comment_id,
        started_at=_utc_now(),
    )
    try:
        result.workflow_ref = _validate_branch(args.workflow_ref, name="workflow_ref")
        result.target_branch = _validate_branch(args.target_branch, name="target_branch")
    except ValueError as exc:
        return _finish(result, ok=False, status="rejected", reason=str(exc))

    if not args.repo or not args.token:
        return _finish(
            result,
            ok=False,
            status="rejected",
            reason="--repo and --token are required",
        )

    api = f"https://api.github.com/repos/{args.repo}"
    try:
        issue = _gh_get(f"{api}/issues/{issue_number}", args.token)
        comment = _gh_get(f"{api}/issues/comments/{approval_comment_id}", args.token)
        comments = _gh_get(f"{api}/issues/{issue_number}/comments?per_page=100", args.token)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - audit report must survive API errors
        return _finish(result, ok=False, status="failed", reason=f"GitHub read failed: {exc}")

    valid, reason = _validate_promotion(
        issue,
        comment,
        issue_number=issue_number,
    )
    if not valid:
        return _finish(result, ok=False, status="rejected", reason=reason)

    marker = _receipt_marker(issue_number, approval_comment_id)
    existing_receipt = _find_receipt(comments if isinstance(comments, list) else [], marker)
    if existing_receipt:
        result.receipt_comment_id = existing_receipt[0]
        if existing_receipt[1] == "dispatched":
            result.dispatch_requested = True
            return _finish(
                result,
                ok=True,
                status="already_dispatched",
                reason="durable promotion receipt already records a successful dispatch",
            )
        if existing_receipt[1] == "dispatching":
            return _finish(
                result,
                ok=False,
                status="ambiguous_dispatch",
                reason="promotion receipt is still dispatching; fail closed to prevent duplication",
            )

    if args.dry_run:
        return _finish(result, ok=True, status="dry_run", reason=reason)

    labels = _label_names(issue)
    added_implement_label = IMPLEMENT_LABEL not in labels
    receipt_url = f"{api}/issues/{issue_number}/comments"
    pending_body = _receipt_body(
        marker,
        status="dispatching",
        issue_number=issue_number,
        approval_comment_id=approval_comment_id,
        workflow_ref=result.workflow_ref,
        target_branch=result.target_branch,
    )

    try:
        if added_implement_label:
            _gh_post(
                f"{api}/issues/{issue_number}/labels",
                args.token,
                {"labels": [IMPLEMENT_LABEL]},
            )
        receipt = _gh_post(receipt_url, args.token, {"body": pending_body})
        result.receipt_comment_id = int(receipt.get("id") or 0)
        if not result.receipt_comment_id:
            raise RuntimeError("GitHub did not return a receipt comment id")
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        if added_implement_label:
            try:
                _gh_delete_label(args.repo, issue_number, IMPLEMENT_LABEL, args.token)
            except BOUNDARY_ERRORS as rollback_exc:  # noqa: BLE001
                logger.error("label rollback failed: %s", rollback_exc)
        return _finish(result, ok=False, status="failed", reason=f"promotion prepare failed: {exc}")

    try:
        _gh_post(
            f"{api}/actions/workflows/{WORKFLOW_PATH}/dispatches",
            args.token,
            {
                "ref": result.workflow_ref,
                "inputs": {
                    "issue_number": str(issue_number),
                    "target_branch": result.target_branch,
                },
            },
        )
        result.dispatch_requested = True
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        failure_body = _receipt_body(
            marker,
            status="failed",
            issue_number=issue_number,
            approval_comment_id=approval_comment_id,
            workflow_ref=result.workflow_ref,
            target_branch=result.target_branch,
            detail=str(exc)[:300],
        )
        try:
            _gh_patch(
                f"{api}/issues/comments/{result.receipt_comment_id}",
                args.token,
                {"body": failure_body},
            )
        except BOUNDARY_ERRORS as receipt_exc:  # noqa: BLE001
            logger.error("failed to update dispatch failure receipt: %s", receipt_exc)
        if added_implement_label:
            try:
                _gh_delete_label(args.repo, issue_number, IMPLEMENT_LABEL, args.token)
            except BOUNDARY_ERRORS as rollback_exc:  # noqa: BLE001
                logger.error("label rollback failed: %s", rollback_exc)
        return _finish(result, ok=False, status="dispatch_failed", reason=str(exc))

    completed_body = _receipt_body(
        marker,
        status="dispatched",
        issue_number=issue_number,
        approval_comment_id=approval_comment_id,
        workflow_ref=result.workflow_ref,
        target_branch=result.target_branch,
    )
    try:
        _gh_patch(
            f"{api}/issues/comments/{result.receipt_comment_id}",
            args.token,
            {"body": completed_body},
        )
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return _finish(
            result,
            ok=False,
            status="receipt_update_failed",
            reason=(
                "implementation dispatch was requested but its receipt stayed dispatching; "
                f"manual verification required: {exc}"
            ),
        )

    return _finish(
        result,
        ok=True,
        status="dispatched",
        reason="owner-approved capability proposal dispatched to controlled implementation",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote an approved capability proposal")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--comment-id", required=True, type=int)
    parser.add_argument("--workflow-ref", default="main")
    parser.add_argument("--target-branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
