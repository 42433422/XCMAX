"""Wave 0: risk_actions.registry.json SSOT contract (release_gate)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.application.employee_runtime.write_approval import build_write_approval_gate
from app.application.workflow.risk_gate import HybridRiskGate
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.services.tools_execution.registry import get_workflow_tool_registry
from resources.config.risk_actions_loader import load_risk_registry

pytestmark = pytest.mark.release_gate

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent
REQUIRED_CLASSES = {
    "business_db.write",
    "im.send",
    "permission.grant",
    "payment.charge",
    "bulk_import",
    "delete.batch",
}

REQUIRED_ACTIVATION_EVIDENCE = {
    "apply_release_to_cvm": (
        ROOT / "scripts/deploy/fhd-auto-update.sh",
        'evaluate_risk(\n    "apply_release_to_cvm"',
    ),
    "rollback_release": (
        ROOT / "scripts/deploy/fhd-apply-release.sh",
        'autonomy_evaluate_action "rollback_release"',
    ),
    "freeze_manifest": (
        ROOT / "app/fastapi_routes/ops_autonomy.py",
        '"freeze_manifest": "freeze-manifest"',
    ),
    "restart_service": (
        ROOT / "scripts/deploy/fhd-apply-release.sh",
        'autonomy_evaluate_action "restart_service"',
    ),
    "self_heal_pr_merge": (
        REPO_ROOT / "成都修茈科技有限公司/MODstore_deploy/modstore_server/approval_dispatcher.py",
        'evaluate_risk(\n        "self_heal_pr_merge"',
    ),
    "mod_auto_publish": (
        REPO_ROOT / "成都修茈科技有限公司/MODstore_deploy/modstore_server/workbench_api.py",
        'evaluate_risk(\n        "mod_auto_publish"',
    ),
    "db_migration": (
        ROOT / "scripts/deploy/fhd-apply-release.sh",
        'autonomy_evaluate_action "db_migration"',
    ),
    "delete_user_data": (
        REPO_ROOT / ".github/workflows/fhd-autonomy-approval-dispatch.yml",
        "probe_delete_user_data",
    ),
}


def test_risk_registry_file_exists():
    path = ROOT / "config" / "risk_actions.registry.json"
    assert path.is_file()


def test_action_classes_complete():
    reg = load_risk_registry()
    classes = set((reg.get("action_classes") or {}).keys())
    assert classes >= REQUIRED_CLASSES


def test_registry_tools_parity():
    reg = load_risk_registry()
    json_tools = set((reg.get("tools") or {}).keys())
    runtime_tools = set(get_workflow_tool_registry().keys())
    assert json_tools == runtime_tools, (
        f"drift: json-only={json_tools - runtime_tools} runtime-only={runtime_tools - json_tools}"
    )


def test_hybrid_risk_gate_medium_high():
    gate = HybridRiskGate()
    plan = PlanGraph(
        plan_id="t",
        intent="t",
        nodes=[
            WorkflowNode(
                node_id="n1",
                tool_id="products",
                action="create",
                params={},
                risk="medium",
            )
        ],
        risk_level="medium",
    )
    assert gate.evaluate(plan, {}).requires_confirmation is True


def test_write_approval_blocks_bulk_import_without_token():
    gate = build_write_approval_gate("test-emp", {})
    verdict = gate("import_excel_to_database", {"file_path": "/tmp/x.xlsx"})
    assert verdict.get("ok") is False or verdict.get("pending_approval") is True


def test_export_script_bindings_present():
    raw = json.loads((ROOT / "config" / "risk_actions.registry.json").read_text(encoding="utf-8"))
    products = (raw.get("tools") or {}).get("products", {}).get("actions", {})
    assert products.get("create", {}).get("action_class") == "business_db.write"


def test_required_autonomous_actions_have_executable_activation_evidence():
    """Prevent a registry-only action from masquerading as an active risk gate."""
    registry = load_risk_registry()
    actions = registry.get("autonomous_actions") or {}
    assert set(REQUIRED_ACTIVATION_EVIDENCE) <= set(actions)

    for action, (path, marker) in REQUIRED_ACTIVATION_EVIDENCE.items():
        assert path.is_file(), f"{action}: missing activation entrypoint {path}"
        assert marker in path.read_text(encoding="utf-8"), (
            f"{action}: registry entry exists but no SSOT activation marker in {path}"
        )

    bridge = (ROOT / "scripts/deploy/lib/autonomy_gate.sh").read_text(encoding="utf-8")
    assert "from app.domain.autonomy.autonomy_guard import evaluate_risk" in bridge
    delegate = (
        REPO_ROOT
        / "成都修茈科技有限公司/MODstore_deploy/modstore_server/autonomy_guard_delegate.py"
    ).read_text(encoding="utf-8")
    assert "from app.domain.autonomy.autonomy_guard import evaluate_risk" in delegate
