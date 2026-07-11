"""Deterministic, signed fact collection for management-task acceptance."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ACTION_KEYWORDS = (
    "修复",
    "修改",
    "实现",
    "写入",
    "创建",
    "删除",
    "发布",
    "部署",
    "上线",
    "发送",
    "安装",
    "配置",
    "重启",
    "提交",
    "合并",
    "更新",
    "退款",
    "fix ",
    "modify",
    "implement",
    "write ",
    "create ",
    "delete ",
    "deploy",
    "release",
    "publish",
    "send ",
    "install",
    "configure",
    "restart",
    "commit",
    "merge",
    "update ",
    "refund",
)
_MUTATING_TOOLS = {
    "write_workspace_file",
    "http_post",
    "send_email",
    "send_message",
    "deploy",
    "publish",
    "restart_service",
    "run_command",
    "execute_command",
}
_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".tsv",
    ".html",
    ".htm",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".vue",
    ".kt",
    ".java",
    ".go",
    ".rs",
    ".sh",
}
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)"
    r"(\s*[:=]\s*)([^\s,;\"']{4,})"
)
_SENSITIVE_PATH_PATTERN = re.compile(
    r"(?i)(^|[._-])(secret|token|credential|password|private[-_]?key)([._-]|$)"
)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b")
_PEM_PATTERN = re.compile(
    r"-----BEGIN [^-]{1,64}-----.*?-----END [^-]{1,64}-----",
    re.DOTALL,
)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact(text: str) -> str:
    cleaned = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text)
    cleaned = _JWT_PATTERN.sub("<redacted-jwt>", cleaned)
    return _PEM_PATTERN.sub("<redacted-private-material>", cleaned)


def redact_runtime_claim(value: Any, *, _depth: int = 0) -> Any:
    """Bound and recursively redact employee-controlled evidence before storage/LLM."""

    if _depth > 12:
        return "<truncated-depth>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= 200:
                out["<truncated-items>"] = len(value) - 200
                break
            name = str(key)[:256]
            if _SENSITIVE_PATH_PATTERN.search(name) or name.lower() in {
                "authorization",
                "cookie",
                "set-cookie",
                "access_token",
                "refresh_token",
                "password",
                "secret",
            }:
                out[name] = "<redacted>"
            else:
                out[name] = redact_runtime_claim(child, _depth=_depth + 1)
        return out
    if isinstance(value, list):
        return [redact_runtime_claim(child, _depth=_depth + 1) for child in value[:500]]
    if isinstance(value, tuple):
        return [redact_runtime_claim(child, _depth=_depth + 1) for child in value[:500]]
    if isinstance(value, str):
        return _redact(value[:120_000])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact(str(value)[:4000])


def _allowed_roots() -> list[Path]:
    candidates = [Path(__file__).resolve().parent.parent]
    for key in (
        "XCMAX_MONOREPO_ROOT",
        "MODSTORE_REPO_ROOT",
        "MODSTORE_GIT_REPO_ROOT",
        "MODSTORE_MANAGEMENT_WORKSPACE_ROOT",
        "MODSTORE_MANAGEMENT_EVIDENCE_ROOTS",
    ):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        values = raw.split(os.pathsep) if key.endswith("ROOTS") else [raw]
        candidates.extend(Path(value).expanduser() for value in values if value.strip())
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved == Path(resolved.anchor) or len(resolved.parts) < 3:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _under_allowed_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _allowed_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _claim_id(value: Any, index: int) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())[:80]
    return clean or f"claim_{index}"


_UNTRUSTED_INPUT_KEYS = {
    "input",
    "input_data",
    "normalized_input",
    "original_input",
    "request",
    "task",
    "task_description",
    "user_request",
    "management_work",
    "upstream_results",
}


def _extract_claims(runtime_result: Any) -> tuple[list[dict[str, Any]], list[str]]:
    claims: list[dict[str, Any]] = []
    side_effect_reasons: list[str] = []

    def add(raw: Any, *, derived_from: str) -> None:
        if not isinstance(raw, dict) or len(claims) >= 30:
            return
        claim = dict(raw)
        claim.setdefault("derived_from", derived_from)
        canonical = _dumps(claim)
        if any(_dumps(existing) == canonical for existing in claims):
            return
        claims.append(claim)

    def walk(value: Any, *, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key in ("management_evidence_claims", "evidence_claims"):
                rows = value.get(key)
                if isinstance(rows, list):
                    for row in rows:
                        add(row, derived_from=key)

            workspace_root = str(value.get("workspace_root") or "").strip()
            files_changed = value.get("files_changed")
            if isinstance(files_changed, list):
                for row in files_changed:
                    path = str(row.get("path") if isinstance(row, dict) else row or "").strip()
                    if path:
                        add(
                            {
                                "kind": "file",
                                "path": path,
                                "workspace_root": workspace_root,
                                "expected": {"exists": True, "min_size": 1},
                            },
                            derived_from="files_changed",
                        )
                        side_effect_reasons.append("files_changed")

            change_ids = value.get("change_request_ids")
            if isinstance(change_ids, list):
                for raw_id in change_ids:
                    try:
                        change_id = int(raw_id or 0)
                    except (TypeError, ValueError):
                        change_id = 0
                    if change_id > 0:
                        add(
                            {"kind": "change_request", "change_request_id": change_id},
                            derived_from="change_request_ids",
                        )
                        side_effect_reasons.append("change_request")

            artifacts = value.get("artifacts")
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    path = str(
                        artifact.get("path")
                        or artifact.get("file_path")
                        or artifact.get("filepath")
                        or ""
                    ).strip()
                    if path:
                        expected: dict[str, Any] = {"exists": True, "min_size": 1}
                        if artifact.get("sha256"):
                            expected["sha256"] = str(artifact["sha256"])
                        add(
                            {
                                "kind": "file",
                                "path": path,
                                "workspace_root": workspace_root,
                                "expected": expected,
                            },
                            derived_from="artifacts",
                        )
                        side_effect_reasons.append("artifact")

            tool = str(value.get("tool") or "").strip().lower()
            if tool in _MUTATING_TOOLS:
                side_effect_reasons.append(f"tool:{tool}")
            operation = value.get("management_operation")
            if isinstance(operation, dict):
                operation_id = str(operation.get("operation_id") or "").strip()
                if operation_id:
                    add(
                        {
                            "kind": "operation",
                            "operation_id": operation_id,
                            "expected": {"status": "succeeded"},
                        },
                        derived_from="management_operation",
                    )
                    side_effect_reasons.append(
                        f"operation:{str(operation.get('kind') or 'unknown')[:64]}"
                    )
            operation_ids = value.get("management_operation_ids")
            if isinstance(operation_ids, list):
                for operation_id in operation_ids:
                    clean_id = str(operation_id or "").strip()
                    if clean_id:
                        add(
                            {
                                "kind": "operation",
                                "operation_id": clean_id,
                                "expected": {"status": "succeeded"},
                            },
                            derived_from="management_operation_ids",
                        )
                        side_effect_reasons.append("operation:declared")
            for key, child in value.items():
                normalized_key = str(key or "").strip().lower()
                # Task input is employee-controlled context, not employee output. It may
                # contain an evidence template, so scanning it would let a plain echo
                # masquerade as completed work.
                if normalized_key in _UNTRUSTED_INPUT_KEYS:
                    continue
                walk(child, path=(*path, normalized_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, path=path)
        # Do not recursively parse JSON-looking strings. Those are LLM prose,
        # not a typed tool result, and accepting claims from them lets an echo
        # or prompt injection masquerade as machine evidence.

    walk(runtime_result)
    return claims[:30], list(dict.fromkeys(side_effect_reasons))[:30]


def _json_subset(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _json_subset(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_json_subset(candidate, wanted) for candidate in actual) for wanted in expected
        )
    return actual == expected


def _collect_file(claim: dict[str, Any], index: int) -> dict[str, Any]:
    raw_path = str(claim.get("path") or "").strip()
    root = str(claim.get("workspace_root") or "").strip()
    path = Path(raw_path).expanduser()
    explicit_claim = str(claim.get("derived_from") or "") in {
        "management_evidence_claims",
        "evidence_claims",
    }
    if explicit_claim and path.is_absolute():
        return {
            "evidence_id": f"fact_{index}",
            "claim_id": _claim_id(claim.get("claim_id"), index),
            "kind": "file",
            "source": "system_file_reader",
            "path": str(path),
            "verified": False,
            "strength": "none",
            "checks": {},
            "error": "explicit file claims must use a relative path and workspace_root",
        }
    if not path.is_absolute() and root:
        path = Path(root).expanduser() / path
    expected = claim.get("expected") if isinstance(claim.get("expected"), dict) else {}
    result: dict[str, Any] = {
        "evidence_id": f"fact_{index}",
        "claim_id": _claim_id(claim.get("claim_id"), index),
        "kind": "file",
        "source": "system_file_reader",
        "path": str(path),
        "verified": False,
        "strength": "none",
        "checks": {},
    }
    if not raw_path or not _under_allowed_root(path):
        result["error"] = "file path is outside configured evidence roots"
        return result
    resolved = path.resolve()
    sensitive_parts = {part.lower() for part in resolved.parts}
    if (
        ".env" in sensitive_parts
        or resolved.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
        or any(_SENSITIVE_PATH_PATTERN.search(part) for part in resolved.parts)
    ):
        result["error"] = "sensitive file paths cannot be collected as evidence"
        return result
    exists = resolved.is_file()
    result["path"] = str(resolved)
    result["checks"]["exists"] = exists == bool(expected.get("exists", True))
    if not exists:
        result["error"] = "file does not exist"
        return result
    stat = resolved.stat()
    digest = _sha256_file(resolved)
    result.update({"size": int(stat.st_size), "sha256": digest})
    if expected.get("sha256"):
        result["checks"]["sha256"] = hmac.compare_digest(
            digest, str(expected["sha256"]).strip().lower()
        )
    if expected.get("min_size") is not None:
        result["checks"]["min_size"] = int(stat.st_size) >= int(expected.get("min_size") or 0)
    preview = ""
    if resolved.suffix.lower() in _TEXT_SUFFIXES and stat.st_size <= 2_000_000:
        preview = _redact(resolved.read_text(encoding="utf-8", errors="replace")[:12_000])
        result["text_preview"] = preview
    contains = expected.get("text_contains")
    if isinstance(contains, list):
        result["checks"]["text_contains"] = all(str(value) in preview for value in contains[:20])
    if isinstance(expected.get("json_subset"), (dict, list)):
        try:
            actual_json = json.loads(resolved.read_text(encoding="utf-8"))
            result["checks"]["json_subset"] = _json_subset(actual_json, expected["json_subset"])
        except (OSError, ValueError, json.JSONDecodeError):
            result["checks"]["json_subset"] = False
    result["verified"] = bool(result["checks"]) and all(result["checks"].values())
    strong_checks = {"sha256", "min_size", "text_contains", "json_subset"}
    result["strength"] = (
        "strong"
        if result["verified"] and (strong_checks.intersection(result["checks"]) or bool(preview))
        else ("observed" if result["verified"] else "none")
    )
    return result


def _collect_change_request(claim: dict[str, Any], index: int) -> dict[str, Any]:
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

    try:
        change_id = int(claim.get("change_request_id") or 0)
    except (TypeError, ValueError):
        change_id = 0
    result: dict[str, Any] = {
        "evidence_id": f"fact_{index}",
        "claim_id": _claim_id(claim.get("claim_id"), index),
        "kind": "change_request",
        "source": "management_database",
        "change_request_id": change_id,
        "verified": False,
        "strength": "none",
    }
    if change_id <= 0:
        result["error"] = "invalid change request id"
        return result
    sf = get_session_factory()
    with sf() as session:
        row = session.get(EmployeeChangeRequest, change_id)
        if row is None:
            result["error"] = "change request not found"
            return result
        result.update(
            {
                "status": str(row.status or ""),
                "source_employee_id": str(row.source_employee_id or ""),
                "target_paths": json.loads(row.target_paths_json or "[]"),
                "risk_level": str(row.risk_level or ""),
                "git_branch": str(row.git_branch or ""),
                "base_commit_sha": str(row.base_commit_sha or ""),
                "staged_commit_sha": str(row.staged_commit_sha or ""),
            }
        )
    result["verified"] = result["status"] == "applied"
    result["strength"] = "strong" if result["verified"] else "none"
    if not result["verified"]:
        result["error"] = f"change request is {result['status']}, not applied"
    return result


def _run_git(repo: Path, *args: str) -> tuple[int, str]:
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=8,
        shell=False,
    )
    return int(process.returncode), (process.stdout or process.stderr or "")[:50_000]


def _collect_git(claim: dict[str, Any], index: int) -> dict[str, Any]:
    repo = Path(str(claim.get("repo_path") or "")).expanduser()
    expected = claim.get("expected") if isinstance(claim.get("expected"), dict) else {}
    result: dict[str, Any] = {
        "evidence_id": f"fact_{index}",
        "claim_id": _claim_id(claim.get("claim_id"), index),
        "kind": "git",
        "source": "system_git_reader",
        "repo_path": str(repo),
        "verified": False,
        "strength": "none",
        "checks": {},
    }
    if not _under_allowed_root(repo):
        result["error"] = "git path is outside configured evidence roots"
        return result
    code, head = _run_git(repo, "rev-parse", "HEAD")
    if code != 0:
        result["error"] = "not a readable git repository"
        return result
    code, changed = _run_git(repo, "status", "--porcelain")
    if code != 0:
        result["error"] = "git status failed"
        return result
    changed_paths = [line[3:].strip() for line in changed.splitlines() if len(line) > 3]
    result.update({"head": head.strip(), "changed_paths": changed_paths[:500]})
    if expected.get("head"):
        result["checks"]["head"] = head.strip() == str(expected["head"]).strip()
    if isinstance(expected.get("changed_paths"), list):
        wanted = {str(path).strip() for path in expected["changed_paths"] if str(path).strip()}
        result["checks"]["changed_paths"] = wanted.issubset(set(changed_paths))
    if expected.get("clean") is not None:
        result["checks"]["clean"] = (not changed_paths) == bool(expected["clean"])
    if expected.get("diff_check") is True:
        check_code, check_output = _run_git(repo, "diff", "--check")
        result["checks"]["diff_check"] = check_code == 0
        if check_output.strip():
            result["diff_check_output"] = check_output[:4000]
    if not result["checks"]:
        result["checks"]["repository_readable"] = True
    result["verified"] = all(result["checks"].values())
    result["strength"] = "strong" if result["verified"] else "none"
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _http_host_allowed(parsed: urllib.parse.ParseResult) -> bool:
    host = str(parsed.hostname or "").strip().lower()
    if not host or parsed.scheme not in {"http", "https"}:
        return False
    configured = {
        value.strip().lower()
        for key in (
            "MODSTORE_MANAGEMENT_EVIDENCE_HTTP_ALLOW_HOSTS",
            "MODSTORE_AGENT_HTTP_ALLOW_HOSTS",
        )
        for value in str(os.environ.get(key) or "").split(",")
        if value.strip()
    }
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    if host not in configured:
        return False
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(
        not (
            address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        )
        for address in addresses
    )


def _collect_http(claim: dict[str, Any], index: int) -> dict[str, Any]:
    url = str(claim.get("url") or "").strip()
    expected = claim.get("expected") if isinstance(claim.get("expected"), dict) else {}
    result: dict[str, Any] = {
        "evidence_id": f"fact_{index}",
        "claim_id": _claim_id(claim.get("claim_id"), index),
        "kind": "http",
        "source": "system_http_reader",
        "url": url,
        "verified": False,
        "strength": "none",
        "checks": {},
    }
    parsed = urllib.parse.urlparse(url)
    if not _http_host_allowed(parsed):
        result["error"] = "HTTP evidence host is not allowlisted"
        return result
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json,text/plain;q=0.9,*/*;q=0.1"},
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=6) as response:
            status = int(response.status)
            body = response.read(1_000_001)
            content_type = str(response.headers.get("content-type") or "")[:256]
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(1_000_001)
        content_type = str(exc.headers.get("content-type") or "")[:256]
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:500]
        return result
    if len(body) > 1_000_000:
        result["error"] = "HTTP evidence response exceeds 1 MB"
        return result
    result.update(
        {
            "status": status,
            "content_type": content_type,
            "body_size": len(body),
            "body_sha256": _sha256_bytes(body),
        }
    )
    result["checks"]["status"] = status == int(expected.get("status") or 200)
    if expected.get("body_sha256"):
        result["checks"]["body_sha256"] = hmac.compare_digest(
            result["body_sha256"], str(expected["body_sha256"]).strip().lower()
        )
    text = body.decode("utf-8", errors="replace")
    if isinstance(expected.get("text_contains"), list):
        result["checks"]["text_contains"] = all(
            str(value) in text for value in expected["text_contains"][:20]
        )
    if isinstance(expected.get("json_subset"), (dict, list)):
        try:
            result["checks"]["json_subset"] = _json_subset(
                json.loads(text), expected["json_subset"]
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            result["checks"]["json_subset"] = False
    result["verified"] = all(result["checks"].values())
    result["strength"] = "strong" if result["verified"] else "none"
    return result


def _collect_operation(
    claim: dict[str, Any],
    index: int,
    *,
    task_id: str,
    employee_id: str,
) -> dict[str, Any]:
    from modstore_server.models import (
        ManagementWorkItem,
        ManagementWorkOperation,
        get_session_factory,
    )

    operation_id = str(claim.get("operation_id") or "").strip()
    expected = claim.get("expected") if isinstance(claim.get("expected"), dict) else {}
    result: dict[str, Any] = {
        "evidence_id": f"fact_{index}",
        "claim_id": _claim_id(claim.get("claim_id") or operation_id, index),
        "kind": "operation",
        "source": "management_operation_ledger",
        "operation_id": operation_id,
        "verified": False,
        "strength": "none",
        "checks": {},
    }
    if not operation_id:
        result["error"] = "operation id is required"
        return result
    sf = get_session_factory()
    with sf() as session:
        work = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if work is None:
            result["error"] = "management work item does not exist"
            return result
        row = (
            session.query(ManagementWorkOperation)
            .filter(
                ManagementWorkOperation.operation_id == operation_id,
                ManagementWorkOperation.task_id == str(task_id),
                ManagementWorkOperation.employee_id == str(employee_id),
            )
            .first()
        )
        if row is None:
            result["error"] = "operation does not belong to this task and employee"
            return result
        if int(row.attempt or 0) != int(work.attempt_count or 0):
            result["error"] = "operation receipt belongs to a different task attempt"
            return result
        result.update(
            {
                "operation_kind": str(row.kind or ""),
                "target": str(row.target or ""),
                "status": str(row.status or ""),
                "request_digest": str(row.request_digest or ""),
                "external_ref": str(row.external_ref or ""),
                "operation_attempt": int(row.attempt or 0),
                "completed_at": (row.completed_at.isoformat() if row.completed_at else None),
                "compensation_status": str(row.compensation_status or ""),
            }
        )
    result["checks"]["status"] = result["status"] == str(expected.get("status") or "succeeded")
    if expected.get("request_digest"):
        result["checks"]["request_digest"] = hmac.compare_digest(
            result["request_digest"], str(expected["request_digest"]).strip().lower()
        )
    if expected.get("target"):
        result["checks"]["target"] = result["target"] == str(expected["target"])
    result["verified"] = all(result["checks"].values())
    result["strength"] = "strong" if result["verified"] else "none"
    if not result["verified"]:
        result["error"] = "operation ledger receipt did not satisfy expected state"
    return result


def _collect_claim(
    claim: dict[str, Any],
    index: int,
    *,
    task_id: str,
    employee_id: str,
) -> dict[str, Any]:
    kind = str(claim.get("kind") or "").strip().lower()
    try:
        if kind == "file":
            result = _collect_file(claim, index)
        elif kind == "change_request":
            result = _collect_change_request(claim, index)
        elif kind == "git":
            result = _collect_git(claim, index)
        elif kind == "http":
            result = _collect_http(claim, index)
        elif kind == "operation":
            result = _collect_operation(
                claim,
                index,
                task_id=task_id,
                employee_id=employee_id,
            )
        else:
            result = {
                "evidence_id": f"fact_{index}",
                "claim_id": _claim_id(claim.get("claim_id"), index),
                "kind": kind or "unknown",
                "source": "system_fact_collector",
                "verified": False,
                "strength": "none",
                "error": "unsupported evidence claim kind",
            }
        result["claimed_criterion_ids"] = [
            str(value)[:64]
            for value in (
                claim.get("criterion_ids") if isinstance(claim.get("criterion_ids"), list) else []
            )[:30]
            if str(value).strip()
        ]
        # Employee-provided criterion bindings are retained only as an
        # untrusted claim.  The receipt officer must bind concrete fact IDs to
        # every ledger criterion in its independently validated report.
        result["criterion_ids"] = []
        try:
            ttl_seconds = max(30, min(int(claim.get("ttl_seconds") or 3600), 86400))
        except (TypeError, ValueError):
            ttl_seconds = 3600
        result["expires_at"] = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + ttl_seconds,
            tz=timezone.utc,
        ).isoformat()
        return result
    except Exception as exc:  # noqa: BLE001 - one bad claim must remain auditable
        return {
            "evidence_id": f"fact_{index}",
            "claim_id": _claim_id(claim.get("claim_id"), index),
            "kind": kind or "unknown",
            "source": "system_fact_collector",
            "verified": False,
            "strength": "none",
            "error": f"{type(exc).__name__}: {exc}"[:1000],
        }
    return {
        "evidence_id": f"fact_{index}",
        "claim_id": _claim_id(claim.get("claim_id"), index),
        "kind": kind or "unknown",
        "source": "system_fact_collector",
        "verified": False,
        "strength": "none",
        "error": "unsupported evidence claim kind",
        "criterion_ids": [],
    }


def _fact_required(
    *, task_text: str, task_input: dict[str, Any], side_effect_reasons: list[str]
) -> tuple[bool, bool, list[str]]:
    policy = (
        task_input.get("evidence_policy")
        if isinstance(task_input.get("evidence_policy"), dict)
        else {}
    )
    # Caller-provided flags are monotonic: they may demand stricter evidence but
    # can never waive evidence inferred from the task or observed side effects.
    policy_required = policy.get("required") is True
    policy_operation_required = policy.get("operation_required") is True
    explicit_effects = task_input.get("external_side_effects")
    lowered = f" {str(task_text or '').lower()} "
    matched = [keyword.strip() for keyword in _ACTION_KEYWORDS if keyword in lowered]
    required = bool(policy_required or explicit_effects is True or side_effect_reasons or matched)
    operation_required = bool(
        policy_operation_required or explicit_effects is True or side_effect_reasons or matched
    )
    reasons: list[str] = []
    if policy_required:
        reasons.append("explicit_evidence_policy")
    if policy_operation_required:
        reasons.append("explicit_operation_policy")
    if explicit_effects is True:
        reasons.append("external_side_effects=true")
    reasons.extend(side_effect_reasons)
    reasons.extend(f"task_keyword:{value}" for value in matched[:10])
    return required, operation_required, list(dict.fromkeys(reasons))[:30]


def _signing_secret() -> bytes:
    dedicated = str(os.environ.get("MODSTORE_MANAGEMENT_EVIDENCE_HMAC_KEY") or "").encode("utf-8")
    if dedicated:
        return dedicated
    jwt_secret = str(os.environ.get("MODSTORE_JWT_SECRET") or "").encode("utf-8")
    if not jwt_secret:
        return b""
    return hmac.new(
        jwt_secret,
        b"xcagi-management-evidence-signing-v1",
        hashlib.sha256,
    ).digest()


def _sign_canonical(value: Any) -> str:
    secret = _signing_secret()
    if not secret:
        return ""
    return hmac.new(secret, _dumps(value).encode("utf-8"), hashlib.sha256).hexdigest()


def _sign_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(snapshot)
    unsigned.pop("snapshot_sha256", None)
    unsigned.pop("signature", None)
    unsigned.pop("signature_alg", None)
    canonical = _dumps(unsigned).encode("utf-8")
    digest = _sha256_bytes(canonical)
    secret = _signing_secret()
    return {
        **unsigned,
        "snapshot_sha256": digest,
        "signature_alg": "hmac-sha256" if secret else "unsigned",
        "signature": _sign_canonical(unsigned),
    }


def verify_snapshot_signature(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict):
        return False
    signed = _sign_snapshot(snapshot)
    if signed["signature_alg"] != "hmac-sha256":
        return False
    return hmac.compare_digest(
        str(snapshot.get("snapshot_sha256") or ""), signed["snapshot_sha256"]
    ) and hmac.compare_digest(str(snapshot.get("signature") or ""), signed["signature"])


def collect_independent_fact_snapshot(
    *,
    task_id: str,
    employee_id: str,
    task_text: str,
    task_input: dict[str, Any],
    runtime_result: Any,
) -> dict[str, Any]:
    """Collect facts outside the employee process and return a signed snapshot."""

    claims, side_effect_reasons = _extract_claims(runtime_result)
    required, operation_required, required_reasons = _fact_required(
        task_text=task_text,
        task_input=task_input,
        side_effect_reasons=side_effect_reasons,
    )
    facts = [
        _collect_claim(
            claim,
            index,
            task_id=task_id,
            employee_id=employee_id,
        )
        for index, claim in enumerate(claims, 1)
    ]
    verified = [fact for fact in facts if fact.get("verified") is True]
    strong = [fact for fact in verified if fact.get("strength") == "strong"]
    operation_facts = [fact for fact in strong if fact.get("kind") == "operation"]
    state_facts = [fact for fact in strong if fact.get("kind") != "operation"]
    failed = [fact for fact in facts if fact.get("verified") is not True]
    secret_available = bool(_signing_secret())
    if failed:
        outcome = "fail"
        reason = f"{len(failed)} independent fact claims failed"
    elif operation_required and not operation_facts:
        outcome = "inconclusive"
        reason = "mutating task requires a succeeded server-side operation receipt"
    elif required and not state_facts:
        outcome = "inconclusive"
        reason = "task requires at least one strong independent state observation"
    elif required and not secret_available:
        outcome = "inconclusive"
        reason = "evidence signing key is unavailable"
    else:
        outcome = "pass"
        reason = (
            f"{len(strong)} strong facts independently verified"
            if strong
            else "analysis-only task does not require external fact evidence"
        )
    snapshot = {
        "kind": "independent_fact_snapshot",
        "version": 1,
        "task_id": str(task_id)[:128],
        "employee_id": str(employee_id)[:128],
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "runtime_claim_sha256": _sha256_bytes(_dumps(runtime_result).encode("utf-8")),
        "required": required,
        "operation_required": operation_required,
        "required_reasons": list(dict.fromkeys(required_reasons))[:30],
        "claim_count": len(claims),
        "verified_count": len(verified),
        "strong_verified_count": len(strong),
        "operation_verified_count": len(operation_facts),
        "state_verified_count": len(state_facts),
        "failed_count": len(failed),
        "outcome": outcome,
        "reason": reason,
        "facts": facts,
    }
    return _sign_snapshot(snapshot)


def _parse_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonical_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        parsed = _parse_timestamp(value)
    if parsed is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat()


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _row_payload(row: Any) -> dict[str, Any] | None:
    payload = _row_value(row, "payload")
    if isinstance(payload, dict):
        return payload
    raw = _row_value(row, "payload_json")
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _row_criterion_ids(row: Any) -> list[Any] | None:
    values = _row_value(row, "criterion_ids")
    if isinstance(values, list):
        return values
    raw = _row_value(row, "criterion_ids_json")
    if not isinstance(raw, str):
        return None
    try:
        values = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return values if isinstance(values, list) else None


def fact_payload_sha256(payload: Any) -> str:
    """Return the canonical digest used by persisted management fact rows."""

    return _sha256_bytes(_dumps(payload).encode("utf-8"))


def _fact_evidence_signature_payload(row: Any) -> dict[str, Any]:
    criterion_ids = _row_criterion_ids(row)
    return {
        "kind": "management_work_evidence_row",
        "version": 1,
        "evidence_id": str(_row_value(row, "evidence_id") or ""),
        "work_item_id": int(_row_value(row, "work_item_id") or 0),
        "task_id": str(_row_value(row, "task_id") or ""),
        "attempt": int(_row_value(row, "attempt") or 0),
        "check_id": str(_row_value(row, "check_id") or ""),
        "criterion_ids": criterion_ids if criterion_ids is not None else "<invalid>",
        "fact_kind": str(_row_value(row, "kind") or ""),
        "trust_level": str(_row_value(row, "trust_level") or ""),
        "status": str(_row_value(row, "status") or ""),
        "source_ref": str(_row_value(row, "source_ref") or ""),
        "observed_at": _canonical_timestamp(_row_value(row, "observed_at")),
        "expires_at": _canonical_timestamp(_row_value(row, "expires_at")),
        "collector_version": str(_row_value(row, "collector_version") or ""),
        "payload_sha256": str(_row_value(row, "payload_sha256") or ""),
    }


def sign_persisted_fact_evidence(row: Any) -> str:
    """Sign one persisted fact row with the server-owned evidence key."""

    return _sign_canonical(_fact_evidence_signature_payload(row))


def verify_persisted_fact_evidence(
    row: Any,
    *,
    task_id: str,
    attempt: int,
    work_item_id: int,
    require_passing: bool = True,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Revalidate identity, payload digest, freshness, and row-level HMAC."""

    evidence_id = str(_row_value(row, "evidence_id") or "")
    label = evidence_id or "<missing>"
    if int(_row_value(row, "work_item_id") or 0) != int(work_item_id):
        return False, f"independent fact evidence {label} belongs to another work item"
    if str(_row_value(row, "task_id") or "") != str(task_id):
        return False, f"independent fact evidence {label} belongs to another task"
    if int(_row_value(row, "attempt") or 0) != int(attempt):
        return False, f"independent fact evidence {label} belongs to another attempt"

    status = str(_row_value(row, "status") or "")
    trust_level = str(_row_value(row, "trust_level") or "")
    expires_at = _canonical_timestamp(_row_value(row, "expires_at"))
    parsed_expiry = _parse_timestamp(expires_at)
    if require_passing and status != "pass":
        return False, f"independent fact evidence {label} is not passing"
    if require_passing and trust_level != "independent_observation":
        return False, f"independent fact evidence {label} is not independently observed"
    if require_passing and parsed_expiry is None:
        return False, f"independent fact evidence {label} has no valid expiry"
    current_time = now or datetime.now(timezone.utc)
    current_time = (
        current_time if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
    )
    if require_passing and parsed_expiry is not None and parsed_expiry <= current_time:
        return False, f"independent fact evidence {label} has expired"

    payload = _row_payload(row)
    if payload is None:
        return False, f"independent fact evidence {label} payload is malformed"
    payload_digest = fact_payload_sha256(payload)
    stored_digest = str(_row_value(row, "payload_sha256") or "")
    if not stored_digest or not hmac.compare_digest(stored_digest, payload_digest):
        return False, f"independent fact evidence {label} payload digest mismatch"
    payload_expiry = _canonical_timestamp(payload.get("expires_at"))
    if payload_expiry != expires_at:
        return False, f"independent fact evidence {label} expiry does not match its payload"
    expected_status = "pass" if payload.get("verified") is True else "fail"
    if status != expected_status:
        return False, f"independent fact evidence {label} status does not match its payload"
    if str(_row_value(row, "kind") or "") != str(payload.get("kind") or ""):
        return False, f"independent fact evidence {label} kind does not match its payload"

    signature = str(_row_value(row, "signature") or "")
    expected_signature = sign_persisted_fact_evidence(row)
    if not expected_signature:
        return False, "management evidence signing key is unavailable"
    if not signature or not hmac.compare_digest(signature, expected_signature):
        return False, f"independent fact evidence {label} signature is invalid"
    return True, "fact evidence row verified"


