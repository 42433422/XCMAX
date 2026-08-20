"""Reference discovery for portable employee-pack workflow bundles."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def collect_referenced_ids(manifest: Dict[str, Any]) -> Tuple[List[int], List[int]]:
    """Walk a manifest and return unique workflow and script-workflow IDs."""
    workflow_ids: List[int] = []
    script_ids: List[int] = []

    def add(target: List[int], value: Any) -> None:
        try:
            normalized = int(value or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized > 0 and normalized not in target:
            target.append(normalized)

    for row in manifest.get("workflow_employees") or []:
        if isinstance(row, dict):
            add(workflow_ids, row.get("workflow_id") or row.get("workflowId"))

    raw_v2 = manifest.get("employee_config_v2")
    v2 = raw_v2 if isinstance(raw_v2, dict) else {}
    raw_collaboration = v2.get("collaboration")
    collaboration = raw_collaboration if isinstance(raw_collaboration, dict) else {}
    raw_workflow = collaboration.get("workflow")
    workflow = raw_workflow if isinstance(raw_workflow, dict) else {}
    add(workflow_ids, workflow.get("workflow_id") or workflow.get("workflowId"))

    for entry in collaboration.get("script_workflows") or []:
        if isinstance(entry, dict):
            add(script_ids, entry.get("script_workflow_id") or entry.get("workflow_id"))

    script_attachment = manifest.get("script_workflow_attachment")
    if isinstance(script_attachment, dict):
        add(
            script_ids,
            script_attachment.get("script_workflow_id") or script_attachment.get("workflow_id"),
        )

    workflow_attachment = manifest.get("workflow_attachment")
    if isinstance(workflow_attachment, dict):
        add(workflow_ids, workflow_attachment.get("workflow_id"))

    return workflow_ids, script_ids


__all__ = ["collect_referenced_ids"]
