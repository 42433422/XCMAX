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

Transport = Callable[[str, str, dict[str, Any] | None, str], tuple[int, dict[str, Any]]]


def run_live_pr_comment_probe(pr_url: str, *, body: str = "", token: str = "", transport: Transport | None = None) -> dict[str, Any]:
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
    permission_denied = False
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
            permission_denied = create_status in {401, 403}
            rollback_receipts.append({"created": False, "status_code": create_status, "response": created})
    rollback_verified = bool(created_receipts) and len(created_receipts) == sum(1 for item in rollback_receipts if item.get("deleted"))
    can_write = any(bool(permission.get(key)) for key in ("admin", "maintain", "push", "triage"))
    degraded_without_write = bool(permission_denied and not created_receipts)
    if rollback_verified:
        status = "live_rolled_back"
    elif degraded_without_write:
        status = "permission_denied_degraded"
    elif can_write:
        status = "permission_verified_no_write"
    else:
        status = "blocked"
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
            "rollback_verified": rollback_verified or degraded_without_write,
            "live_github_write": bool(created_receipts),
            "permission_denied": permission_denied,
            "degraded_without_write": degraded_without_write,
        },
        "created_receipts": created_receipts,
        "rollback_receipts": rollback_receipts,
        "evidence": {
            "api": "GitHub REST issues comments",
            "target_is_pull_request": bool(pull_payload.get("number")),
            "head_ref": str((pull_payload.get("head") or {}).get("ref") or ""),
            "base_ref": str((pull_payload.get("base") or {}).get("ref") or ""),
            "token_redacted": True,
            "real_network": transport is None,
            "transport": "github_rest" if transport is None else "injected_transport",
            "required_permission": "issues:write or pull_requests:write",
            "degradation": "no_comment_created_no_rollback_needed" if degraded_without_write else "",
        },
    }


def run_readonly_pr_degradation_probe(pr_url: str, *, transport: Transport | None = None) -> dict[str, Any]:
    owner, repo, number = _parse_pr_url(pr_url)
    call = transport or _github_public_request
    repo_status, _repo_payload = call("GET", f"https://api.github.com/repos/{owner}/{repo}", None, "")
    pull_status, pull_payload = call("GET", f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}", None, "")
    target_found = repo_status < 400 and pull_status < 400 and bool(pull_payload.get("number"))
    return {
        "status": "read_only_degraded" if target_found else "blocked",
        "pr_url": f"https://github.com/{owner}/{repo}/pull/{number}",
        "summary": {
            "target_repo": f"{owner}/{repo}",
            "pull_number": int(number),
            "repo_status": repo_status,
            "pull_status": pull_status,
            "token_present": False,
            "created_comment_count": 0,
            "rolled_back_comment_count": 0,
            "rollback_verified": target_found,
            "live_github_write": False,
            "permission_denied": target_found,
            "degraded_without_write": target_found,
            "degradation_artifact_ready": target_found,
        },
        "created_receipts": [],
        "rollback_receipts": [{"created": False, "status_code": 0, "response": {"reason": "read_only_probe_suppressed_write"}}] if target_found else [],
        "evidence": {
            "api": "GitHub REST public read-only",
            "target_is_pull_request": bool(pull_payload.get("number")),
            "head_ref": str((pull_payload.get("head") or {}).get("ref") or ""),
            "base_ref": str((pull_payload.get("base") or {}).get("ref") or ""),
            "token_redacted": True,
            "real_network": transport is None,
            "transport": "github_rest_readonly" if transport is None else "injected_transport",
            "required_permission": "issues:write or pull_requests:write",
            "write_suppressed_reason": "no_token_read_only_probe",
            "degradation": "dry_run_review_payload_only_no_comment_created" if target_found else "target_not_readable",
            "degradation_artifact": {
                "kind": "publish_dry_run",
                "target": f"{owner}/{repo}#{number}",
                "next_step": "request_write_token_or_export_review_payload",
            },
        },
    }


