"""Test PatchLedger: history, evolution chain, rollback."""

from __future__ import annotations

import json

import pytest

from vibe_coding.runtime import CodeSkillRuntime, JsonCodeSkillStore
from vibe_coding import MockLLM, PatchLedger
from vibe_coding.code_factory import NLCodeSkillFactory


def _seed_skill_with_two_versions(tmp_path) -> tuple[JsonCodeSkillStore, str]:
    store = JsonCodeSkillStore(tmp_path / "code.json")
    spec = {
        "skill_id": "extract",
        "name": "extract",
        "domain": "",
        "function_name": "extract",
        "purpose": "extract name",
        "signature": {"params": ["user"], "return_type": "dict", "required_params": ["user"]},
        "dependencies": [],
        "test_cases": [
            {
                "case_id": "happy",
                "input_data": {"user": {"name": "ada"}},
                "expected_output": {"name": "ada"},
            }
        ],
        "quality_gate": {"required_keys": ["name"]},
        "domain_keywords": [],
    }
    code = {"source_code": "def extract(user):\n    return {'name': user['name']}\n"}
    llm = MockLLM([json.dumps(spec), json.dumps(code)])
    factory = NLCodeSkillFactory(llm, store)
    factory.generate("brief")
    runtime = CodeSkillRuntime(store)
    runtime.run("extract", {"user": {}})  # triggers solidify v2
    return store, "extract"


def test_history_contains_solidify_event(tmp_path):
    store, sid = _seed_skill_with_two_versions(tmp_path)
    ledger = PatchLedger(code_store=store)
    history = ledger.history(sid)
    assert any(r.stage == "solidified" for r in history)


def test_evolution_chain_lists_versions(tmp_path):
    store, sid = _seed_skill_with_two_versions(tmp_path)
    ledger = PatchLedger(code_store=store)
    chain = ledger.evolution_chain(sid)
    assert [c["version"] for c in chain] == [1, 2]
    assert sum(1 for c in chain if c["active"]) == 1


def test_rollback_changes_active_version(tmp_path):
    store, sid = _seed_skill_with_two_versions(tmp_path)
    ledger = PatchLedger(code_store=store)
    skill_before = store.get_code_skill(sid)
    assert skill_before.active_version == 2
    ledger.rollback(sid, 1)
    skill_after = store.get_code_skill(sid)
    assert skill_after.active_version == 1


def test_rollback_unknown_version_raises(tmp_path):
    store, sid = _seed_skill_with_two_versions(tmp_path)
    ledger = PatchLedger(code_store=store)
    with pytest.raises(ValueError):
        ledger.rollback(sid, 999)


def test_report_aggregates_health(tmp_path):
    store, sid = _seed_skill_with_two_versions(tmp_path)
    ledger = PatchLedger(code_store=store)
    report = ledger.report()
    assert report["totals"]["skills"] == 1
    assert report["totals"]["healed"] >= 1


def test_ledger_requires_code_store():
    with pytest.raises(ValueError):
        PatchLedger(code_store=None)


def test_history_for_unknown_skill_returns_empty(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "empty.json")
    ledger = PatchLedger(code_store=store)
    assert ledger.history("nope") == []


def test_empty_store_report_zero_skills(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "code.json")
    ledger = PatchLedger(code_store=store)
    assert ledger.report()["totals"]["skills"] == 0
