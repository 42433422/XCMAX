from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = FHD_ROOT / "docs" / "evidence" / "e2e" / "final-acceptance-1.0.0.5"


def _module():
    script = FHD_ROOT / "scripts" / "release" / "ticket_loop_ledger_check.py"
    spec = importlib.util.spec_from_file_location("ticket_loop_ledger_check", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ledger() -> dict:
    return json.loads((LEDGER_DIR / "ticket-loop.run.json").read_text(encoding="utf-8"))


def _gates() -> dict:
    return json.loads((LEDGER_DIR / "gates.json").read_text(encoding="utf-8"))


PARA_OK = {
    "handler": "para_delegate",
    "ok": True,
    "accepted": True,
    "completed": True,
    "status": "completed",
    "source": "para_api",
    "para_result": {"id": "para-task-1"},
}


def _filled(attempts: list[dict], *, pass_items=(24,)) -> dict:
    ledger = copy.deepcopy(_ledger())
    ledger["candidate"]["source_sha"] = "a" * 40
    ledger["candidate"]["installer_sha256"] = "b" * 64
    ledger["accounts"]["customer_a"] = {"alias": "TEST-A", "tenant": "tenant-a"}
    ledger["accounts"]["customer_b"] = {"alias": "TEST-B", "tenant": "tenant-b"}
    ledger["tickets"]["resolved"]["ticket_id"] = "CS-1"
    ledger["tickets"]["resolved"]["processing"]["para_task_id"] = "para-task-1"
    ledger["tickets"]["resolved"]["processing"]["handlers_attempted"] = attempts
    for item in ledger["items"]:
        if item["no"] in pass_items:
            item["result"] = "PASS"
            item["observed_at"] = "2026-10-10T15:00:00Z"
            item["evidence"] = ["runs/ticket.json"]
    return ledger


def _codes(errs: list[dict]) -> set[str]:
    return {e["code"] for e in errs}


def test_committed_ledger_and_gates_have_no_violations() -> None:
    mod = _module()
    assert mod.check_ledger(_ledger(), _gates(), LEDGER_DIR) == []
    assert mod.main(["--ledger", str(LEDGER_DIR / "ticket-loop.run.json")]) == 0


def test_ledger_declares_para_policy_for_ai_processing_items() -> None:
    policy = _ledger()["processor_policy"]
    assert policy["required_handler"] == "para_delegate"
    assert {"agent", "llm_md", "cursor_delegate", "direct_python"} <= set(
        policy["forbidden_local_handlers"]
    )
    assert {19, 24, 26, 48, 49} <= set(policy["applies_to_items"])


def test_para_completed_without_fallback_passes() -> None:
    assert _module().check_ledger(_filled([PARA_OK])) == []


def test_local_llm_fallback_after_para_failure_fails() -> None:
    para_failed = {**PARA_OK, "ok": False, "completed": False, "error": "device offline"}
    errs = _module().check_ledger(_filled([para_failed, {"handler": "agent", "ok": True}]))
    assert {"para_fallback_detected", "para_not_completed"} <= _codes(errs)


def test_llm_md_alongside_successful_para_still_counts_as_fallback() -> None:
    errs = _module().check_ledger(_filled([PARA_OK, {"handler": "llm_md", "ok": True}]))
    assert _codes(errs) == {"para_fallback_detected"}


def test_para_accepted_but_not_completed_fails() -> None:
    accepted_only = {**PARA_OK, "completed": False, "status": "para_task_accepted"}
    assert "para_not_completed" in _codes(_module().check_ledger(_filled([accepted_only])))


def test_missing_processing_evidence_fails() -> None:
    assert "para_evidence_missing" in _codes(_module().check_ledger(_filled([])))


def test_pass_without_evidence_or_identity_fails() -> None:
    ledger = copy.deepcopy(_ledger())
    for item in ledger["items"]:
        if item["no"] == 8:
            item["result"] = "PASS"
    codes = _codes(_module().check_ledger(ledger))
    assert {
        "pass_without_observed_at",
        "pass_without_evidence",
        "frozen_candidate_missing",
        "account_missing",
        "resolved_ticket_missing",
    } <= codes


def test_reopen_needs_distinct_ticket_and_tenants_must_differ() -> None:
    ledger = _filled([PARA_OK], pass_items=(24, 36))
    ledger["tickets"]["reopened"]["ticket_id"] = "CS-1"
    ledger["tickets"]["reopened"]["processing"] = copy.deepcopy(
        ledger["tickets"]["resolved"]["processing"]
    )
    ledger["accounts"]["customer_b"]["tenant"] = "tenant-a"
    codes = _codes(_module().check_ledger(ledger))
    assert {"reopened_ticket_same_as_resolved", "accounts_same_tenant"} <= codes


def test_gate_19_green_requires_all_items_pass() -> None:
    gates = copy.deepcopy(_gates())
    for gate in gates["gates"]:
        if gate["no"] == 19:
            gate["status"] = "GREEN"
    errs = _module().check_ledger(_filled([PARA_OK]), gates)
    assert any(e["code"] == "gate_green_without_pass" and e["gate"] == 19 for e in errs)


def test_handler_outputs_evidence_file_is_loaded(tmp_path: Path) -> None:
    (tmp_path / "outputs.json").write_text(
        json.dumps({"outputs": [PARA_OK, {"handler": "vibe_edit", "ok": True}]}), encoding="utf-8"
    )
    ledger = _filled([])
    ledger["tickets"]["resolved"]["processing"]["handler_outputs_evidence"] = "outputs.json"
    errs = _module().check_ledger(ledger, base=tmp_path)
    assert _codes(errs) == {"para_fallback_detected"}
