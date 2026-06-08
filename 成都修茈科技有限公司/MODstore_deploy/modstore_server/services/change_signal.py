"""变更信号与员工任务生命周期事件。

- doc_change：依赖员工文档相关产出后发布，供 doc-knowledge-curator 等订阅。
- employee.task.done / employee.task.failed：任意员工执行结束统一发布，供 incident-bus 订阅派发。
- employee.execution.recovery：执行器在认知层 transient 重试成功后发布，供运维 / 风险评估绑定消费（非 doc_change）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DOC_CHANGE_SOURCE_EMPLOYEES = frozenset(
    {
        "mods-and-eskill-curator",
        "vibe-coding-maintainer",
        "test-qa-runner",
        "site-content-editor",
        "employee-pack-curator",
    }
)

DOC_CHANGE_EVENT_TYPE = "doc_change"


@dataclass
class ChangeSignal:
    source_employee: str
    change_type: str
    affected_files: List[str] = field(default_factory=list)
    timestamp: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def emit_execution_recovery_event(
    employee_id: str,
    task: str,
    *,
    recovery_action: str,
    success: bool,
    original_error: str,
    attempts: int,
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Publish ``employee.execution.recovery`` after executor-side retry succeeds."""
    payload: Dict[str, Any] = {
        "summary": f"{employee_id} employee.execution.recovery {recovery_action}",
        "task": (task or "")[:500],
        "employee_id": employee_id,
        "recovery_action": recovery_action,
        "success": bool(success),
        "original_error": (original_error or "")[:2000],
        "attempts": int(attempts or 0),
    }
    if extra:
        payload["extra"] = extra

    try:
        from modstore_server.incident_bus import publish

        return publish("employee.execution.recovery", payload, source=employee_id)
    except Exception as exc:
        logger.exception("Failed to publish execution recovery event: %s", exc)
        return False


def emit_task_lifecycle_event(
    employee_id: str,
    task: str,
    *,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: str = "",
) -> bool:
    """发布 employee.task.done 或 employee.task.failed（source=完成任务的员工）。"""
    if status not in ("success", "failed"):
        return False
    event_type = "employee.task.done" if status == "success" else "employee.task.failed"
    payload: Dict[str, Any] = {
        "summary": f"{employee_id} {event_type}",
        "task": (task or "")[:500],
        "finished_employee_id": employee_id,
        "execution_status": status,
    }
    if result is not None:
        payload["result_excerpt"] = (
            str(result.get("result", ""))[:1500] if isinstance(result, dict) else ""
        )
    if error:
        payload["error"] = error[:2000]

    try:
        from modstore_server.incident_bus import publish

        return publish(event_type, payload, source=employee_id)
    except Exception as exc:
        logger.exception("Failed to publish task lifecycle event: %s", exc)
        return False


def publish_doc_change_signal(
    source_employee: str,
    change_type: str,
    affected_files: List[str],
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    if source_employee not in DOC_CHANGE_SOURCE_EMPLOYEES:
        logger.debug("Ignoring doc change signal from non-doc source: %s", source_employee)
        return False

    signal = ChangeSignal(
        source_employee=source_employee,
        change_type=change_type,
        affected_files=affected_files,
        payload=payload or {},
    )

    try:
        from modstore_server.incident_bus import publish

        return publish(
            DOC_CHANGE_EVENT_TYPE,
            signal.to_dict(),
            source=source_employee,
        )
    except Exception as exc:
        logger.exception("Failed to publish doc change signal: %s", exc)
        return False


def emit_signal_on_execution_complete(
    employee_id: str,
    task: str,
    result: Dict[str, Any],
) -> bool:
    if employee_id not in DOC_CHANGE_SOURCE_EMPLOYEES:
        return False

    affected_files: List[str] = []
    change_type = "execution_completed"

    actions_result = result.get("result") or {}
    outputs = actions_result.get("outputs") or []

    for output in outputs:
        handler = str(output.get("handler") or "")

        if handler == "doc_sync":
            changed = output.get("changed_docs") or []
            affected_files.extend(changed)

        if handler in ("shell_exec", "ssh_exec"):
            stdout = str(output.get("stdout") or "")
            for line in stdout.split("\n"):
                line = line.strip()
                if line.endswith((".md", ".yaml", ".json")):
                    affected_files.append(line)

        if handler == "llm_md":
            reasoning = str(output.get("output") or "")
            if "ESkill.md" in reasoning:
                affected_files.append("ESkill.md")
            if "README.md" in reasoning:
                affected_files.append("README.md")

    if employee_id == "mods-and-eskill-curator":
        change_type = "eskill_changed"
        if "ESkill.md" not in affected_files:
            affected_files.append("ESkill.md")

    if employee_id == "vibe-coding-maintainer":
        change_type = "api_changed"

    if employee_id == "test-qa-runner":
        change_type = "coverage_report"

    if employee_id == "site-content-editor":
        change_type = "content_changed"

    if not affected_files:
        return False

    return publish_doc_change_signal(
        source_employee=employee_id,
        change_type=change_type,
        affected_files=list(dict.fromkeys(affected_files)),
        payload={"task": task[:500], "status": result.get("status", "unknown")},
    )


def get_pending_signals_for_doc_curator() -> List[Dict[str, Any]]:
    try:
        from modstore_server.models import IncidentEvent, get_session_factory

        sf = get_session_factory()
        signals: List[Dict[str, Any]] = []
        with sf() as session:
            events = (
                session.query(IncidentEvent)
                .filter(IncidentEvent.event_type == DOC_CHANGE_EVENT_TYPE)
                .order_by(IncidentEvent.created_at.desc())
                .limit(50)
                .all()
            )
            for ev in events:
                try:
                    payload = json.loads(ev.payload_json or "{}")
                except json.JSONDecodeError:
                    payload = {}
                signals.append(
                    {
                        "id": int(ev.id),
                        "source": str(ev.source or ""),
                        "payload": payload,
                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                        "dispatched_count": int(ev.dispatched_count or 0),
                    }
                )
        return signals
    except Exception as exc:
        logger.exception("Failed to get pending signals: %s", exc)
        return []
