from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable
from typing import Optional, Union

Transport = Callable[[str, str, Optional[dict[str, Any]], str], tuple[int, dict[str, Any]]]


def run_live_pr_comment_probe(
    pr_url: str,
    *,
    body: str = "",
    token: str = "",
    transport: Optional[Transport] = None,
) -> dict[str, Any]:
    owner, repo, number = _parse_pr_url(pr_url)
    resolved_token = _resolve_token(token)
    if not resolved_token:
        return _blocked(pr_url, "missing_github_token")
    call = transport or _github_request
    repo_status, repo_payload = call("GET", f"https://api.github.com/repos/{owner}/{repo}", None, resolved_token)
    pull_status, pull_payload = call("GET", f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}", None, resolved_token)
    permission = repo_payload.get("permissions") if isinstance(repo_payload.get("permissions"), dict) else {}
    marker = f"retort-live-probe:{uuid.uuid4().hex[:12]}"
    comment_body = body.strip() or f"Retort controlled live publish probe. marker={marker}. This comment will be deleted immediately."
    created_receipts: list[dict[str, Any]] = []
    rollback_receipts: list[dict[str, Any]] = []
    if repo_status < 400 and pull_status < 400:
        create_status, created = call("POST", f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments", {"body": comment_body}, resolved_token)
        if create_status < 400:
            comment_id = str(created.get("id") or "")
            created_receipts.append(
                {
                    "comment_id": comment_id,
                    "html_url": str(created.get("html_url") or ""),
                    "body_marker": marker,
                    "created": True,
                    "target": "pull_request_conversation",
                }
            )
            if comment_id:
                delete_status, deleted = call("DELETE", f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}", None, resolved_token)
                rollback_receipts.append(
                    {
                        "comment_id": comment_id,
                        "deleted": delete_status in {200, 202, 204},
                        "status_code": delete_status,
                        "response": deleted,
                    }
                )
        else:
            rollback_receipts.append({"created": False, "status_code": create_status, "response": created})
    rollback_verified = bool(created_receipts) and len(created_receipts) == sum(1 for item in rollback_receipts if item.get("deleted"))
    can_write = any(bool(permission.get(key)) for key in ("admin", "maintain", "push", "triage"))
    status = "live_rolled_back" if rollback_verified else ("permission_verified_no_write" if can_write else "blocked")
    return {
        "status": status,
        "pr_url": f"https://github.com/{owner}/{repo}/pull/{number}",
        "summary": {
            "target_repo": f"{owner}/{repo}",
            "pull_number": int(number),
            "repo_status": repo_status,
            "pull_status": pull_status,
            "token_present": bool(resolved_token),
            "permission_admin": bool(permission.get("admin")),
            "permission_maintain": bool(permission.get("maintain")),
            "permission_push": bool(permission.get("push")),
            "created_comment_count": len(created_receipts),
            "rolled_back_comment_count": sum(1 for item in rollback_receipts if item.get("deleted")),
            "rollback_verified": rollback_verified,
            "live_github_write": bool(created_receipts),
        },
        "created_receipts": created_receipts,
        "rollback_receipts": rollback_receipts,
        "evidence": {
            "api": "GitHub REST issues comments",
            "target_is_pull_request": bool(pull_payload.get("number")),
            "head_ref": str((pull_payload.get("head") or {}).get("ref") or ""),
            "base_ref": str((pull_payload.get("base") or {}).get("ref") or ""),
            "token_redacted": True,
        },
    }


def _blocked(pr_url: str, reason: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "pr_url": pr_url,
        "summary": {"reason": reason, "created_comment_count": 0, "rolled_back_comment_count": 0, "rollback_verified": False, "live_github_write": False},
        "created_receipts": [],
        "rollback_receipts": [],
        "evidence": {"token_redacted": True},
    }


def _parse_pr_url(pr_url: str) -> tuple[str, str, str]:
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:/.*)?$", pr_url.strip())
    if not match:
        raise ValueError("publish-pr-live-probe expects a GitHub pull request URL")
    return match.group(1), match.group(2), match.group(3)


def _resolve_token(token: str) -> str:
    if token.strip():
        return token.strip()
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    try:
        result = subprocess.run(["gh", "auth", "token"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _github_request(
    method: str,
    url: str,
    payload: Optional[dict[str, Any]],
    token: str,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "retort-live-probe",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            payload = {"message": body}
        return int(exc.code), payload


def write_live_pr_comment_probe(pr_url: str, output: Union[str, Path], *, body: str = "") -> dict[str, Any]:
    started = time.monotonic()
    result = run_live_pr_comment_probe(pr_url, body=body)
    result["summary"]["duration_sec"] = round(time.monotonic() - started, 3)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result
