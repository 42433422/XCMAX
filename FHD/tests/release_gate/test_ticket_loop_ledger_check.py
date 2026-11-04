from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

import pytest

FHD_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = FHD_ROOT / "docs" / "evidence" / "e2e" / "final-acceptance-1.0.0.5"


CHECK = runpy.run_path(str(FHD_ROOT / "scripts/release/ticket_loop_ledger_check.py"))


def _read(name: str) -> dict:
    return json.loads((LEDGER_DIR / name).read_text(encoding="utf-8"))


def _template() -> dict:
    """已提交台账会记录真实轮次（#2279 起），用例从清空后的模板构造，避免随真实数据漂移。"""
    ledger = _read("ticket-loop.run.json")
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
            item.update(
                result="PASS",
                observed_at="2026-10-10T15:00:00Z",
                evidence=["runs/ticket.json"],
            )
    return ledger


def _codes(errs: list[dict]) -> set[str]:
    return {e["code"] for e in errs}


def test_committed_ledger_and_gates_have_no_violations() -> None:
    assert CHECK["main"](["--ledger", str(LEDGER_DIR / "ticket-loop.run.json")]) == 0


def test_ledger_declares_para_policy_for_ai_processing_items() -> None:
    policy = _read("ticket-loop.run.json")["processor_policy"]
    assert policy["required_handler"] == "para_delegate"
    assert {"agent", "llm_md", "cursor_delegate", "direct_python"} <= set(
        policy["forbidden_local_handlers"]
    )
    assert {19, 24, 26, 48, 49} <= set(policy["applies_to_items"])


PARA_FAILED = dict(PARA_OK, ok=False, completed=False, error="device offline")
PARA_ACCEPTED = dict(PARA_OK, completed=False, status="para_task_accepted")
LOCAL_OK = {"handler": "agent", "ok": True}
FALLBACK, INCOMPLETE = "para_fallback_detected", "para_not_completed"


@pytest.mark.parametrize(
    "attempts, expected",
    [
        ([PARA_OK], set()),
        ([PARA_FAILED, LOCAL_OK], {FALLBACK, INCOMPLETE}),
        ([PARA_OK, {"handler": "llm_md", "ok": True}], {"para_fallback_detected"}),
        ([PARA_ACCEPTED], {INCOMPLETE}),
        ([], {"para_evidence_missing"}),
    ],
)
def test_para_processing_outcomes(attempts: list[dict], expected: set[str]) -> None:
    assert _codes(CHECK["check_ledger"](_filled(attempts))) == expected


def test_pass_without_evidence_or_identity_fails() -> None:
    ledger = _template()
    for item in ledger["items"]:
        if item["no"] == 8:
            item["result"] = "PASS"
    codes = _codes(CHECK["check_ledger"](ledger))
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
    codes = _codes(CHECK["check_ledger"](ledger))
    assert {"reopened_ticket_same_as_resolved", "accounts_same_tenant"} <= codes


def test_gate_19_green_requires_all_items_pass() -> None:
    gates = _read("gates.json")
    for gate in gates["gates"]:
        if gate["no"] == 19:
            gate["status"] = "GREEN"
    errs = CHECK["check_ledger"](_filled([PARA_OK]), gates)
    assert any(e["code"] == "gate_green_without_pass" and e["gate"] == 19 for e in errs)


def test_handler_outputs_evidence_file_is_loaded(tmp_path: Path) -> None:
    (tmp_path / "outputs.json").write_text(
        json.dumps({"outputs": [PARA_OK, {"handler": "vibe_edit", "ok": True}]}),
        encoding="utf-8",
    )
    ledger = _filled([])
    ledger["tickets"]["resolved"]["processing"]["handler_outputs_evidence"] = "outputs.json"
    errs = CHECK["check_ledger"](ledger, base=tmp_path)
    assert _codes(errs) == {"para_fallback_detected"}


@pytest.mark.parametrize(
    "defect, expected",
    [
        ("accepted_missing", "para_not_completed"),
        ("source_ref", "frozen_candidate_invalid"),
        ("installer_digest", "frozen_candidate_invalid"),
        ("weaken_forbidden", "para_fallback_detected"),
        ("weaken_scope", "para_evidence_missing"),
        ("duplicate_item", "item_number_duplicate"),
        ("null_evidence", "pass_without_evidence"),
        ("string_evidence", "pass_without_evidence"),
        ("invalid_time", "pass_with_invalid_observed_at"),
        ("naive_time", "pass_with_invalid_observed_at"),
    ],
)
def test_incomplete_or_weakened_proof_cannot_pass(defect: str, expected: str) -> None:
    ledger = _filled([copy.deepcopy(PARA_OK)])
    processing = ledger["tickets"]["resolved"]["processing"]
    item = next(row for row in ledger["items"] if row["no"] == 24)
    if defect == "accepted_missing":
        processing["handlers_attempted"][0].pop("accepted")
    elif defect == "source_ref":
        ledger["candidate"]["source_sha"] = "main"
    elif defect == "installer_digest":
        ledger["candidate"]["installer_sha256"] = "pending"
    elif defect == "weaken_forbidden":
        ledger["processor_policy"]["forbidden_local_handlers"] = ["other"]
        processing["handlers_attempted"].append({"handler": "direct_python", "ok": True})
    elif defect == "weaken_scope":
        ledger["processor_policy"]["applies_to_items"] = [999]
        ledger["tickets"]["resolved"].pop("processing")
    elif defect == "duplicate_item":
        ledger["items"].insert(0, dict(item, result="FAIL"))
    elif defect in {"null_evidence", "string_evidence"}:
        item["evidence"] = [None] if defect == "null_evidence" else "receipt.json"
    else:
        item["observed_at"] = "pending" if defect == "invalid_time" else "2026-10-10T15:00:00"
    assert expected in _codes(CHECK["check_ledger"](ledger))


