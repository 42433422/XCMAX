"""Message formatting mixin for AiGroupChatFormattingMixin."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, cast

from app.application.group_chat.constants import (
    _BROKEN_MARKDOWN_LINK_RE,
    _DEV_TASK_MARKERS,
    _EVIDENCE_FILE_RE,
    _EXECUTION_EVIDENCE_MARKERS,
    _FAILED_REPORT_MARKERS,
    _MARKDOWN_LINK_RE,
    _PURE_RESEARCH_TASK_MARKERS,
    _RESEARCH_ONLY_REPORT_MARKERS,
    _TEMP_PATH_RE,
    _UNFINISHED_REPORT_MARKERS,
    CONTEXT_TURNS,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class AiGroupChatFormattingMixin:
    if TYPE_CHECKING:

        @staticmethod
        def _chat_friendly_summary(
            value: str, limit: int, *, include_detail_note: bool = True
        ) -> str:
            raise NotImplementedError

    @staticmethod
    def _clean_chat_summary_line(line: str) -> str:
        text = _TEMP_PATH_RE.sub("临时执行工作区", str(line or ""))
        text = _MARKDOWN_LINK_RE.sub(r"\1", text)
        text = _BROKEN_MARKDOWN_LINK_RE.sub(r"\1", text)
        for token in ("**", "__", "`"):
            text = text.replace(token, "")
        return " ".join(text.split()).strip("；，。 ")

    @classmethod
    def _relay_result_risk(
        cls,
        *,
        result: dict[str, Any],
        success: bool,
        task_id: str,
        dispatcher: str,
    ) -> str:
        for value in (result.get("risk"), result.get("error"), result.get("reason")):
            text = cls._stringify_summary(value)
            if text:
                return text[:500]
        if not success:
            text = cls._stringify_summary(result.get("reply"))
            if text:
                return cast(
                    "str", cls._chat_friendly_summary(text, limit=500, include_detail_note=False)
                )
        parts: list[str] = []
        if success:
            parts.append("未发现阻塞")
        else:
            parts.append("中继任务未成功完成")
        if dispatcher:
            parts.append(f"执行端：{dispatcher}")
        if task_id:
            parts.append(f"中继任务：{task_id}")
        return "；".join(parts) + "。"

    @classmethod
    def _effective_report_status(cls, row: dict[str, Any]) -> str:
        raw_report = row.get("payload")
        report: dict[str, Any] = dict(raw_report) if isinstance(raw_report, dict) else {}
        status = str((row or {}).get("status") or report.get("status") or "").strip().lower()
        summary = cls._stringify_summary(report.get("summary") or row.get("body") or "")
        success = report.get("success")
        task = cls._stringify_summary(report.get("original_task") or report.get("task") or "")
        missing_evidence = cls._completed_report_lacks_required_evidence(
            task,
            summary,
            report.get("raw") if isinstance(report.get("raw"), dict) else report,
        )
        raw_unfinished = cls._summary_indicates_unfinished(cls._execution_evidence_text(report))
        if status in {"completed", "done"} and (
            success is False
            or cls._summary_indicates_unfinished(summary)
            or raw_unfinished
            or missing_evidence
        ):
            return "failed" if cls._summary_indicates_failed(summary) else "blocked"
        return "completed" if status == "done" else status

    @staticmethod
    def _summary_indicates_unfinished(text: str) -> bool:
        if not text:
            return False
        compact = str(text).replace(" ", "")
        return any(
            marker in text or marker.replace(" ", "") in compact
            for marker in _UNFINISHED_REPORT_MARKERS
        )

    @staticmethod
    def _summary_indicates_failed(text: str) -> bool:
        return any(marker in str(text or "") for marker in _FAILED_REPORT_MARKERS)

    @classmethod
    def _completed_report_lacks_required_evidence(
        cls,
        task: str,
        summary: str,
        raw: Any = None,
    ) -> bool:
        if not cls._task_requires_execution_evidence(task):
            return False
        evidence_text = cls._execution_evidence_text(summary, raw)
        return not cls._has_execution_evidence(evidence_text)

    @staticmethod
    def _task_requires_execution_evidence(task: str) -> bool:
        text = str(task or "").strip().lower()
        if not text:
            return False
        has_dev_marker = any(marker.lower() in text for marker in _DEV_TASK_MARKERS)
        if not has_dev_marker:
            return False
        research_only = any(marker.lower() in text for marker in _PURE_RESEARCH_TASK_MARKERS)
        if research_only and not any(
            marker in text
            for marker in ("修复", "实现", "开发", "添加", "新增", "更新", "测试", "验收", "合并")
        ):
            return False
        return True

    @classmethod
    def _has_execution_evidence(cls, text: str) -> bool:
        value = str(text or "")
        if not value or cls._summary_indicates_unfinished(value):
            return False
        lower = value.lower()
        if any(marker.lower() in lower for marker in _EXECUTION_EVIDENCE_MARKERS):
            return True
        if _EVIDENCE_FILE_RE.search(value):
            return True
        return False

    @classmethod
    def _execution_evidence_text(cls, *values: Any) -> str:
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
            text = cls._stringify_summary(value)
            if text:
                chunks.append(text)

        for value in values:
            walk(value)
        return " ".join(chunks)[:20000]

    @classmethod
    def _summary_is_research_only_without_evidence(cls, text: str) -> bool:
        value = str(text or "")
        if not value:
            return False
        if cls._has_execution_evidence(value):
            return False
        return any(marker in value for marker in _RESEARCH_ONLY_REPORT_MARKERS)

    @staticmethod
    def _relay_result_dispatch_value(result: dict[str, Any], key: str) -> str:
        for value in result.values():
            if not isinstance(value, dict):
                continue
            dispatch = value.get("dispatch")
            if isinstance(dispatch, dict) and dispatch.get(key) is not None:
                return str(dispatch.get(key) or "")
        return ""

    @staticmethod
    def _execution_summary(result: dict[str, Any]) -> str:
        candidates = (
            result.get("summary"),
            result.get("message"),
            result.get("output"),
            result.get("result"),
            result.get("report"),
        )
        for value in candidates:
            text = AiGroupChatFormattingMixin._stringify_summary(value)
            if text:
                return text[:1200]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("summary", "message", "output", "result", "report"):
                text = AiGroupChatFormattingMixin._stringify_summary(data.get(key))
                if text:
                    return text[:1200]
        return AiGroupChatFormattingMixin._stringify_summary(result)[:1200]

    @staticmethod
    def _execution_risk(result: dict[str, Any], success: bool) -> str:
        candidates = (result.get("risk"), result.get("risks"), result.get("blocker"))
        for value in candidates:
            text = AiGroupChatFormattingMixin._stringify_summary(value)
            if text:
                return text[:500]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("risk", "risks", "blocker"):
                text = AiGroupChatFormattingMixin._stringify_summary(data.get(key))
                if text:
                    return text[:500]
        return "未发现阻塞。" if success else "执行失败，需负责人介入。"

    @staticmethod
    def _stringify_summary(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:1200]
        except TypeError:  # noqa: BLE001 - untrusted summary serialization fallback
            return str(value)[:1200]

    @staticmethod
    def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
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
                    compact[key] = AiGroupChatFormattingMixin._stringify_summary(value)
        return compact

    async def _super_employee_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        """超级员工群聊回复：调用专用 invoke 通道（CLI 直答 / Para 派工）。

        超级员工的回复结果会写入其自身会话的 messages.jsonl（由 invoke 内部完成），
        群聊消息则写入 ai_group_chat/messages.jsonl（由调用方 post_message 完成），
        两者独立持久化，互不干扰。
        """
        from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
        from app.application.codex_super_employee_service import CodexSuperEmployeeService
        from app.application.cursor_super_employee_service import CursorSuperEmployeeService
        from app.application.trae_super_employee_service import TraeSuperEmployeeService

        employee_id = str(member.get("employee_id") or "")
        me = str(member.get("name") or employee_id)
        group_name = str(group.get("name") or "AI 群聊")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        prompt = (
            f"你是群聊「{group_name}」里的成员「{me}」。\n"
            f"群成员有：{roster}。\n"
            f"【群最近对话】\n{transcript}\n\n"
            f"请以「{me}」身份回应最新这条消息，用一两句话简洁回应。"
        )
        try:
            service: Any
            if employee_id == "codex-super-employee":
                service = CodexSuperEmployeeService()
            elif employee_id == "cursor-super-employee":
                service = CursorSuperEmployeeService()
            elif employee_id == "trae-super-employee":
                service = TraeSuperEmployeeService()
            else:
                service = ClaudeSuperEmployeeService()
            # 群聊场景强制走 CLI 直答（mode=chat），避免 transcript 里包含
            # "修改/测试/调用"等 _TASK_MARKERS 词被误判为任务走派工流程，
            # 导致本机无 Para 时只返回"思考中..."而永远等不到答案。
            # 阻塞的 CLI 子进程调用放到工作线程跑，避免冻住事件循环、
            # 导致同一服务上其它群聊/接口在本次「思考」期间全部卡住。
            result = await asyncio.to_thread(
                service.invoke,
                user_id=int(user_id),
                message=prompt,
                context={"mode": "chat"},
            )
            assistant = result.get("assistant_message") or {}
            body = str(assistant.get("body") or "").strip()
            if body:
                return body
            return f"（{me} 暂时无法回应）"
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"
