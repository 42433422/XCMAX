"""Bind a Windows verification child to the Mac executor's exact source receipt."""

import json
import re

from modstore_server.mac_control_store import accept, digest, event


def schedule_windows_verification(db, parent, raw):
    request = json.loads(parent.request_json)
    if not request.get("verify_on_windows") or request.get("target") != "mac":
        return ""
    evidence = None
    for report in raw.get("reports", []):
        if not report.get("applied") or report.get("status") != "completed":
            continue
        try:
            candidate = json.loads(report.get("report", ""))
        except (ValueError, TypeError):
            continue
        if (
            isinstance(candidate, dict)
            and candidate.get("source") == "executor_git_readback"
            and candidate.get("pushed") is True
            and re.fullmatch(r"[0-9a-f]{40}", str(candidate.get("commit_sha", "")))
            and re.fullmatch(r"[0-9a-f]{64}", str(candidate.get("archive_sha256", "")))
        ):
            evidence = candidate
            break
    if evidence is None:
        return "waiting_for_pushed_commit_and_source_archive_receipt"
    sha, archive = evidence["commit_sha"], evidence["archive_sha256"]
    child_request = {
        "message": (
            "在 Windows 隔离工作区验证上游任务，不使用生产业务数据。"
            f"必须先确认 HEAD={sha}，运行 "
            f"node FHD/scripts/autonomy/runtime_tools/control_git_handoff.mjs {sha} {archive}；"
            "校验失败立即停止。通过后执行与原目标相关的 Windows 检查，"
            "报告实际命令、结果与限制，禁止用测试替代客户安装或业务验收。原目标："
            + request["message"]
        ),
        "target": "windows",
        "mode": "review",
        "tool": request.get("tool", "codex"),
        "source_sha": sha,
        "source": "mac_handoff",
        "parent_task_id": parent.id,
        "source_archive_sha256": archive,
        "ticket_id": request.get("ticket_id"),
        "customer_id": request.get("customer_id"),
    }
    child = accept(
        db,
        actor=parent.actor,
        key=digest([parent.id, "windows", sha, archive]),
        request=child_request,
    )
    event(db, parent, "windows_verification_queued", {"child_task_id": child.id, **evidence})
    db.commit()
    return ""