@pytest.mark.parametrize("numbers", [None, [], "24", [True], ["24"]])
def test_green_gate_requires_explicit_nonempty_integer_items(numbers) -> None:
    gates = {
        "gates": [
            {
                "no": 19,
                "status": "GREEN",
                "sources": [
                    {"run": "ticket-loop.run.json", "items": numbers},
                ],
            }
        ]
    }
    assert "gate_source_items_invalid" in _codes(CHECK["check_ledger"](_filled([PARA_OK]), gates))


@pytest.mark.parametrize("attempt", [None, "para_delegate", {}, {"handler": " "}])
def test_malformed_handler_records_are_not_silently_dropped(attempt) -> None:
    assert "para_evidence_missing" in _codes(CHECK["check_ledger"](_filled([PARA_OK, attempt])))


@pytest.mark.parametrize("number", [None, True, 0, -1, "pending"])
def test_invalid_item_numbers_fail_closed(number) -> None:
    ledger = _filled([PARA_OK])
    ledger["items"].append({"no": number, "result": "UNKNOWN"})
    assert "item_number_invalid" in _codes(CHECK["check_ledger"](ledger))


@pytest.mark.parametrize(
    "policy",
    ["invalid", {"applies_to_items": "24"}, {"forbidden_local_handlers": [{}]}],
)
def test_malformed_processor_policy_fails_closed(policy) -> None:
    ledger = _filled([PARA_OK])
    ledger["processor_policy"] = policy
    assert "processor_policy_invalid" in _codes(CHECK["check_ledger"](ledger))


def test_custom_policy_can_strengthen_but_not_replace_defaults() -> None:
    ledger = _filled([PARA_OK, {"handler": "custom_local", "ok": True}], pass_items=(1,))
    ledger["processor_policy"] = {
        "applies_to_items": [1],
        "forbidden_local_handlers": ["custom_local"],
    }
    assert "para_fallback_detected" in _codes(CHECK["check_ledger"](ledger))


def test_valid_proof_and_green_gate_are_unchanged() -> None:
    nos = [*range(17, 28), 41]
    ledger = _filled([PARA_OK], pass_items=nos)
    gates = {
        "gates": [
            {
                "no": 19,
                "status": "GREEN",
                "sources": [
                    {"run": "ticket-loop.run.json", "items": nos},
                ],
            }
        ]
    }
    before = copy.deepcopy((ledger, gates))
    assert CHECK["check_ledger"](ledger, gates) == []
    assert (ledger, gates) == before


@pytest.mark.parametrize("section", [None, "", "A", "invalid", "omitted"])
def test_section_cannot_disable_identity_requirements(section) -> None:
    ledger = _filled([PARA_OK])
    item = next(i for i in ledger["items"] if i["no"] == 24)
    if section == "omitted":
        item.pop("section")
    else:
        item["section"] = section
    ledger.pop("candidate")
    ledger.pop("accounts")
    ledger["tickets"]["resolved"].pop("ticket_id")
    assert {
        "item_section_invalid",
        "frozen_candidate_missing",
        "account_missing",
        "resolved_ticket_missing",
    } <= _codes(CHECK["check_ledger"](ledger))


@pytest.mark.parametrize("gate_no", [1, 2, *range(17, 24)])
@pytest.mark.parametrize(
    "sources", [None, [], [{"run": "wrong.run.json", "items": [24]}], "omitted"]
)
def test_green_ticket_gates_require_their_canonical_sources(gate_no, sources) -> None:
    gate = {"no": gate_no, "status": "GREEN"}
    if sources != "omitted":
        gate["sources"] = sources
    assert "gate_required_sources_missing" in _codes(CHECK["check_ledger"]({}, {"gates": [gate]}))


def test_green_gate_cannot_reduce_required_items() -> None:
    ledger = _filled([PARA_OK])
    gate = {
        "no": 19,
        "status": "GREEN",
        "sources": [{"run": "ticket-loop.run.json", "items": [24]}],
    }
    errors = CHECK["check_ledger"](ledger, {"gates": [gate]})
    assert {"gate_required_sources_missing", "gate_green_without_pass"} <= _codes(errors)


