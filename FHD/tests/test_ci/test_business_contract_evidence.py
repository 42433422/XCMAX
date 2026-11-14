"""契约证据校验的正反例，以及 E23 回读能抓住重复插入。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.dev.check_business_contract_evidence import (
    MINIMUM_REQUIRED,
    REQUIRED_TESTS,
    catalog_errors,
    ci_gate,
    evidence_from_junit,
    floor_errors,
    load_catalog,
    required_node_ids,
    requirement_rollup,
    validate,
)
from tests.test_application.test_idempotency_recovery_e23_e24 import (
    test_e23_kill_after_commit_returns_the_same_row,
)

CLASSNAME = "tests.test_application.test_idempotency_recovery_e23_e24"
NAME = "test_e23_kill_after_commit_returns_the_same_row"
EXPORT_CLASS = "tests.test_application.test_shipment_records_agent_routes"
EXPORT_NAME = "test_approved_shipment_then_export_uses_full_persisted_plan"


def _case(classname: str, name: str, inner: str = "") -> str:
    return f"<testcase classname='{classname}' name='{name}'>{inner}</testcase>"


def _passing_pair() -> str:
    body = ""
    seen: set[str] = set()
    for node_ids in required_node_ids().values():
        for node_id in node_ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            bits = node_id.split("::")
            classname = bits[0][:-3].replace("/", ".")
            if len(bits) > 2:
                classname += "." + ".".join(bits[1:-1])
            body += _case(classname, bits[-1])
    return body


def _xml(body: str) -> str:
    return f"<testsuite tests='1'>{body}</testsuite>"


def _write(directory: Path, body: str, name: str = "full.xml") -> Path:
    shard = directory / "backend-shard-1-1"
    shard.mkdir(parents=True)
    path = shard / name
    path.write_text(_xml(body), encoding="utf-8")
    return path


def test_catalog_keeps_the_required_readback_scenario():
    assert catalog_errors(load_catalog()) == []


def test_removing_the_required_scenario_is_rejected():
    data = load_catalog()
    data["contracts"] = [
        item for item in data["contracts"] if item["scenario_id"] not in MINIMUM_REQUIRED
    ]
    assert any("required scenarios removed" in error for error in catalog_errors(data))


def test_one_passing_child_does_not_complete_the_requirement():
    rollup = requirement_rollup(
        {
            "contracts": [
                {
                    "requirement_id": "RX",
                    "scenario_id": "RX-done",
                    "tests": ["tests/a.py::test_a"],
                    "boundary": {"execution": "real"},
                    "known_defects": [],
                },
                {
                    "requirement_id": "RX",
                    "scenario_id": "RX-open",
                    "tests": [],
                    "boundary": {"execution": "NOT RUN"},
                    "known_defects": [],
                },
            ]
        }
    )
    assert rollup["RX"] == "NOT RUN"


def test_floor_from_main_rejects_a_shrunk_required_set():
    assert (
        floor_errors(
            {
                "required_scenarios": list(MINIMUM_REQUIRED),
                "required_tests": dict(REQUIRED_TESTS),
            }
        )
        == []
    )
    errors = floor_errors(
        {
            "required_scenarios": ["R08-e23-readback", "not-in-this-change"],
            "required_tests": {
                **REQUIRED_TESTS,
                "R08-e23-readback": "tests/other.py::test_other",
            },
        }
    )
    assert any("not-in-this-change" in error for error in errors)
    assert any("tests/other.py::test_other" in error for error in errors)


def test_passed_junit_is_accepted(tmp_path: Path):
    body = _passing_pair()
    evidence = evidence_from_junit(
        [_write(tmp_path, body)], source_sha="abc", run_id="9", run_attempt="1"
    )
    assert (
        validate(
            evidence, expected_sha="abc", required_ids=MINIMUM_REQUIRED, allow_not_applicable=False
        )
        == []
    )


def test_missing_required_result_is_rejected(tmp_path: Path):
    evidence = evidence_from_junit(
        [_write(tmp_path, "<testcase classname='other' name='other'/>")],
        source_sha="abc",
        run_id="9",
        run_attempt="1",
    )
    errors = validate(
        evidence, expected_sha="abc", required_ids=MINIMUM_REQUIRED, allow_not_applicable=False
    )
    assert any("NOT RUN is not PASS" in error for error in errors)
    absent = dict(evidence)
    absent["scenarios"] = []
    assert any(
        "no result" in error
        for error in validate(
            absent, expected_sha="abc", required_ids=MINIMUM_REQUIRED, allow_not_applicable=False
        )
    )


def test_wrong_sha_skip_and_retry_cover_are_rejected(tmp_path: Path):
    failed = (
        _case(CLASSNAME, NAME, "<failure message='len(after) == 1'>assert 2 == 1</failure>")
        + _case(CLASSNAME, NAME)
        + _case(EXPORT_CLASS, EXPORT_NAME)
    )
    evidence = evidence_from_junit(
        [_write(tmp_path, failed)], source_sha="abc", run_id="9", run_attempt="1"
    )
    errors = validate(
        evidence, expected_sha="wrong", required_ids=MINIMUM_REQUIRED, allow_not_applicable=False
    )
    assert any("source sha" in error for error in errors)
    assert any("FAIL is not PASS" in error for error in errors)
    covered = dict(evidence)
    covered["source_sha"] = "abc"
    covered["scenarios"] = [
        {
            "scenario_id": "R08-e23-readback",
            "status": "PASS",
            "attempts": [
                {"n": 1, "status": "FAIL", "failure": "assert 2 == 1"},
                {"n": 2, "status": "PASS", "failure": ""},
            ],
        },
        {
            "scenario_id": "R05-approved-shipment-export",
            "status": "PASS",
            "attempts": [{"n": 1, "status": "PASS", "failure": ""}],
        },
    ]
    assert any(
        "PASS hides" in error
        for error in validate(
            covered, expected_sha="abc", required_ids=MINIMUM_REQUIRED, allow_not_applicable=False
        )
    )

    skipped = _case(CLASSNAME, NAME, "<skipped message='skip'/>") + _case(EXPORT_CLASS, EXPORT_NAME)
    skipped_evidence = evidence_from_junit(
        [_write(tmp_path / "skip", skipped)],
        source_sha="abc",
        run_id="9",
        run_attempt="1",
    )
    assert any(
        "NOT RUN" in error
        for error in validate(
            skipped_evidence,
            expected_sha="abc",
            required_ids=MINIMUM_REQUIRED,
            allow_not_applicable=False,
        )
    )


def test_damaged_evidence_and_blocked_are_rejected():
    damaged = validate(
        {"source_sha": "abc"},
        expected_sha="abc",
        required_ids=MINIMUM_REQUIRED,
        allow_not_applicable=False,
    )
    assert any("scenarios missing" in error for error in damaged)
    blocked = {
        "source_sha": "abc",
        "scenarios": [
            {"scenario_id": scenario_id, "status": "BLOCKED", "attempts": []}
            for scenario_id in MINIMUM_REQUIRED
        ],
    }
    assert any(
        "BLOCKED" in error
        for error in validate(
            blocked, expected_sha="abc", required_ids=MINIMUM_REQUIRED, allow_not_applicable=False
        )
    )


def test_evidence_without_run_binding_is_rejected(tmp_path: Path):
    evidence = evidence_from_junit(
        [_write(tmp_path, _passing_pair())], source_sha="abc", run_id="9", run_attempt="1"
    )
    evidence["run_id"] = ""
    evidence["data_version"] = ""
    errors = validate(
        evidence, expected_sha="abc", required_ids=MINIMUM_REQUIRED, allow_not_applicable=False
    )
    assert any("run_id is not bound" in error for error in errors)
    assert any("data_version is not bound" in error for error in errors)


def test_ci_gate_blocks_when_the_shard_never_started(tmp_path: Path):
    with pytest.raises(ValueError, match="no junit"):
        ci_gate(tmp_path, source_sha="a" * 40, run_id="9", run_attempt="1", backend="ran")


def test_ci_gate_records_not_applicable_when_backend_is_skipped():
    evidence = ci_gate(
        Path("missing"), source_sha="a" * 40, run_id="local", run_attempt="1", backend="skipped"
    )
    assert evidence["scenarios"][0]["status"] == "NOT APPLICABLE"


def test_parameterized_required_test_fails_when_one_instance_fails(tmp_path: Path):
    """整体 nodeid 会聚合全部参数实例：任一参数失败，场景不能算通过。"""
    base = REQUIRED_TESTS["R03-confirm-binding"]
    module, _, name = base.partition("::")
    classname = module[:-3].replace("/", ".")
    body = ""
    seen: set[str] = set()
    for scenario_id, node_id in REQUIRED_TESTS.items():
        if scenario_id == "R03-confirm-binding" or node_id in seen:
            continue
        seen.add(node_id)
        bits = node_id.split("::")
        cn = bits[0][:-3].replace("/", ".")
        if len(bits) > 2:
            cn += "." + ".".join(bits[1:-1])
        body += _case(cn, bits[-1])
    body += _case(classname, f"{name}[None]")
    body += _case(classname, f'{name}[""]', "<failure message='boom'/>")
    evidence = evidence_from_junit(
        [_write(tmp_path, body)], source_sha="abc", run_id="9", run_attempt="1"
    )
    r03 = next(item for item in evidence["scenarios"] if item["scenario_id"] == "R03-confirm-binding")
    assert r03["status"] == "FAIL"


def test_parameterized_required_test_passes_when_every_instance_passes(tmp_path: Path):
    base = REQUIRED_TESTS["R03-confirm-binding"]
    module, _, name = base.partition("::")
    classname = module[:-3].replace("/", ".")
    body = ""
    seen: set[str] = set()
    for scenario_id, node_id in REQUIRED_TESTS.items():
        if scenario_id == "R03-confirm-binding" or node_id in seen:
            continue
        seen.add(node_id)
        bits = node_id.split("::")
        cn = bits[0][:-3].replace("/", ".")
        if len(bits) > 2:
            cn += "." + ".".join(bits[1:-1])
        body += _case(cn, bits[-1])
    body += _case(classname, f"{name}[None]")
    body += _case(classname, f'{name}[""]')
    evidence = evidence_from_junit(
        [_write(tmp_path, body)], source_sha="abc", run_id="9", run_attempt="1"
    )
    r03 = next(item for item in evidence["scenarios"] if item["scenario_id"] == "R03-confirm-binding")
    assert r03["status"] == "PASS"
    assert len(r03["attempts"]) == 2


def test_a_lookalike_name_is_not_the_required_node(tmp_path: Path):
    body = ""
    for node_id in REQUIRED_TESTS.values():
        module, _, name = node_id.partition("::")
        body += _case(module[:-3].replace("/", "."), name + "_other")
        if "[" in name:
            body += _case(module[:-3].replace("/", "."), name.split("[", 1)[0])
    evidence = evidence_from_junit(
        [_write(tmp_path, body)], source_sha="abc", run_id="9", run_attempt="1"
    )
    assert all(item["status"] == "NOT RUN" for item in evidence["scenarios"])
    with pytest.raises(ValueError, match="NOT RUN"):
        ci_gate(tmp_path, source_sha="a" * 40, run_id="9", run_attempt="1", backend="ran")


def test_short_sha_is_rejected(tmp_path: Path):
    _write(tmp_path, _passing_pair())
    with pytest.raises(ValueError, match="40 lowercase hex"):
        ci_gate(tmp_path, source_sha="abc", run_id="9", run_attempt="1", backend="ran")


def test_broken_xml_is_rejected(tmp_path: Path):
    shard = tmp_path / "backend-shard-1-1"
    shard.mkdir(parents=True)
    (shard / "full.xml").write_text("<testsuite>", encoding="utf-8")
    with pytest.raises(ET.ParseError):
        ci_gate(tmp_path, source_sha="a" * 40, run_id="9", run_attempt="1", backend="ran")


def test_r08_readback_fails_when_recovery_inserts_again(monkeypatch):
    import app.application.agent_orchestrator.tool_permission as permissions

    real = permissions.begin_idempotent_replay

    def drop_replay(*args, **kwargs):
        key, _replay = real(*args, **kwargs)
        return key, None

    monkeypatch.setattr(permissions, "begin_idempotent_replay", drop_replay)
    with pytest.raises(AssertionError) as caught:
        test_e23_kill_after_commit_returns_the_same_row()
    message = str(caught.value)
    folded = message.encode("utf-8", "backslashreplace").decode("unicode_escape")
    assert "客户名称已存在" in message or "客户名称已存在" in folded
    monkeypatch.undo()
    test_e23_kill_after_commit_returns_the_same_row()
