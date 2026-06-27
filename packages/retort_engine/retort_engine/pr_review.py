from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from retort_engine.absorbed_capabilities import ranked_capabilities, review_strategy_for_file


SECRET_MARKERS = ("api_key", "apikey", "secret", "password", "token", "private_key")


def review_diff(diff_text: str, *, max_comments: int = 20, previous_diff_text: str = "") -> dict[str, Any]:
    """Review a unified diff with absorbed external review capabilities."""
    raw_files = parse_unified_diff(diff_text)
    previous_files = parse_unified_diff(previous_diff_text) if previous_diff_text.strip() else []
    files, incremental = _filter_incremental_files(raw_files, previous_files) if previous_files else (
        raw_files,
        {
            "enabled": False,
            "previous_diff_supplied": False,
            "previous_added_change_count": 0,
            "current_added_change_count": _added_change_count(raw_files),
            "skipped_existing_change_count": 0,
            "reviewed_new_change_count": _added_change_count(raw_files),
        },
    )
    capabilities = [str(item.get("signal") or "") for item in ranked_capabilities()]
    comments: list[dict[str, Any]] = []
    task_groups: dict[str, dict[str, Any]] = {}
    hunk_count = 0
    for file_review in files:
        file_path = str(file_review["path"])
        strategy = review_strategy_for_file(file_path)
        group = task_groups.setdefault(str(strategy["strategy"]), {"files": [], "comment_count": 0})
        group["files"].append(file_path)
        for hunk in file_review["hunks"]:
            hunk_count += 1
            hunk_comments = _review_hunk(file_path, hunk, strategy, capabilities)
            if not hunk_comments and _remaining(max_comments, comments):
                hunk_comments = [_info_comment(file_path, hunk, strategy, capabilities)]
            for comment in hunk_comments:
                if not _remaining(max_comments, comments):
                    break
                comments.append(comment)
                group["comment_count"] = int(group["comment_count"]) + 1
    summary = {
        "file_count": len(files),
        "hunk_count": hunk_count,
        "comment_count": len(comments),
        "capabilities": capabilities[:5],
        "ready_for_employee_tasking": bool(files and comments),
        "incremental": bool(incremental.get("enabled")),
        "skipped_existing_change_count": int(incremental.get("skipped_existing_change_count") or 0),
        "reviewed_new_change_count": int(incremental.get("reviewed_new_change_count") or 0),
    }
    status = "reviewed" if files else ("no_new_changes" if raw_files and previous_files else "empty_diff")
    return {
        "status": status,
        "summary": summary,
        "files": files,
        "comments": comments,
        "task_groups": [{"strategy": key, **value} for key, value in sorted(task_groups.items())],
        "incremental": incremental,
    }