@pytest.mark.parametrize("result", ["UNKNOWN", "FAIL", "missing"])
def test_green_gate_requires_every_canonical_item_to_pass(result) -> None:
    nos = [*range(17, 28), 41]
    ledger = _filled([PARA_OK], pass_items=nos)
    if result == "missing":
        ledger["items"] = [i for i in ledger["items"] if i["no"] != 41]
    else:
        next(i for i in ledger["items"] if i["no"] == 41)["result"] = result
    gate = {
        "no": 19,
        "status": "GREEN",
        "sources": [{"run": "ticket-loop.run.json", "items": nos}],
    }
    errors = CHECK["check_ledger"](ledger, {"gates": [gate]})
    assert any(e["code"] == "gate_green_without_pass" and 41 in e["items"] for e in errors)


def test_unknown_item_and_green_gate_numbers_are_rejected() -> None:
    ledger = _filled([PARA_OK])
    ledger["items"].append({"no": 999, "section": "A", "result": "UNKNOWN"})
    assert "item_number_unknown" in _codes(CHECK["check_ledger"](ledger))
    assert "gate_number_invalid" in _codes(
        CHECK["check_ledger"]({}, {"gates": [{"no": 999, "status": "GREEN"}]})
    )


def test_non_ticket_green_gate_remains_outside_ticket_validation() -> None:
    assert CHECK["check_ledger"]({}, {"gates": [{"no": 3, "status": "GREEN"}]}) == []


@pytest.mark.parametrize("catalog", ["ticket-loop.run.json", "gates.json"])
def test_default_catalog_structural_tampering_is_rejected(monkeypatch, catalog) -> None:
    ledger = _template()
    changed = _read(catalog)
    if catalog == "ticket-loop.run.json":
        next(i for i in changed["items"] if i["no"] == 24)["section"] = "A"
    else:
        next(g for g in changed["gates"] if g["no"] == 19)["sources"] = []
    original = Path.read_text

    def read(path, *args, **kwargs):
        return (
            json.dumps(changed) if path == LEDGER_DIR / catalog else original(path, *args, **kwargs)
        )

    monkeypatch.setattr(Path, "read_text", read)
    assert "acceptance_contract_invalid" in _codes(CHECK["check_ledger"](ledger))


def test_evidence_updates_do_not_change_structural_contract(monkeypatch) -> None:
    ledger = _template()
    changed = copy.deepcopy(ledger)
    changed["items"][0].update(
        result="PASS",
        evidence=["new-synthetic-evidence"],
        observed_at="2026-10-22T00:00:00Z",
    )
    original = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda p, *a, **kw: (
            json.dumps(changed)
            if p == LEDGER_DIR / "ticket-loop.run.json"
            else original(p, *a, **kw)
        ),
    )
    assert CHECK["check_ledger"](ledger) == []


def test_caller_base_does_not_override_structural_contract(tmp_path) -> None:
    (tmp_path / "ticket-loop.run.json").write_text('{"items": []}')
    (tmp_path / "gates.json").write_text('{"gates": []}')
    ledger = _filled([PARA_OK])
    next(i for i in ledger["items"] if i["no"] == 24)["section"] = "A"
    assert "item_section_invalid" in _codes(CHECK["check_ledger"](ledger, base=tmp_path))


def test_cli_missing_requested_gate_file_fails_closed(tmp_path, capsys) -> None:
    assert (
        CHECK["main"](
            [
                "--ledger",
                str(LEDGER_DIR / "ticket-loop.run.json"),
                "--gates",
                str(tmp_path / "missing.json"),
            ]
        )
        == 1
    )
    assert "input_file_invalid" in _codes(json.loads(capsys.readouterr().out)["violations"])


def test_unreadable_contract_fails_closed(monkeypatch) -> None:
    ledger = _template()
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path == LEDGER_DIR / "gates.json":
            raise FileNotFoundError("synthetic missing catalog")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert "acceptance_contract_invalid" in _codes(CHECK["check_ledger"](ledger))


def test_cli_malformed_gate_json_fails_closed(tmp_path, capsys) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")
    assert (
        CHECK["main"](["--ledger", str(LEDGER_DIR / "ticket-loop.run.json"), "--gates", str(path)])
        == 1
    )
    assert json.loads(capsys.readouterr().out)["violations"] == [
        {"code": "input_file_invalid", "kind": "JSONDecodeError"}
    ]


@pytest.mark.parametrize("payload", ["null", "[]", "42"])
def test_cli_gate_file_must_be_an_object(tmp_path, capsys, payload) -> None:
    path = tmp_path / "invalid-root.json"
    path.write_text(payload, encoding="utf-8")
    assert (
        CHECK["main"](["--ledger", str(LEDGER_DIR / "ticket-loop.run.json"), "--gates", str(path)])
        == 1
    )
    assert "gates_invalid" in _codes(json.loads(capsys.readouterr().out)["violations"])


def test_ledger_only_python_api_remains_supported() -> None:
    assert CHECK["check_ledger"]({}, None) == []
