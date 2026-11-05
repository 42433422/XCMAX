"""Notification payloads emitted after approval transactions release their lock."""

from __future__ import annotations

from typing import Any


def completed_workflow_notification(request: Any) -> tuple[int, str, str, dict[str, str]]:
    return (
        int(request.applicant_id),
        "审批进度更新",
        f"《{request.title or request.request_no}》AI 工作流已执行完成",
        {"route": f"/app/approval/{request.id}", "request_id": str(request.id)},
    )
