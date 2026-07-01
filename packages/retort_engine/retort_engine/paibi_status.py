from __future__ import annotations

import json
from typing import Any

from retort_engine.llm_schema import RETORT_SCORE_DIMENSIONS


def summarize_task(task_body: dict[str, Any]) -> dict[str, Any]:
    task = task_body.get("task") if isinstance(task_body.get("task"), dict) else task_body
    subtasks = task.get("subTasks") or task.get("subtasks") or []
    normalized_subtasks: list[dict[str, Any]] = []
    logs: list[str] = []
    if isinstance(subtasks, list):
        for subtask in subtasks:
            if not isinstance(subtask, dict):
                continue
            subtask_logs = subtask.get("logs") if isinstance(subtask.get("logs"), list) else []
            for row in subtask_logs:
                if isinstance(row, dict) and str(row.get("content") or "").strip():
                    logs.append(str(row.get("content") or "").strip())
            normalized_subtasks.append(
                {
                    "id": str(subtask.get("id") or ""),
                    "title": str(subtask.get("title") or ""),
                    "status": str(subtask.get("status") or ""),
                    "blocked": bool(subtask.get("blocked")),
                    "last_error": str(subtask.get("last_error") or subtask.get("lastError") or ""),
                    "depends_on": [str(item) for item in (subtask.get("depends_on") or subtask.get("dependsOn") or [])],
                    "progress": subtask.get("progress") or 0,
                    "device_name": str(subtask.get("device_name") or ""),
                    "branch_name": str(subtask.get("branch_name") or ""),
                    "log_count": len(subtask_logs),
                }
            )
    excerpt = "\n".join(logs)[-8000:]
    json_result = _extract_last_json_object(excerpt)
    result = {
        "provider": "paibi",
        "task_id": str(task.get("id") or ""),
        "status": str(task.get("status") or ""),
        "subtasks": normalized_subtasks,
        "logs_excerpt": excerpt,
        "json_result": json_result,
        "scores": normalize_llm_scores(json_result),
    }
    result["blockers"] = analyze_task_blockers(result)
    result["unblock_tasks"] = unblock_tasks_from_blockers(result["blockers"])
    return result


def parallel_summary(status: dict[str, Any]) -> dict[str, Any]:
    subtasks = status.get("subtasks") if isinstance(status.get("subtasks"), list) else []
    counts: dict[str, int] = {}
    devices: set[str] = set()
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        sub_status = str(subtask.get("status") or "unknown")
        counts[sub_status] = counts.get(sub_status, 0) + 1
        if subtask.get("device_name"):
            devices.add(str(subtask.get("device_name")))
    return {"subtask_count": len(subtasks), "status_counts": counts, "device_count": len(devices), "has_blockers": bool(analyze_task_blockers(status))}


def analyze_task_blockers(status: dict[str, Any]) -> list[dict[str, Any]]:
    subtasks = status.get("subtasks") if isinstance(status.get("subtasks"), list) else []
    logs = str(status.get("logs_excerpt") or "")
    blockers: list[dict[str, Any]] = []
    if _is_stale_dispatch(status, subtasks, logs):
        blockers.append(
            {
                "kind": "stale_dispatch",
                "action": "retry_with_idle_tool_slot",
                "task_id": status.get("task_id"),
                "status": status.get("status"),
                "subtask_count": len(subtasks),
                "reason": "Para task stayed at zero progress while logs only show dispatch waiting.",
            }
        )
    pending_without_deps = [
        subtask
        for subtask in subtasks
        if isinstance(subtask, dict) and str(subtask.get("status") or "") == "pending" and not (subtask.get("depends_on") or [])
    ]
    if pending_without_deps and ("当前不可用" in logs or "执行器忙" in logs or "busy" in logs.lower()):
        blockers.append(
            {
                "kind": "worker_capacity_limit",
                "action": "add_worker_or_wait_running_slot",
                "task_id": status.get("task_id"),
                "status": status.get("status"),
                "pending_subtask_count": len(pending_without_deps),
            }
        )
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        sub_status = str(subtask.get("status") or "")
        blocked = bool(subtask.get("blocked")) or sub_status in {"failed", "blocked"}
        if not blocked:
            continue
        text = " ".join([sub_status, str(subtask.get("last_error") or ""), logs]).lower()
        kind = "subtask_blocked"
        action = "inspect_logs_and_retry"
        if "git clone --no-hardlinks" in text or "fetch-pack" in text or "tmp_pack" in text:
            kind = "workspace_clone_race"
            action = "retry_serial_or_unique_workspace"
        elif "未在线" in text or "offline" in text:
            kind = "device_offline"
            action = "start_or_replace_device"
        elif "缺少自动改码执行器" in text or "not_installed" in text or "executor" in text:
            kind = "executor_missing"
            action = "install_or_select_executor"
        elif "depends" in text or "前置" in text:
            kind = "dependency_wait"
            action = "complete_or_remove_dependency"
        elif "timeout" in text or "超时" in text:
            kind = "timeout"
            action = "split_smaller_or_retry"
        blockers.append(
            {
                "kind": kind,
                "action": action,
                "subtask_id": subtask.get("id"),
                "title": subtask.get("title"),
                "status": sub_status,
                "device_name": subtask.get("device_name"),
                "last_error": subtask.get("last_error"),
            }
        )
    if status.get("status") in {"failed", "blocked"} and not blockers:
        blockers.append({"kind": "task_blocked", "action": "inspect_task_logs_and_retry", "task_id": status.get("task_id"), "status": status.get("status")})
    return blockers