def persisted_fact_bundle_digest(evidence_rows: list[Any], *, task_id: str, attempt: int) -> str:
    """Digest the current signed fact rows in stable order for receipt binding."""

    facts = [
        {
            **_fact_evidence_signature_payload(row),
            "signature": str(_row_value(row, "signature") or ""),
        }
        for row in evidence_rows
    ]
    facts.sort(key=lambda value: (str(value["check_id"]), str(value["evidence_id"])))
    return _sha256_bytes(
        _dumps(
            {
                "kind": "management_work_fact_bundle",
                "version": 1,
                "task_id": str(task_id),
                "attempt": int(attempt),
                "facts": facts,
            }
        ).encode("utf-8")
    )


def _serialize_evidence_row(row: Any) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    try:
        criterion_ids = json.loads(row.criterion_ids_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        criterion_ids = []
    return {
        "evidence_id": str(row.evidence_id),
        "task_id": str(row.task_id),
        "attempt": int(row.attempt or 0),
        "check_id": str(row.check_id or ""),
        "criterion_ids": criterion_ids if isinstance(criterion_ids, list) else [],
        "kind": str(row.kind or ""),
        "trust_level": str(row.trust_level or ""),
        "status": str(row.status or ""),
        "source_ref": str(row.source_ref or ""),
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "collector_version": str(row.collector_version or ""),
        "payload": payload,
        "payload_sha256": str(row.payload_sha256 or ""),
        "signature": str(row.signature or ""),
    }


def persist_fact_snapshot(
    *, task_id: str, attempt: int, snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    """Append current-attempt facts; conflicting rewrites are rejected."""

    if not verify_snapshot_signature(snapshot):
        raise ValueError("independent fact snapshot signature is invalid")
    from modstore_server.models import (
        ManagementWorkEvidence,
        ManagementWorkItem,
        get_session_factory,
    )

    sf = get_session_factory()
    with sf() as session:
        work = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .one()
        )
        if int(work.attempt_count or 0) != int(attempt):
            raise ValueError("fact snapshot attempt does not match current work attempt")
        observed_at = _parse_timestamp(snapshot.get("captured_at")) or datetime.now(timezone.utc)
        created: list[Any] = []
        for fact in snapshot.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            check_id = str(fact.get("claim_id") or fact.get("evidence_id") or "")[:128]
            if not check_id:
                continue
            payload_json = _dumps(fact)
            payload_digest = fact_payload_sha256(fact)
            existing = (
                session.query(ManagementWorkEvidence)
                .filter(
                    ManagementWorkEvidence.work_item_id == int(work.id),
                    ManagementWorkEvidence.attempt == int(attempt),
                    ManagementWorkEvidence.check_id == check_id,
                )
                .first()
            )
            if existing is not None:
                if str(existing.payload_sha256 or "") != payload_digest:
                    raise ValueError(f"evidence {check_id} already exists with a different payload")
                created.append(existing)
                continue
            source_ref = str(
                fact.get("path")
                or fact.get("url")
                or fact.get("repo_path")
                or fact.get("change_request_id")
                or fact.get("operation_id")
                or ""
            )[:512]
            verified = fact.get("verified") is True
            row = ManagementWorkEvidence(
                evidence_id=f"mwe_{uuid.uuid4().hex}",
                work_item_id=int(work.id),
                task_id=str(task_id)[:64],
                attempt=int(attempt),
                check_id=check_id,
                criterion_ids_json=_dumps(fact.get("criterion_ids") or [])[:8000],
                kind=str(fact.get("kind") or "unknown")[:64],
                trust_level="independent_observation",
                status="pass" if verified else "fail",
                source_ref=source_ref,
                observed_at=observed_at,
                expires_at=_parse_timestamp(fact.get("expires_at")),
                collector_version="v1",
                payload_json=payload_json[:500_000],
                payload_sha256=payload_digest,
                signature="",
            )
            row.signature = sign_persisted_fact_evidence(row)
            if not row.signature:
                raise ValueError("management evidence signing key is unavailable")
            session.add(row)
            created.append(row)
        session.commit()
        for row in created:
            session.refresh(row)
        return [_serialize_evidence_row(row) for row in created]


def list_fact_evidence(task_id: str, *, attempt: int | None = None) -> list[dict[str, Any]]:
    from modstore_server.models import ManagementWorkEvidence, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        query = session.query(ManagementWorkEvidence).filter(
            ManagementWorkEvidence.task_id == str(task_id)
        )
        if attempt is not None:
            query = query.filter(ManagementWorkEvidence.attempt == int(attempt))
        rows = query.order_by(
            ManagementWorkEvidence.attempt.asc(), ManagementWorkEvidence.id.asc()
        ).all()
        return [_serialize_evidence_row(row) for row in rows]


__all__ = [
    "collect_independent_fact_snapshot",
    "fact_payload_sha256",
    "list_fact_evidence",
    "persisted_fact_bundle_digest",
    "persist_fact_snapshot",
    "redact_runtime_claim",
    "sign_persisted_fact_evidence",
    "verify_persisted_fact_evidence",
    "verify_snapshot_signature",
]
