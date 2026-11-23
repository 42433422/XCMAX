"""Official backup and restore retain their distinct approval contracts."""


def test_official_backup_keeps_existing_approval_contract():
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.workflow_types import WorkflowNode
    from resources.config.risk_actions_loader import get_action_approval

    svc = ApprovalService()
    backup = WorkflowNode(
        node_id="b",
        tool_id="system_maintenance",
        action="backup_database",
        params={},
        risk="medium",
    )
    restore = WorkflowNode(
        node_id="r", tool_id="system_maintenance", action="restore_database", params={}, risk="high"
    )
    assert get_action_approval("system_maintenance", "backup_database") != "always"
    assert svc.check_node_requires_approval(backup) is False
    assert get_action_approval("system_maintenance", "restore_database") == "always"
    assert svc.check_node_requires_approval(restore) is True
