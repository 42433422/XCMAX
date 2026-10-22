"""Explicit immutable, read-only checks reuse Para's existing child task protocol."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from modstore_server import models
from modstore_server import para_delegate_handler as h
from modstore_server.customer_issue_delivery_contract import (
    execution_requires_reconciliation,
)
from modstore_server.node_coordinator import incident_claim_scope
from tests.test_para_delegate_tier import _integ_env, _IntegClient, _online_codex
from tests.test_para_first_no_planning_llm import fresh_db as fresh_db


@pytest.fixture
def check_request(fresh_db, monkeypatch):
    _integ_env(monkeypatch)
    monkeypatch.setenv("MODSTORE_CREDENTIAL_TASK_GRANTS", "0")
    units = [
        {
            "unit_id": name,
            "title": name,
            "prompt": prompt,
            "read_only": True,
            "source_revision": "a" * 40,
        }
        for name, prompt in (
            ("api", "Check API response fields"),
            ("ui", "Check UI status rendering"),
        )
    ]
    claim = {
        "schema_version": 2,
        "plan": {"execution_schema": 2, "independent_checks": {"scout": units}},
        "team": [
            {
                "role": "scout",
                "employee_id": "scout",
                "attempt_id": "attempt-1",
                "status": "dispatching",
            }
        ],
    }
    with models.get_session_factory()() as db:
        event = models.IncidentEvent(
            event_type="test",
            source="test",
            payload_json=json.dumps({"_team_claim": claim}),
        )
        db.add(event)
        db.commit()
        event_id = event.id
    return {
        "request_id": "attempt-1",
        "repo_url": "https://example.com/repo.git",
        "report_only": True,
        "wait_for_para": False,
        "mode": "review",
        "task": "Review incident",
        "raw_input": {
            "_trusted_incident_team_execution": True,
            "_incident_continuation": True,
            "event_id": event_id,
            "attempt_id": "attempt-1",
            "role": "scout",
            "independent_checks": units,
        },
    }


def test_explicit_checks_have_distinct_prompts_and_one_parent(check_request, monkeypatch):
    client = _IntegClient([_online_codex("w1"), _online_codex("w2")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    with incident_claim_scope(check_request["raw_input"]["event_id"]):
        out = h._post_para_api_once(check_request)
    assert out["accepted"] and not out["completed"]
    assert out["required_subtask_ids"] == ["sub-1", "sub-2"]
    assert [d["unit_id"] for d in out["devices"]] == ["api", "ui"]
    assert [p["device_id"] for p in client.posted_tasks] == ["w1", "w2"]
    assert client.posted_tasks[1]["task_id"] == "task-1"
    for payload, unit in zip(client.posted_tasks, check_request["raw_input"]["independent_checks"]):
        assert unit["prompt"] in payload["prompt"]
        assert payload["branch"] == "a" * 40
        assert payload["report_only"] is True and payload["max_attempts"] == 1
        assert not payload.get("auto_merge")
        assert not payload.get("depends_on")


def test_same_device_units_keep_distinct_request_keys(check_request, monkeypatch):
    client = _IntegClient([_online_codex("w1")])
    keys = []
    post = client.post

    def capture(url, headers=None, json=None):
        keys.append(headers["Idempotency-Key"])
        return post(url, headers, json)

    monkeypatch.setattr(client, "post", capture)
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    with incident_claim_scope(check_request["raw_input"]["event_id"]):
        out = h._post_para_api_once(check_request)
    assert len(keys) == len(set(keys)) == 2
    assert out["planned_devices"] == ["w1", "w1"]


def test_client_cannot_replace_saved_checks_or_parallelize_fix(check_request, monkeypatch):
    client = _IntegClient([_online_codex("w1")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    for role, units in (
        ("fix", check_request["raw_input"]["independent_checks"]),
        ("scout", [{"unit_id": "injected", "read_only": True, "prompt": "unreviewed"}]),
    ):
        req = {
            **check_request,
            "raw_input": {
                **check_request["raw_input"],
                "role": role,
                "independent_checks": units,
            },
        }
        with incident_claim_scope(req["raw_input"]["event_id"]):
            out = h._post_para_api_once(req)
        assert out["status"] == "blocked_independent_checks"
        assert not out["accepted"] and not out["queued"]
    assert client.posted_tasks == []


def test_second_check_lost_receipt_remains_partial_unknown(check_request, monkeypatch):
    client = _IntegClient([_online_codex("w1"), _online_codex("w2")])
    post = client.post

    def lose(url, headers=None, json=None):
        if client.posted_tasks:
            raise httpx.ReadTimeout("lost receipt")
        return post(url, headers, json)

    monkeypatch.setattr(client, "post", lose)
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    with incident_claim_scope(check_request["raw_input"]["event_id"]):
        out = h._post_para_api_once(check_request)
    assert out["task_id"] == "task-1"
    assert out["partial"] and not out["completed"]
    assert out["required_subtask_ids"] == ["sub-1"]
    assert execution_requires_reconciliation(out)


def test_incident_repair_keeps_one_writer_on_fleet(monkeypatch):
    _integ_env(monkeypatch)
    client = _IntegClient([_online_codex("w1"), _online_codex("w2")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    result = h.dispatch_para_delegate(
        task="Repair",
        employee_id="fix",
        input_data={
            "_incident_continuation": True,
            "role": "fix",
            "max_devices": 2,
            "wait_for_para": False,
        },
    )
    assert result["accepted"] and len(client.posted_tasks) == 1


def test_verification_checks_require_current_fix_sha(check_request, monkeypatch):
    raw = check_request["raw_input"]
    raw["role"] = "verify"
    client = _IntegClient([_online_codex("w1")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    with models.get_session_factory()() as db:
        event = db.get(models.IncidentEvent, raw["event_id"])
        payload = json.loads(event.payload_json)
        claim = payload["_team_claim"]
        claim["plan"]["independent_checks"] = {"verify": raw["independent_checks"]}
        claim["team"] = [
            {
                "role": "fix",
                "ok": True,
                "handler_outputs": {
                    "outputs": [{"merge_commit_sha": "b" * 40}],
                },
            },
            {"role": "verify", "attempt_id": "attempt-1", "status": "dispatching"},
        ]
        event.payload_json = json.dumps(payload)
        db.commit()
    with incident_claim_scope(raw["event_id"]):
        result = h._post_para_api_once(check_request)
    assert result["status"] == "blocked_independent_checks"
    assert client.posted_tasks == []


def test_context_budget_blocks_new_dispatch_but_allows_original_readback(monkeypatch):
    calls = []
    req = {"execution_budget": {"context_chars": 3}}
    monkeypatch.setattr(h, "para_delegate_enabled", lambda: True)
    monkeypatch.setattr(h, "_build_request", lambda **kw: req)
    monkeypatch.setattr(h, "_build_para_prompt", lambda request: "too long")
    monkeypatch.setattr(h, "_post_webhook", lambda request: calls.append(request) or {"ok": True})
    result = h.dispatch_para_delegate(task="test", employee_id="test")
    assert result["status"] == "blocked_context_budget" and not result["queued"]
    assert calls == []
    req["para_task_id"] = "original"
    assert h.dispatch_para_delegate(task="test", employee_id="test")["ok"]
    assert len(calls) == 1


def test_final_prompt_budget_checks_all_units_and_grant_before_any_post(check_request, monkeypatch):
    from modstore_server import cred_vault

    monkeypatch.setenv("MODSTORE_CREDENTIAL_TASK_GRANTS", "1")
    revoked = []
    grant_text = "Remote reader token reference: " + "r" * 600
    monkeypatch.setattr(
        cred_vault,
        "issue_task_grant",
        lambda *a, **kw: SimpleNamespace(
            task_id="attempt-1",
            prompt_line=lambda: grant_text,
        ),
    )
    monkeypatch.setattr(
        cred_vault, "revoke_task_grants", lambda task_id, **kw: revoked.append(task_id)
    )
    units = check_request["raw_input"]["independent_checks"]
    units[1]["prompt"] = "second independent check " + "u" * 2000
    with models.get_session_factory()() as db:
        event = db.get(models.IncidentEvent, check_request["raw_input"]["event_id"])
        payload = json.loads(event.payload_json)
        payload["_team_claim"]["plan"]["independent_checks"]["scout"] = units
        event.payload_json = json.dumps(payload)
        db.commit()
    check_request["execution_budget"] = {
        "context_chars": 1_000_000,
        "output_tokens": 1200,
    }
    check_request["execution_budget"]["context_chars"] = (
        len(h._build_para_prompt(check_request)) + 1000
    )
    client = _IntegClient([_online_codex("w1"), _online_codex("w2")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    with incident_claim_scope(check_request["raw_input"]["event_id"]):
        result = h._post_para_api_once(check_request)
    assert result["status"] == "blocked_context_budget"
    assert not result["accepted"] and not result["queued"]
    assert client.posted_tasks == [] and revoked == ["attempt-1"]


def test_mixed_dolt_check_group_is_rejected_before_any_child_post(check_request, monkeypatch):
    from modstore_server import cred_vault

    monkeypatch.setenv("MODSTORE_CREDENTIAL_TASK_GRANTS", "1")
    revoked = []
    monkeypatch.setattr(
        cred_vault,
        "issue_task_grant",
        lambda *a, **kw: SimpleNamespace(
            task_id="attempt-1",
            prompt_line=lambda: "credential reader reference",
        ),
    )
    monkeypatch.setattr(
        cred_vault, "revoke_task_grants", lambda task_id, **kw: revoked.append(task_id)
    )
    client = _IntegClient([_online_codex("w1"), _online_codex("w2")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    monkeypatch.setattr(
        h,
        "_resolve_dispatch_devices",
        lambda *a, **kw: (
            "test",
            [
                {"id": "w1", "_selected_tool": "codex"},
                {"id": "w2", "_selected_tool": "dolt"},
            ],
            "",
        ),
    )
    with incident_claim_scope(check_request["raw_input"]["event_id"]):
        result = h._post_para_api_once(check_request)
    assert result["status"] == "blocked_independent_checks"
    assert client.posted_tasks == [] and revoked == ["attempt-1"]


def test_preparation_failure_keeps_original_scope_and_submits_nothing(check_request, monkeypatch):
    from modstore_server import para_delegate_handler_part04 as dispatch_impl

    client = _IntegClient([_online_codex("w1"), _online_codex("w2")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **kw: client)
    prepared, saved = [], []

    def transform(req, payload, tool):
        if prepared:
            raise OSError("synthetic second payload failure")
        prepared.append(payload)
        return payload

    monkeypatch.setattr(dispatch_impl, "prepare_dolt_ticket_payload", transform)
    monkeypatch.setattr(
        h,
        "_outbox_response",
        lambda request, **kwargs: saved.append(request) or {"ok": False},
    )
    with incident_claim_scope(check_request["raw_input"]["event_id"]):
        result = h._post_para_api_once(check_request)
    assert client.posted_tasks == [] and result["submission_started"] is False
    assert saved[0]["planned_devices"] == ["w1", "w2"]
    assert saved[0]["para_payload"] == prepared[0]
    assert result["requires_reconciliation"] and not result["accepted"]