def unblock_tasks_from_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, str]]:
    tasks = []
    for index, blocker in enumerate(blockers, start=1):
        kind = str(blocker.get("kind") or "subtask_blocked")
        subtask = str(blocker.get("subtask_id") or blocker.get("task_id") or "")
        if kind == "device_offline":
            title = "恢复或替换离线 Para 工作设备"
            acceptance = f"子任务 {subtask} 所在设备在线，或任务已迁移到在线 Codex 设备。"
            owner = "runtime"
        elif kind == "executor_missing":
            title = "安装或切换 Codex 执行器"
            acceptance = f"子任务 {subtask} 的目标设备 executorReady=true，重新派发后进入 running/completed。"
            owner = "runtime"
        elif kind == "dependency_wait":
            title = "解除无效前置依赖"
            acceptance = f"子任务 {subtask} 的 depends_on 已完成或被移除，调度器可派发。"
            owner = "scheduler"
        elif kind == "timeout":
            title = "拆小并重试超时子任务"
            acceptance = f"子任务 {subtask} 被拆成更小 panel，并在超时窗口内返回 JSON。"
            owner = "scheduler"
        elif kind == "worker_capacity_limit":
            title = "增加 Para worker 或等待执行槽位"
            acceptance = "pending 子任务进入 running/completed，或被迁移到其它在线 Codex 设备。"
            owner = "runtime"
        elif kind == "workspace_clone_race":
            title = "串行重试或隔离 Para 工作区"
            acceptance = f"子任务 {subtask} 不再共享并发 clone 目录，重试后不再出现 tmp_pack/fetch-pack 错误。"
            owner = "scheduler"
        elif kind == "stale_dispatch":
            title = "跳过卡住工具槽位并重新派发评审"
            acceptance = f"原任务 {subtask} 不再被当成可用执行证据，新任务已派发到 idle/ready 工具槽位并产生进度或分数。"
            owner = "scheduler"
        else:
            title = "诊断并重试阻塞子任务"
            acceptance = f"子任务 {subtask} 的 last_error 已归因，重试后不再处于 failed/blocked。"
            owner = "runtime"
        tasks.append(
            {
                "title": title,
                "owner_hint": owner,
                "acceptance": acceptance,
                "evidence_required": "Para task status, subtask logs, retry result",
                "blocker_kind": kind,
                "task_id": f"para-unblock-{index:02d}",
            }
        )
    return tasks


def _is_stale_dispatch(status: dict[str, Any], subtasks: list[Any], logs: str) -> bool:
    if str(status.get("status") or "") not in {"running", "pending"}:
        return False
    if status.get("scores") or status.get("json_result"):
        return False
    if not subtasks:
        return False
    lower_logs = logs.lower()
    dispatch_waiting = any(
        marker in logs or marker in lower_logs
        for marker in (
            "等待派发",
            "等待调度",
            "未派发",
            "waiting dispatch",
            "waiting for dispatch",
            "not dispatched",
        )
    )
    if not dispatch_waiting:
        return False
    unfinished = [subtask for subtask in subtasks if isinstance(subtask, dict) and str(subtask.get("status") or "") not in {"completed", "failed", "blocked"}]
    if not unfinished:
        return False
    return all(_progress_value(subtask.get("progress")) <= 0 for subtask in unfinished)


def _progress_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _extract_last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None
    scored: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            if isinstance(value.get("scores"), list) or "score_suggestion" in value:
                scored.append(value)
            best = value
    return scored[-1] if scored else best


def normalize_llm_scores(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_scores = payload.get("scores")
    scores: list[dict[str, Any]] = []
    if isinstance(raw_scores, list):
        for item in raw_scores:
            if not isinstance(item, dict):
                continue
            dimension = str(item.get("dimension") or "").strip()
            if dimension not in RETORT_SCORE_DIMENSIONS:
                continue
            try:
                value = max(0.0, min(100.0, float(item.get("value"))))
            except (TypeError, ValueError):
                continue
            evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
            scores.append(
                {
                    "dimension": dimension,
                    "value": round(value, 1),
                    "reason": str(item.get("reason") or "LLM score from Retort scoring prompt."),
                    "evidence": [str(row) for row in evidence],
                }
            )
    existing = {score["dimension"] for score in scores}
    if "calibrated_overall" not in existing:
        suggestion = payload.get("score_suggestion")
        try:
            value = max(0.0, min(100.0, float(suggestion)))
        except (TypeError, ValueError):
            value = -1.0
        if value >= 0:
            scores.append(
                {
                    "dimension": "calibrated_overall",
                    "value": round(value, 1),
                    "reason": "LLM score_suggestion normalized as calibrated_overall.",
                    "evidence": [],
                }
            )
    return scores
