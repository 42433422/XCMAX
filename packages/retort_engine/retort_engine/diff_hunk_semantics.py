from __future__ import annotations

import re
from typing import Any


CONTROL_FLOW_MARKERS = ("except ", "try:", "subprocess.", "requests.", "thread", "process", "timeout", "publish", "create_review")
VALIDATION_MARKERS = ("validate", "sanitize", "permission", "auth", "token", "secret", "assert", "raise", "check")
WRITE_PERMISSION_MARKERS = ("pull_request_target", "pull-requests: write", "contents: write", "issues: write")


def analyze_hunk_semantics(file_path: str, hunk: dict[str, Any], review_context: str) -> dict[str, Any]:
    """Classify behavior changes by comparing added lines with deleted/context lines inside one diff hunk."""
    changes = [item for item in hunk.get("changes") or [] if isinstance(item, dict)]
    added = [_line(item) for item in changes if item.get("type") == "add"]
    deleted = [_line(item) for item in changes if item.get("type") == "delete"]
    context = [_line(item) for item in changes if item.get("type") == "context"]
    findings: list[dict[str, Any]] = []
    findings.extend(_permission_broadening(file_path, added, context, review_context))
    findings.extend(_validation_regression(file_path, added, deleted, context, review_context))
    findings.extend(_test_weakening(file_path, added, deleted, review_context))
    findings.extend(_crash_or_timeout_regression(file_path, added, context, review_context))
    return {
        "status": "semantic_findings" if findings else "no_semantic_regression",
        "file": file_path,
        "hunk_header": str(hunk.get("header") or ""),
        "review_context": review_context,
        "added_line_count": len(added),
        "deleted_line_count": len(deleted),
        "context_line_count": len(context),
        "finding_count": len(findings),
        "max_confidence": max([int(item.get("confidence") or 0) for item in findings] or [0]),
        "findings": findings,
    }