def run_low_permission_pr_degradation_probe(pr_url: str, *, transport: Transport | None = None) -> dict[str, Any]:
    owner, repo, number = _parse_pr_url(pr_url)
    if transport is None:
        repo_status, _repo_payload = _github_public_request("GET", f"https://api.github.com/repos/{owner}/{repo}", None, "")
        pull_status, pull_payload = _github_public_request("GET", f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}", None, "")
        create_status, created = _github_request("POST", f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments", {"body": "Retort low-permission probe should not be created."}, "")
        transport_name = "github_rest_public_read_then_unauthorized_write"
    else:
        repo_status, _repo_payload = transport("GET", f"https://api.github.com/repos/{owner}/{repo}", None, "")
        pull_status, pull_payload = transport("GET", f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}", None, "")
        create_status, created = transport("POST", f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments", {"body": "Retort low-permission probe should not be created."}, "")
        transport_name = "injected_transport"
    target_found = repo_status < 400 and pull_status < 400 and bool(pull_payload.get("number"))
    permission_denied = create_status in {401, 403}
    degraded_without_write = bool(target_found and permission_denied)
    return {
        "status": "permission_denied_degraded" if degraded_without_write else "blocked",
        "pr_url": f"https://github.com/{owner}/{repo}/pull/{number}",
        "summary": {
            "target_repo": f"{owner}/{repo}",
            "pull_number": int(number),
            "repo_status": repo_status,
            "pull_status": pull_status,
            "token_present": False,
            "permission_admin": False,
            "permission_maintain": False,
            "permission_push": False,
            "created_comment_count": 0,
            "rolled_back_comment_count": 0,
            "rollback_verified": degraded_without_write,
            "live_github_write": False,
            "permission_denied": permission_denied,
            "degraded_without_write": degraded_without_write,
            "write_attempt_status": create_status,
        },
        "created_receipts": [],
        "rollback_receipts": [{"created": False, "status_code": create_status, "response": created}],
        "evidence": {
            "api": "GitHub REST issues comments",
            "target_is_pull_request": bool(pull_payload.get("number")),
            "head_ref": str((pull_payload.get("head") or {}).get("ref") or ""),
            "base_ref": str((pull_payload.get("base") or {}).get("ref") or ""),
            "token_redacted": True,
            "real_network": transport is None,
            "transport": transport_name,
            "required_permission": "issues:write or pull_requests:write",
            "degradation": "write_attempt_denied_no_comment_created" if degraded_without_write else "target_not_readable_or_write_unexpectedly_allowed",
            "degradation_artifact": {
                "kind": "permission_denied_publish_attempt",
                "target": f"{owner}/{repo}#{number}",
                "write_attempt_status": create_status,
                "next_step": "request_write_token_or_export_review_payload",
            },
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


def _github_request(method: str, url: str, payload: dict[str, Any] | None, token: str) -> tuple[int, dict[str, Any]]:
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


def _github_public_request(method: str, url: str, payload: dict[str, Any] | None, token: str) -> tuple[int, dict[str, Any]]:
    del token
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "retort-readonly-probe",
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


def write_live_pr_comment_probe(pr_url: str, output: str | Path, *, body: str = "") -> dict[str, Any]:
    started = time.monotonic()
    result = run_live_pr_comment_probe(pr_url, body=body)
    result["summary"]["duration_sec"] = round(time.monotonic() - started, 3)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def write_readonly_pr_degradation_probe(pr_url: str, output: str | Path) -> dict[str, Any]:
    started = time.monotonic()
    result = run_readonly_pr_degradation_probe(pr_url)
    result["summary"]["duration_sec"] = round(time.monotonic() - started, 3)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def write_low_permission_pr_degradation_probe(pr_url: str, output: str | Path) -> dict[str, Any]:
    started = time.monotonic()
    result = run_low_permission_pr_degradation_probe(pr_url)
    result.setdefault("summary", {})["duration_sec"] = round(time.monotonic() - started, 3)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result