def parse_unified_diff(diff_text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    hunk: dict[str, Any] | None = None
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current = {"path": _path_from_diff_header(raw), "hunks": []}
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if raw.startswith("+++ b/"):
            current["path"] = raw[6:]
            continue
        match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if match:
            new_line = int(match.group(1))
            hunk = {"header": raw, "changes": []}
            current["hunks"].append(hunk)
            continue
        if hunk is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            hunk["changes"].append({"type": "add", "line": new_line, "text": raw[1:]})
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            hunk["changes"].append({"type": "delete", "line": None, "text": raw[1:]})
        else:
            hunk["changes"].append({"type": "context", "line": new_line, "text": raw[1:] if raw.startswith(" ") else raw})
            new_line += 1
    return [item for item in files if item["hunks"]]


def _review_hunk(file_path: str, hunk: dict[str, Any], strategy: dict[str, Any], capabilities: list[str]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for change in hunk.get("changes") or []:
        if change.get("type") != "add":
            continue
        text = str(change.get("text") or "")
        lowered = text.lower()
        line = int(change.get("line") or 0)
        if _looks_like_secret_leak(text, lowered):
            comments.append(_comment(file_path, line, "high", "新增行疑似包含凭证或密钥，需要改为配置注入并加脱敏测试。", strategy, capabilities))
        elif "todo" in lowered or "fixme" in lowered:
            comments.append(_comment(file_path, line, "medium", "新增 TODO/FIXME 会把吸收任务停在占位状态，需要落成可验证实现或任务记录。", strategy, capabilities))
        elif Path(file_path).suffix == ".py" and "print(" in lowered:
            comments.append(_comment(file_path, line, "low", "新增 print 调试输出需要换成结构化结果或日志门禁，避免产品路径噪声。", strategy, capabilities))
        elif len(text) > 120:
            comments.append(_comment(file_path, line, "low", "新增行过长，建议拆分为可审阅的局部表达式。", strategy, capabilities))
    return comments


def _info_comment(file_path: str, hunk: dict[str, Any], strategy: dict[str, Any], capabilities: list[str]) -> dict[str, Any]:
    first_add = next((change for change in hunk.get("changes") or [] if change.get("type") == "add"), {})
    line = int(first_add.get("line") or 1)
    return _comment(file_path, line, "info", "该 hunk 已按吸收的评审策略完成检查，未发现阻断问题。", strategy, capabilities)


def _looks_like_secret_leak(text: str, lowered: str) -> bool:
    if not any(marker in lowered for marker in SECRET_MARKERS):
        return False
    stripped = text.strip()
    documentation_markers = ("#", '"""', "'''", "* ", "- ", "``")
    if stripped.startswith(documentation_markers) or "``" in stripped:
        return False
    safe_markers = (
        "resolve_api_key",
        "platform-key",
        "fake",
        "mock",
        "dummy",
        "redacted",
        "example",
        "token_redacted",
        "monkeypatch",
    )
    if any(marker in lowered for marker in safe_markers):
        return False
    assignment = re.search(r"(?i)\b[A-Z0-9_]*(api[_-]?key|apikey|secret|password|token|private_key)[A-Z0-9_]*\b[^=\n:]{0,40}[:=]\s*['\"][^'\"]{6,}", text)
    authorization = re.search(r"(?i)\b(authorization|bearer)\b.{0,20}['\"]?[A-Za-z0-9_\-]{16,}", text)
    return bool(assignment or authorization)


def _comment(file_path: str, line: int, severity: str, message: str, strategy: dict[str, Any], capabilities: list[str]) -> dict[str, Any]:
    return {
        "file": file_path,
        "line": line,
        "severity": severity,
        "message": message,
        "strategy": strategy.get("strategy", "semantic_review"),
        "capability": (capabilities or ["review_pipeline"])[0],
    }


def _path_from_diff_header(header: str) -> str:
    parts = header.split()
    if len(parts) >= 4 and parts[3].startswith("b/"):
        return parts[3][2:]
    return parts[-1].removeprefix("b/") if parts else ""


def _remaining(max_comments: int, comments: list[dict[str, Any]]) -> bool:
    return len(comments) < max(1, max_comments)


def _filter_incremental_files(files: list[dict[str, Any]], previous_files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    previous_counts = Counter(_added_change_keys(previous_files))
    skipped = 0
    reviewed = 0
    filtered: list[dict[str, Any]] = []
    for file_review in files:
        file_path = str(file_review.get("path") or "")
        kept_hunks: list[dict[str, Any]] = []
        for hunk in file_review.get("hunks") or []:
            kept_changes: list[dict[str, Any]] = []
            hunk_has_new_addition = False
            for change in hunk.get("changes") or []:
                if change.get("type") != "add":
                    kept_changes.append(change)
                    continue
                key = _added_change_key(file_path, change)
                if previous_counts[key] > 0:
                    previous_counts[key] -= 1
                    skipped += 1
                    continue
                reviewed += 1
                hunk_has_new_addition = True
                kept_changes.append(change)
            if hunk_has_new_addition:
                kept_hunks.append({**hunk, "changes": kept_changes})
        if kept_hunks:
            filtered.append({**file_review, "hunks": kept_hunks})
    return filtered, {
        "enabled": True,
        "previous_diff_supplied": True,
        "previous_added_change_count": _added_change_count(previous_files),
        "current_added_change_count": _added_change_count(files),
        "skipped_existing_change_count": skipped,
        "reviewed_new_change_count": reviewed,
    }


def _added_change_keys(files: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for file_review in files:
        file_path = str(file_review.get("path") or "")
        for hunk in file_review.get("hunks") or []:
            for change in hunk.get("changes") or []:
                if change.get("type") == "add":
                    keys.append(_added_change_key(file_path, change))
    return keys


def _added_change_count(files: list[dict[str, Any]]) -> int:
    return len(_added_change_keys(files))


def _added_change_key(file_path: str, change: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", str(change.get("text") or "").strip())
    return f"{file_path}\0{text}"
