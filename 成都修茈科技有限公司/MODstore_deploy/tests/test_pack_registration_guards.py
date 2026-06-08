"""pack-registrar 登记门禁单元测试。"""

from __future__ import annotations

from modstore_server.pack_registration_guards import (
    audit_failure_error_payload,
    classify_audit_failure,
    registration_metadata_mismatches,
    workflow_automation_block_reason,
)


def test_workflow_automation_blocks_incomplete_upstream():
    reason = workflow_automation_block_reason(
        [{"workflow_index": 0, "ok": False, "automation_complete": False}],
        workflow_index=0,
        wf_entry={"id": "emp-a", "label": "A"},
    )
    assert reason
    assert "workflow-automator" in reason or "workflow_index" in reason


def test_workflow_automation_allows_complete():
    assert (
        workflow_automation_block_reason(
            [{"workflow_index": 0, "ok": True, "workflow_id": 12, "automation_complete": True}],
            workflow_index=0,
            wf_entry={"id": "emp-a"},
        )
        is None
    )


def test_workflow_automation_wf_attach_flag():
    assert (
        workflow_automation_block_reason(
            [],
            wf_attach={"ok": True, "automation_complete": True, "workflow_id": 9},
            wf_entry={"id": "x"},
        )
        is None
    )


def test_workflow_automation_skips_pack_only_without_workflow_expectation():
    assert (
        workflow_automation_block_reason(
            [],
            wf_entry={"id": "emp-only", "label": "Only pack"},
        )
        is None
    )


def test_classify_audit_trivial_vs_non_trivial():
    trivial = classify_audit_failure(
        {
            "ok": True,
            "summary": {"pass": False, "average": 55},
            "dimensions": {
                "metadata_quality": {"score": 40, "reasons": []},
                "manifest_compliance": {"score": 80, "reasons": []},
            },
        }
    )
    assert trivial["repair_tier"] == "trivial"
    assert trivial["dynamic_repair_allowed"] is True

    hard = classify_audit_failure(
        {
            "ok": True,
            "summary": {"pass": False, "average": 30},
            "dimensions": {
                "manifest_compliance": {"score": 10, "reasons": []},
                "security_and_size": {"score": 20, "reasons": []},
            },
        }
    )
    assert hard["repair_tier"] == "non_trivial"
    assert hard["escalate_to_human"] is True
    assert hard["dynamic_repair_allowed"] is False


def test_audit_failure_payload_escalate():
    audit = {"ok": True, "summary": {"pass": False}}
    cls = classify_audit_failure(
        {
            "ok": True,
            "summary": {"pass": False},
            "dimensions": {"manifest_compliance": {"score": 0, "reasons": []}},
        }
    )
    err = audit_failure_error_payload(
        pack_id="mod-emp",
        workflow_index=0,
        audit=audit,
        classification=cls,
    )
    assert err["audit_passed"] is False
    assert err["escalate_to_human"] is True
    assert err["dynamic_repair_allowed"] is False


def test_registration_metadata_mismatch_version():
    mismatches = registration_metadata_mismatches(
        wf_entry={"id": "m-emp", "label": "Label A"},
        mod_manifest={"version": "2.0.0", "author": "alice"},
        audit_manifest={"id": "m-emp", "name": "Label A", "version": "1.0.0", "author": "alice"},
        catalog_rec={"id": "m-emp", "name": "Label A", "version": "2.0.0"},
    )
    assert any("version" in m for m in mismatches)
