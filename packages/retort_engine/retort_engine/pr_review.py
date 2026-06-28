from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from retort_engine.absorbed_capabilities import ranked_capabilities, review_strategy_for_file
from retort_engine.absorbed_review_policy import policy_context_rank_weight, policy_context_rank_weights, policy_summary
from retort_engine.diff_extension_policy import extension_policy_for_path, extension_policy_summary, extension_review_context
from retort_engine.intent_alignment import assess_change_intent_alignment
from retort_engine.review_calibration_policy import calibration_context_rank_weight, calibration_context_rank_weights, calibration_summary
from retort_engine.review_context_bias import context_rank_weight, context_rank_weights, context_signal_strength, file_grouping_enabled, review_context_bias
from retort_engine.static_analysis_gate import scan_static_analysis_findings


SECRET_MARKERS = ("api_key", "apikey", "secret", "password", "token", "private_key")
REVIEW_STAGES = ("group_related_files", "localize_changed_hunks", "classify_risk", "reflect_before_publish", "dispatch_employee_task")
REVIEW_CONTEXTS = ("security", "tests", "ci_config", "config", "frontend", "runtime", "docs", "other")
SEVERITIES = ("high", "medium", "low", "info")
LARGE_DIFF_FILE_THRESHOLD = 8
LARGE_DIFF_HUNK_THRESHOLD = 12
LARGE_DIFF_CHAR_THRESHOLD = 30000


