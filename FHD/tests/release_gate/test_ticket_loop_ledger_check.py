from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

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


def _template() -> dict:
    """已提交台账会记录真实轮次（#2279 起），用例从清空后的模板构造，避免随真实数据漂移。"""
    ledger = _ledger()
    ledger["candidate"].update(source_sha=None, installer_sha256=None)
    for who in ("customer_a", "customer_b"):
        ledger["accounts"][who] = {"alias": None, "tenant": None}
    for ticket in ledger["tickets"].values():
        ticket["ticket_id"] = None
        ticket["processing"] = dict.fromkeys(
            ("para_task_id", "para_device_id", "handler_outputs_evidence")
        ) | {"handlers_attempted": []}
    for item in ledger["items"]:
        item.update(result="UNKNOWN", observed_at=None, evidence=[])
    return ledger


def _gates() -> dict:
    return json.loads((LEDGER_DIR / "gates.json").read_text(encoding="utf-8"))


PARA_OK = {
    "handler": "para_delegate",
    **dict.fromkeys(("ok", "accepted", "completed"), True),
    "status": "completed",
    "source": "para_api",
    "para_result": {"id": "para-task-1"},
}


def _filled(attempts: list[dict], *, pass_items=(24,)) -> dict:
    ledger = _template()
    ledger["candidate"]["source_sha"] = "a" * 40
    ledger["candidate"]["installer_sha256"] = "b" * 64
    ledger["accounts"]["customer_a"] = {"alias": "TEST-A", "tenant": "tenant-a"}
    ledger["accounts"]["customer_b"] = {"alias": "TEST-B", "tenant": "tenant-b"}
    ledger["tickets"]["resolved"]["ticket_id"] = "CS-1"
    ledger["tickets"]["resolved"]["processing"]["para_task_id"] = "para-task-1"
    ledger["tickets"]["resolved"]["processing"]["handlers_attempted"] = attempts
    for item in ledger["items"]:
        if item["no"] in pass_items:
            item.update(result="PASS", observed_at="2026-10-10T15:00:00Z", evidence=["runs/ticket.json"])
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


@pytest.mark.parametrize("attempts, expected", [
    ([PARA_OK], set()),
    ([{**PARA_OK, "ok": False, "completed": False, "error": "device offline"},
      {"handler": "agent", "ok": True}], {"para_fallback_detected", "para_not_completed"}),
    ([PARA_OK, {"handler": "llm_md", "ok": True}], {"para_fallback_detected"}),
    ([{**PARA_OK, "completed": False, "status": "para_task_accepted"}], {"para_not_completed"}),
    ([], {"para_evidence_missing"}),
])
def test_para_processing_outcomes(attempts: list[dict], expected: set[str]) -> None:
    assert _codes(_module().check_ledger(_filled(attempts))) == expected


def test_pass_without_evidence_or_identity_fails() -> None:
    ledger = _template()
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
    ledger["tickets"]["reopened"]["processing"] = ledger["tickets"]["resolved"]["processing"].copy()
    ledger["accounts"]["customer_b"]["tenant"] = "tenant-a"
    codes = _codes(_module().check_ledger(ledger))
    assert {"reopened_ticket_same_as_resolved", "accounts_same_tenant"} <= codes


def test_gate_19_green_requires_all_items_pass() -> None:
    gates = _gates()
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
