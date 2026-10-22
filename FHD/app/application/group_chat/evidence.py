"""Pure execution result normalization and evidence policy."""

from __future__ import annotations

import json
from typing import Any

from app.application.group_chat.constants import (
    _DEV_TASK_MARKERS,
    _EVIDENCE_FILE_RE,
    _EXECUTION_EVIDENCE_MARKERS,
    _FAILED_REPORT_MARKERS,
    _PURE_RESEARCH_TASK_MARKERS,
    _RESEARCH_ONLY_REPORT_MARKERS,
    _UNFINISHED_REPORT_MARKERS,
)


class ExecutionResultPolicy:
    @staticmethod
    def effective_report_status(row: dict[str, Any]) -> str:
        raw_report = row.get("payload")
        report: dict[str, Any] = dict(raw_report) if isinstance(raw_report, dict) else {}
        status = str((row or {}).get("status") or report.get("status") or "").strip().lower()
        summary = ExecutionResultPolicy.stringify_summary(
            report.get("summary") or row.get("body") or ""
        )
        success = report.get("success")
        task = ExecutionResultPolicy.stringify_summary(
            report.get("original_task") or report.get("task") or ""
        )
        missing_evidence = ExecutionResultPolicy.completed_report_lacks_required_evidence(
            task, summary, report.get("raw") if isinstance(report.get("raw"), dict) else report
        )
        raw_unfinished = ExecutionResultPolicy.summary_indicates_unfinished(
            ExecutionResultPolicy.execution_evidence_text(report)
        )
        if status in {"completed", "done"} and (
            success is False
            or ExecutionResultPolicy.summary_indicates_unfinished(summary)
            or raw_unfinished
            or missing_evidence
        ):
            return (
                "failed" if ExecutionResultPolicy.summary_indicates_failed(summary) else "blocked"
            )
        return "completed" if status == "done" else status

    @staticmethod
    def summary_indicates_unfinished(text: str) -> bool:
        if not text:
            return False
        compact = str(text).replace(" ", "")
        return any(
            marker in text or marker.replace(" ", "") in compact
            for marker in _UNFINISHED_REPORT_MARKERS
        )

    @staticmethod
    def summary_indicates_failed(text: str) -> bool:
        return any(marker in str(text or "") for marker in _FAILED_REPORT_MARKERS)

    @staticmethod
    def completed_report_lacks_required_evidence(task: str, summary: str, raw: Any = None) -> bool:
        if not ExecutionResultPolicy.task_requires_execution_evidence(task):
            return False
        evidence_text = ExecutionResultPolicy.execution_evidence_text(summary, raw)
        return not ExecutionResultPolicy.has_execution_evidence(evidence_text)

    @staticmethod
    def task_requires_execution_evidence(task: str) -> bool:
        text = str(task or "").strip().lower()
        if not text:
            return False
        has_dev_marker = any(marker.lower() in text for marker in _DEV_TASK_MARKERS)
        if not has_dev_marker:
            return False
        research_only = any(marker.lower() in text for marker in _PURE_RESEARCH_TASK_MARKERS)
        if research_only and (
            not any(
                marker in text
                for marker in (
                    "修复",
                    "实现",
                    "开发",
                    "添加",
                    "新增",
                    "更新",
                    "测试",
                    "验收",
                    "合并",
                )
            )
        ):
            return False
        return True

    @staticmethod
    def has_execution_evidence(text: str) -> bool:
        value = str(text or "")
        if not value or ExecutionResultPolicy.summary_indicates_unfinished(value):
            return False
        lower = value.lower()
        if any(marker.lower() in lower for marker in _EXECUTION_EVIDENCE_MARKERS):
            return True
        if _EVIDENCE_FILE_RE.search(value):
            return True
        return False

    @staticmethod
    def execution_evidence_text(*values: Any) -> str:
        chunks: list[str] = []

        def walk(value: Any, *, depth: int = 0) -> None:
            if value is None or depth > 6 or len(" ".join(chunks)) > 20000:
                return
            if isinstance(value, str):
                text = value.strip()
                if text:
                    chunks.append(text)
                return
            if isinstance(value, dict):
                priority = (
                    "body",
                    "summary",
                    "message",
                    "output",
                    "report",
                    "reply",
                    "error",
                    "reason",
                    "risk",
                    "assistant_message",
                    "result",
                    "data",
                )
                seen: set[str] = set()
                for key in priority:
                    if key in value:
                        seen.add(key)
                        walk(value.get(key), depth=depth + 1)
                for key, child in value.items():
                    if key not in seen:
                        walk(child, depth=depth + 1)
                return
            if isinstance(value, list | tuple):
                for item in value:
                    walk(item, depth=depth + 1)
                return
            text = ExecutionResultPolicy.stringify_summary(value)
            if text:
                chunks.append(text)

        for value in values:
            walk(value)
        return " ".join(chunks)[:20000]

    @staticmethod
    def summary_is_research_only_without_evidence(text: str) -> bool:
        value = str(text or "")
        if not value:
            return False
        if ExecutionResultPolicy.has_execution_evidence(value):
            return False
        return any(marker in value for marker in _RESEARCH_ONLY_REPORT_MARKERS)

    @staticmethod
    def relay_result_dispatch_value(result: dict[str, Any], key: str) -> str:
        for value in result.values():
            if not isinstance(value, dict):
                continue
            dispatch = value.get("dispatch")
            if isinstance(dispatch, dict) and dispatch.get(key) is not None:
                return str(dispatch.get(key) or "")
        return ""

    @staticmethod
    def execution_summary(result: dict[str, Any]) -> str:
        candidates = (
            result.get("summary"),
            result.get("message"),
            result.get("output"),
            result.get("result"),
            result.get("report"),
        )
        for value in candidates:
            text = ExecutionResultPolicy.stringify_summary(value)
            if text:
                return text[:1200]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("summary", "message", "output", "result", "report"):
                text = ExecutionResultPolicy.stringify_summary(data.get(key))
                if text:
                    return text[:1200]
        return ExecutionResultPolicy.stringify_summary(result)[:1200]

    @staticmethod
    def execution_risk(result: dict[str, Any], success: bool) -> str:
        candidates = (result.get("risk"), result.get("risks"), result.get("blocker"))
        for value in candidates:
            text = ExecutionResultPolicy.stringify_summary(value)
            if text:
                return text[:500]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("risk", "risks", "blocker"):
                text = ExecutionResultPolicy.stringify_summary(data.get(key))
                if text:
                    return text[:500]
        return "未发现阻塞。" if success else "执行失败，需负责人介入。"

    @staticmethod
    def stringify_summary(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:1200]
        except TypeError:
            return str(value)[:1200]

    @staticmethod
    def compact_result(result: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "success",
            "status",
            "message",
            "summary",
            "task_id",
            "run_id",
            "error",
            "dispatch_request_id",
            "dispatcher",
            "relay_id",
        ):
            if key in result:
                value = result[key]
                if value is None or isinstance(value, str | int | float | bool):
                    compact[key] = value
                else:
                    compact[key] = ExecutionResultPolicy.stringify_summary(value)
        return compact