def review_diff(
    diff_text: str,
    *,
    max_comments: int = 20,
    previous_diff_text: str = "",
    issue_context: str = "",
    pr_body: str = "",
    employee_feedback: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    context_bias = review_context_bias()
    context_groups = group_related_files_for_review(files)
    large_diff_chunking = _large_diff_review_needed(files, diff_text)
    context_by_file = {path: str(group["context"]) for group in context_groups for path in group["files"]}
    extension_policy = extension_policy_summary([str(file_review["path"]) for file_review in files])
    static_analysis = scan_static_analysis_findings(files)
    intent_alignment = assess_change_intent_alignment(files, issue_context=issue_context, pr_body=pr_body)
    feedback_context_weights = _feedback_context_weights(employee_feedback or [])
    static_findings_by_location = {
        (str(finding.get("file") or ""), int(finding.get("line") or 0)): finding
        for finding in static_analysis.get("findings") or []
        if isinstance(finding, dict)
    }
    candidate_comments: list[dict[str, Any]] = []
    hunk_count = 0
    for file_review in files:
        file_path = str(file_review["path"])
        strategy = review_strategy_for_file(file_path)
        review_context = context_by_file.get(file_path, review_context_for_file(file_path))
        for hunk in file_review["hunks"]:
            hunk_count += 1
            hunk_comments = _static_analysis_comments(file_path, hunk, strategy, capabilities, review_context, static_findings_by_location)
            hunk_comments.extend(_review_hunk(file_path, hunk, strategy, capabilities, review_context))
            if not hunk_comments:
                hunk_comments = [_info_comment(file_path, hunk, strategy, capabilities, review_context)]
            candidate_comments.extend(hunk_comments)
    if intent_alignment.get("status") == "misaligned" and files:
        candidate_comments.append(_intent_alignment_comment(files, capabilities, context_by_file, intent_alignment))
    comments = _rank_review_comments(
        candidate_comments,
        max_comments=max_comments,
        context_groups=context_groups,
        large_diff_chunking=large_diff_chunking,
        feedback_context_weights=feedback_context_weights,
    )
    risk_counts = _risk_counts(comments)
    file_summaries = [
        _file_summary(
            str(file_review["path"]),
            review_strategy_for_file(str(file_review["path"])),
            file_review,
            [comment for comment in comments if comment.get("file") == file_review["path"]],
            context_by_file.get(str(file_review["path"]), review_context_for_file(str(file_review["path"]))),
        )
        for file_review in files
    ]
    task_groups = _build_task_groups(files, comments, context_by_file)
    summary = {
        "file_count": len(files),
        "hunk_count": hunk_count,
        "comment_count": len(comments),
        "candidate_comment_count": len(candidate_comments),
        "suppressed_comment_count": max(0, len(candidate_comments) - len(comments)),
        "publishable_comment_count": sum(1 for comment in comments if comment.get("publishable")),
        "capabilities": capabilities[:5],
        "stage_count": len(REVIEW_STAGES),
        "file_summary_count": len(file_summaries),
        "review_context_group_count": len(context_groups),
        "primary_review_contexts": [str(group["context"]) for group in context_groups[:5]],
        "extension_policy": extension_policy,
        "absorbed_file_grouping": file_grouping_enabled(),
        "absorbed_context_signal_strength": context_signal_strength(),
        "absorbed_context_rank_weights": context_rank_weights(),
        "absorbed_policy_rank_weights": policy_context_rank_weights(),
        "absorbed_review_policy": policy_summary(),
        "calibration_policy": calibration_summary(),
        "calibration_rank_weights": calibration_context_rank_weights(),
        "employee_feedback_context_weights": feedback_context_weights,
        "employee_feedback_ranked": bool(feedback_context_weights),
        "absorbed_review_source": str(context_bias.get("source") or ""),
        "risk_counts": risk_counts,
        "static_analysis": static_analysis["summary"],
        "intent_alignment": intent_alignment["summary"],
        "deep_review_pipeline": True,
        "comment_ranking_model": "severity_context_publishability_v1",
        "large_diff_chunking": large_diff_chunking,
        "large_diff_chunk_count": len(context_groups) if large_diff_chunking else (1 if files else 0),
        "large_diff_context_balancing": large_diff_chunking,
        "line_anchor_policy": "RIGHT-side added lines only; file-level fallback is marked non-publishable",
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
        "file_summaries": file_summaries,
        "comments": comments,
        "context_groups": context_groups,
        "task_groups": task_groups,
        "incremental": incremental,
        "intent_alignment": intent_alignment,
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


def review_context_for_file(path: str) -> str:
    """Classify a changed file into the review context absorbed from external projects."""
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    suffix = Path(name).suffix
    if normalized.startswith(".github/workflows/") or "/workflows/" in normalized or name in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
        return "ci_config"
    if normalized.startswith("tests/") or "/tests/" in normalized or name.startswith("test_") or name.endswith((".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx")):
        return "tests"
    extension_context = extension_review_context(path)
    if normalized.startswith("docs/") or extension_context == "docs":
        return "docs"
    if "auth" in normalized or "security" in normalized or any(marker in normalized for marker in SECRET_MARKERS):
        return "security"
    if normalized.startswith(("config/", "settings/")) or "/config/" in normalized or "/settings/" in normalized:
        return "config"
    if suffix in {".ini", ".env"} or name == ".env" or name.endswith(".env"):
        return "config"
    if suffix in {".tsx", ".jsx", ".css", ".html"} or "/frontend/" in normalized or "/ui/" in normalized:
        return "frontend"
    return extension_context


def group_related_files_for_review(files: list[dict[str, Any]] | list[str]) -> list[dict[str, Any]]:
    """Group changed files before deep review so reasoning stays focused."""
    buckets: dict[str, dict[str, Any]] = {}
    for item in files:
        file_path = str(item.get("path") if isinstance(item, dict) else item)
        if not file_path:
            continue
        context = review_context_for_file(file_path)
        bucket = buckets.setdefault(context, {"context": context, "files": [], "file_count": 0, "hunk_count": 0, "added_change_count": 0, "review_focus": _review_focus_for_context(context)})
        bucket["files"].append(file_path)
        bucket["file_count"] = int(bucket["file_count"]) + 1
        if isinstance(item, dict):
            hunks = list(item.get("hunks") or [])
            bucket["hunk_count"] = int(bucket["hunk_count"]) + len(hunks)
            bucket["added_change_count"] = int(bucket["added_change_count"]) + sum(1 for hunk in hunks for change in hunk.get("changes") or [] if change.get("type") == "add")
    return sorted(buckets.values(), key=lambda group: (REVIEW_CONTEXTS.index(str(group["context"])) if group["context"] in REVIEW_CONTEXTS else 99, str(group["context"])))


def _review_hunk(file_path: str, hunk: dict[str, Any], strategy: dict[str, Any], capabilities: list[str], review_context: str) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for change in hunk.get("changes") or []:
        if change.get("type") != "add":
            continue
        text = str(change.get("text") or "")
        lowered = text.lower()
        line = int(change.get("line") or 0)
        if _looks_like_secret_leak(text, lowered):
            comments.append(_comment(file_path, line, "high", "新增行疑似包含凭证或密钥，需要改为配置注入并加脱敏测试。", strategy, capabilities, "classify_risk", _line_risk_context(review_context, lowered), hunk=hunk, line_text=text))
        elif "todo" in lowered or "fixme" in lowered:
            comments.append(_comment(file_path, line, "medium", "新增 TODO/FIXME 会把吸收任务停在占位状态，需要落成可验证实现或任务记录。", strategy, capabilities, "reflect_before_publish", review_context, hunk=hunk, line_text=text))
        elif Path(file_path).suffix == ".py" and "print(" in lowered:
            comments.append(_comment(file_path, line, "low", "新增 print 调试输出需要换成结构化结果或日志门禁，避免产品路径噪声。", strategy, capabilities, "localize_changed_hunks", review_context, hunk=hunk, line_text=text))
        elif len(text) > 120:
            comments.append(_comment(file_path, line, "low", "新增行过长，建议拆分为可审阅的局部表达式。", strategy, capabilities, "localize_changed_hunks", review_context, hunk=hunk, line_text=text))
    return comments


def _static_analysis_comments(
    file_path: str,
    hunk: dict[str, Any],
    strategy: dict[str, Any],
    capabilities: list[str],
    review_context: str,
    findings_by_location: dict[tuple[str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for change in hunk.get("changes") or []:
        if change.get("type") != "add":
            continue
        line = int(change.get("line") or 0)
        finding = findings_by_location.get((file_path, line))
        if not finding:
            continue
        comments.append(
            _comment(
                file_path,
                line,
                str(finding.get("severity") or "medium"),
                f"{finding.get('message')} [{finding.get('rule_id')}]",
                strategy,
                ["static_analysis", *capabilities],
                "classify_risk",
                review_context,
                hunk=hunk,
                line_text=str(change.get("text") or ""),
            )
        )
    return comments


def _intent_alignment_comment(
    files: list[dict[str, Any]],
    capabilities: list[str],
    context_by_file: dict[str, str],
    intent_alignment: dict[str, Any],
) -> dict[str, Any]:
    first_file = files[0]
    file_path = str(first_file.get("path") or "")
    first_hunk = next(iter(first_file.get("hunks") or []), {})
    first_add = next((change for change in first_hunk.get("changes") or [] if change.get("type") == "add"), {})
    missing = ", ".join(str(item) for item in intent_alignment.get("missing_keywords", [])[:5])
    message = "PR 变更与 issue/目标上下文缺少关键词重合，需要先证明变更方向相关。"
    if missing:
        message += f" 未覆盖关键词：{missing}。"
    return _comment(
        file_path,
        int(first_add.get("line") or 1),
        "medium",
        message,
        review_strategy_for_file(file_path),
        ["intent_alignment", *capabilities],
        "reflect_before_publish",
        context_by_file.get(file_path, review_context_for_file(file_path)),
        hunk=first_hunk,
        line_text=str(first_add.get("text") or ""),
    )


def _line_risk_context(default_context: str, lowered_line: str) -> str:
    if default_context in {"runtime", "other"} and any(marker in lowered_line for marker in SECRET_MARKERS):
        return "security"
    return default_context


def _info_comment(file_path: str, hunk: dict[str, Any], strategy: dict[str, Any], capabilities: list[str], review_context: str) -> dict[str, Any]:
    first_add = next((change for change in hunk.get("changes") or [] if change.get("type") == "add"), {})
    line = int(first_add.get("line") or 1)
    return _comment(file_path, line, "info", "该 hunk 已按吸收的评审策略完成检查，未发现阻断问题。", strategy, capabilities, "reflect_before_publish", review_context, hunk=hunk, line_text=str(first_add.get("text") or ""))


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


def _comment(
    file_path: str,
    line: int,
    severity: str,
    message: str,
    strategy: dict[str, Any],
    capabilities: list[str],
    stage: str,
    review_context: str,
    *,
    hunk: dict[str, Any] | None = None,
    line_text: str = "",
) -> dict[str, Any]:
    publishable = bool(file_path and line > 0)
    payload = {
        "file": file_path,
        "line": line,
        "severity": severity,
        "message": message,
        "strategy": strategy.get("strategy", "semantic_review"),
        "review_context": review_context,
        "capability": (capabilities or ["review_pipeline"])[0],
        "review_stage": stage,
        "employee_actionable": severity in {"high", "medium"},
        "publishable": publishable,
        "comment_anchor": {"path": file_path, "line": line, "side": "RIGHT"} if publishable else {"path": file_path, "side": "FILE"},
        "publish_payload": {"path": file_path, "line": line, "side": "RIGHT", "body": message} if publishable else {"path": file_path, "body": message},
        "hunk_header": str((hunk or {}).get("header") or ""),
        "line_text_excerpt": line_text[:160],
    }
    return payload


def _rank_review_comments(
    comments: list[dict[str, Any]],
    *,
    max_comments: int,
    context_groups: list[dict[str, Any]] | None = None,
    large_diff_chunking: bool = False,
    feedback_context_weights: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for index, comment in enumerate(comments):
        key = (
            str(comment.get("file") or ""),
            int(comment.get("line") or 0),
            str(comment.get("severity") or ""),
            str(comment.get("message") or "")[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        scored = dict(comment)
        scored["_original_order"] = index
        scored["absorbed_context_rank_weight"] = context_rank_weight(str(scored.get("review_context") or "other"))
        scored["absorbed_policy_rank_weight"] = policy_context_rank_weight(str(scored.get("review_context") or "other"))
        scored["calibration_rank_weight"] = calibration_context_rank_weight(str(scored.get("review_context") or "other"))
        scored["feedback_rank_weight"] = int((feedback_context_weights or {}).get(str(scored.get("review_context") or "other"), 0))
        scored["rank_score"] = _comment_rank_score(scored)
        scored["rank_reason"] = _rank_reason(scored)
        deduped.append(scored)
    ordered = sorted(deduped, key=lambda item: (-int(item["rank_score"]), int(item["_original_order"])))
    selected = (
        _context_balanced_comment_selection(ordered, context_groups or [], max_comments=max_comments)
        if large_diff_chunking and context_groups
        else ordered[: max(1, max_comments)]
    )
    for position, comment in enumerate(selected, start=1):
        comment["rank_position"] = position
        comment.pop("_original_order", None)
    return selected


def _context_balanced_comment_selection(ordered: list[dict[str, Any]], context_groups: list[dict[str, Any]], *, max_comments: int) -> list[dict[str, Any]]:
    limit = max(1, max_comments)
    selected_indexes: list[int] = []
    context_order = [str(group.get("context") or "") for group in context_groups if group.get("context")]
    for context in context_order:
        if len(selected_indexes) >= limit:
            break
        for index, comment in enumerate(ordered):
            if index in selected_indexes:
                continue
            if str(comment.get("review_context") or "") == context:
                selected_indexes.append(index)
                break
    for index, _comment in enumerate(ordered):
        if len(selected_indexes) >= limit:
            break
        if index not in selected_indexes:
            selected_indexes.append(index)
    return [ordered[index] for index in selected_indexes]


def _large_diff_review_needed(files: list[dict[str, Any]], diff_text: str) -> bool:
    hunk_count = sum(len(item.get("hunks") or []) for item in files)
    return len(files) > LARGE_DIFF_FILE_THRESHOLD or hunk_count > LARGE_DIFF_HUNK_THRESHOLD or len(diff_text) > LARGE_DIFF_CHAR_THRESHOLD


def _feedback_context_weights(feedback: list[dict[str, Any]]) -> dict[str, int]:
    weights: dict[str, int] = {}
    for item in feedback:
        task = item.get("task") if isinstance(item.get("task"), dict) else {}
        dimension = str(item.get("dimension") or task.get("dimension") or "")
        status = str(item.get("status") or item.get("result") or "").lower()
        if status and status not in {"failed", "blocked", "needs_replay", "needs_attention", "missed"}:
            continue
        for context, weight in _feedback_context_map(dimension).items():
            weights[context] = max(weights.get(context, 0), weight)
    return dict(sorted(weights.items()))


def _feedback_context_map(dimension: str) -> dict[str, int]:
    return {
        "test_gate_evidence": {"tests": 120},
        "operational_readiness": {"ci_config": 100, "config": 70},
        "safety_license_gate": {"security": 110},
        "product_operability": {"frontend": 90, "docs": 60},
        "feedback_loop_closure": {"runtime": 80, "tests": 60},
        "comparative_analysis_depth": {"runtime": 70, "security": 50},
        "architecture_depth": {"runtime": 70, "ci_config": 50},
    }.get(dimension, {})


def _comment_rank_score(comment: dict[str, Any]) -> int:
    severity_weight = {"high": 400, "medium": 300, "low": 200, "info": 100}.get(str(comment.get("severity") or ""), 0)
    context_weight = {
        "security": 80,
        "ci_config": 60,
        "runtime": 55,
        "tests": 45,
        "config": 40,
        "frontend": 35,
        "docs": 20,
        "other": 10,
    }.get(str(comment.get("review_context") or "other"), 10)
    capability_weight = {"static_analysis": 45, "intent_alignment": 30}.get(str(comment.get("capability") or ""), 0)
    absorbed_context_weight = int(comment.get("absorbed_context_rank_weight") or 0)
    absorbed_policy_weight = int(comment.get("absorbed_policy_rank_weight") or 0)
    calibration_weight = int(comment.get("calibration_rank_weight") or 0)
    feedback_weight = int(comment.get("feedback_rank_weight") or 0)
    action_weight = 20 if comment.get("employee_actionable") else 0
    publish_weight = 5 if comment.get("publishable") else -20
    return severity_weight + context_weight + capability_weight + absorbed_context_weight + absorbed_policy_weight + calibration_weight + feedback_weight + action_weight + publish_weight


def _rank_reason(comment: dict[str, Any]) -> str:
    return f"{comment.get('severity')}:{comment.get('review_context')}:{comment.get('capability')}:bias={comment.get('absorbed_context_rank_weight', 0)}:policy={comment.get('absorbed_policy_rank_weight', 0)}:calibration={comment.get('calibration_rank_weight', 0)}:feedback={comment.get('feedback_rank_weight', 0)}"


def _risk_counts(comments: list[dict[str, Any]]) -> dict[str, int]:
    return {severity: sum(1 for comment in comments if comment.get("severity") == severity) for severity in SEVERITIES}


def _build_task_groups(files: list[dict[str, Any]], comments: list[dict[str, Any]], context_by_file: dict[str, str]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for file_review in files:
        file_path = str(file_review.get("path") or "")
        if not file_path:
            continue
        context = context_by_file.get(file_path, review_context_for_file(file_path))
        strategy = review_strategy_for_file(file_path)
        bucket = buckets.setdefault(
            context,
            {
                "context": context,
                "strategy": str(strategy["strategy"]),
                "files": [],
                "comment_count": 0,
                "publishable_comment_count": 0,
                "stages": list(REVIEW_STAGES),
                "risk_counts": {severity: 0 for severity in SEVERITIES},
            },
        )
        if file_path not in bucket["files"]:
            bucket["files"].append(file_path)
    for comment in comments:
        context = str(comment.get("review_context") or "other")
        file_path = str(comment.get("file") or "")
        strategy = review_strategy_for_file(file_path)
        bucket = buckets.setdefault(
            context,
            {
                "context": context,
                "strategy": str(strategy["strategy"]),
                "files": [],
                "comment_count": 0,
                "publishable_comment_count": 0,
                "stages": list(REVIEW_STAGES),
                "risk_counts": {severity: 0 for severity in SEVERITIES},
            },
        )
        if file_path and file_path not in bucket["files"]:
            bucket["files"].append(file_path)
        bucket["comment_count"] = int(bucket["comment_count"]) + 1
        bucket["publishable_comment_count"] = int(bucket["publishable_comment_count"]) + (1 if comment.get("publishable") else 0)
        severity = str(comment.get("severity") or "info")
        if severity in bucket["risk_counts"]:
            bucket["risk_counts"][severity] = int(bucket["risk_counts"][severity]) + 1
    return sorted(
        [{"context": key, **value} for key, value in buckets.items()],
        key=lambda group: (REVIEW_CONTEXTS.index(str(group["context"])) if group["context"] in REVIEW_CONTEXTS else 99, str(group["context"])),
    )


def _file_summary(file_path: str, strategy: dict[str, Any], file_review: dict[str, Any], comments: list[dict[str, Any]], review_context: str) -> dict[str, Any]:
    severity_counts = {severity: sum(1 for item in comments if item.get("severity") == severity) for severity in SEVERITIES}
    extension_policy = extension_policy_for_path(file_path)
    return {
        "file": file_path,
        "strategy": strategy.get("strategy", "semantic_review"),
        "review_context": review_context,
        "extension_policy": extension_policy,
        "hunk_count": len(file_review.get("hunks") or []),
        "comment_count": len(comments),
        "risk_counts": severity_counts,
        "stages": [{"name": stage, "status": "completed"} for stage in REVIEW_STAGES],
        "ready_for_employee_task": bool(severity_counts["high"] or severity_counts["medium"]),
    }


def _review_focus_for_context(context: str) -> str:
    return {
        "security": "secrets_permissions_and_auth_edges",
        "tests": "behavior_proof_and_regression_scope",
        "ci_config": "repeatable_gates_and_release_safety",
        "config": "runtime_contract_and_environment_drift",
        "frontend": "user_flow_and_state_surface",
        "runtime": "core_execution_path",
        "docs": "operator_evidence_and_task_clarity",
    }.get(context, "general_review")


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