def summarize_hunk_semantics(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    findings = [finding for item in analyses for finding in item.get("findings") or [] if isinstance(finding, dict)]
    types = sorted({str(item.get("type") or "") for item in findings if item.get("type")})
    contexts = sorted({str(item.get("review_context") or "") for item in findings if item.get("review_context")})
    return {
        "status": "active" if findings else "no_findings",
        "hunk_analysis_count": len(analyses),
        "finding_count": len(findings),
        "finding_types": types,
        "review_contexts": contexts,
        "max_confidence": max([int(item.get("confidence") or 0) for item in findings] or [0]),
        "core_behavior_active": bool(findings),
    }


def _permission_broadening(file_path: str, added: list[dict[str, Any]], context: list[dict[str, Any]], review_context: str) -> list[dict[str, Any]]:
    joined_added = "\n".join(item["lowered"] for item in added)
    joined_context = "\n".join(item["lowered"] for item in context)
    if not any(marker in joined_added for marker in WRITE_PERMISSION_MARKERS):
        return []
    if "permissions:" not in joined_added and "permissions:" not in joined_context:
        return []
    line = _first_line(added, WRITE_PERMISSION_MARKERS)
    return [
        _finding(
            "permission_broadening",
            "high",
            "新增 PR 写权限或 pull_request_target，需要证明只在受信任分支发布并有回滚门禁。",
            line,
            review_context if review_context != "other" else "ci_config",
            92,
            added_evidence=_matching_texts(added, WRITE_PERMISSION_MARKERS),
        )
    ]


def _validation_regression(
    file_path: str,
    added: list[dict[str, Any]],
    deleted: list[dict[str, Any]],
    context: list[dict[str, Any]],
    review_context: str,
) -> list[dict[str, Any]]:
    if review_context == "tests" or "test" in file_path.replace("\\", "/").lower():
        return []
    deleted_validation = [item for item in deleted if any(marker in item["lowered"] for marker in VALIDATION_MARKERS)]
    added_bypass = [
        item
        for item in added
        if re.search(r"\b(pass|return\s+true|return\s+none|continue)\b", item["lowered"])
        or "create_review" in item["lowered"]
        or "publish(" in item["lowered"]
    ]
    if not deleted_validation or not added_bypass:
        return []
    line = int(added_bypass[0]["line"] or 0)
    context_hint = _semantic_context(review_context, file_path, context)
    return [
        _finding(
            "validation_regression",
            "high",
            "同一 hunk 删除校验/断言后新增发布或放行路径，需要恢复校验并补行为测试。",
            line,
            context_hint,
            95,
            added_evidence=[item["text"] for item in added_bypass[:3]],
            removed_evidence=[item["text"] for item in deleted_validation[:3]],
        )
    ]


def _test_weakening(file_path: str, added: list[dict[str, Any]], deleted: list[dict[str, Any]], review_context: str) -> list[dict[str, Any]]:
    normalized = file_path.replace("\\", "/").lower()
    if review_context != "tests" and "test" not in normalized:
        return []
    removed_asserts = [item for item in deleted if "assert" in item["lowered"] or "expect(" in item["lowered"]]
    added_weakening = [item for item in added if re.search(r"\b(pass|return\s+true)\b", item["lowered"]) or "skip" in item["lowered"]]
    if not removed_asserts or not added_weakening:
        return []
    return [
        _finding(
            "test_weakening",
            "high",
            "测试 hunk 删除断言后改成跳过或恒真，会让吸收证明失效。",
            int(added_weakening[0]["line"] or 0),
            "tests",
            94,
            added_evidence=[item["text"] for item in added_weakening[:3]],
            removed_evidence=[item["text"] for item in removed_asserts[:3]],
        )
    ]


def _crash_or_timeout_regression(file_path: str, added: list[dict[str, Any]], context: list[dict[str, Any]], review_context: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in added:
        lowered = item["lowered"]
        if ("subprocess.run" in lowered or "requests." in lowered) and "timeout" not in lowered:
            findings.append(
                _finding(
                    "missing_timeout",
                    "medium",
                    "新增外部进程或网络调用没有 timeout，会让员工执行链路卡死。",
                    int(item["line"] or 0),
                    _semantic_context(review_context, file_path, context),
                    86,
                    added_evidence=[item["text"]],
                )
            )
        if "except exception" in lowered:
            pass_like = any(re.search(r"\b(pass|return\s+none|continue)\b", later["lowered"]) for later in added)
            if pass_like:
                findings.append(
                    _finding(
                        "swallowed_exception",
                        "medium",
                        "异常被吞掉会隐藏吸收失败，需要记录错误并触发降级或回滚。",
                        int(item["line"] or 0),
                        _semantic_context(review_context, file_path, context),
                        88,
                        added_evidence=[item["text"]],
                    )
                )
    return findings[:2]


def _semantic_context(review_context: str, file_path: str, context: list[dict[str, Any]]) -> str:
    if review_context and review_context != "other":
        return review_context
    normalized = file_path.replace("\\", "/").lower()
    joined_context = "\n".join(item["lowered"] for item in context)
    if "workflow" in normalized or "permissions:" in joined_context:
        return "ci_config"
    if "test" in normalized:
        return "tests"
    if any(marker in normalized or marker in joined_context for marker in ("auth", "token", "secret", "permission")):
        return "security"
    if any(marker in joined_context for marker in CONTROL_FLOW_MARKERS):
        return "runtime"
    return review_context or "other"


def _finding(
    finding_type: str,
    severity: str,
    message: str,
    line: int,
    review_context: str,
    confidence: int,
    *,
    added_evidence: list[str] | None = None,
    removed_evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": finding_type,
        "severity": severity,
        "message": message,
        "line": line,
        "review_context": review_context,
        "confidence": confidence,
        "added_evidence": added_evidence or [],
        "removed_evidence": removed_evidence or [],
    }


def _line(change: dict[str, Any]) -> dict[str, Any]:
    text = str(change.get("text") or "")
    return {"line": int(change.get("line") or 0), "text": text, "lowered": text.lower()}


def _first_line(lines: list[dict[str, Any]], markers: tuple[str, ...]) -> int:
    for item in lines:
        if any(marker in item["lowered"] for marker in markers):
            return int(item["line"] or 0)
    return int(lines[0]["line"] or 0) if lines else 0


def _matching_texts(lines: list[dict[str, Any]], markers: tuple[str, ...]) -> list[str]:
    return [item["text"] for item in lines if any(marker in item["lowered"] for marker in markers)][:4]
