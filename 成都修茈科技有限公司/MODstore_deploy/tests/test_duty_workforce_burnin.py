from __future__ import annotations

import asyncio

from modstore_server import duty_workforce_burnin as burnin
from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner


def _manifest(*handlers: str) -> dict:
    return {
        "id": "test-employee",
        "employee_config_v2": {
            "perception": {"type": "text"},
            "memory": {"type": "session"},
            "cognition": {"system_prompt": "test"},
            "actions": {
                "handlers": list(handlers),
                "agent": {"workspace": {"read_only": False}},
            },
        },
    }


def _contract(employee_id: str, *, risk: str = "low", mission: str = "只读巡检") -> dict:
    return {
        "employee_id": employee_id,
        "mission": mission,
        "mode": "execute",
        "risk_level": risk,
        "trigger": {"cron": "0 * * * *"},
        "acceptance": ["保留真实证据"],
    }


def _accepted_execution() -> dict:
    return {
        "duration_ms": 12.0,
        "executed_at": "2026-07-22T00:00:00+00:00",
        "result": {
            "outputs": [
                {
                    "handler": "agent",
                    "ok": True,
                    "summary": "根据真实目录扫描完成只读巡检",
                    "tool_calls_count": 1,
                    "tool_call_kinds": ["analyze_project_summary"],
                    "tool_call_success_count": 1,
                    "tool_call_failure_count": 0,
                    "change_request_ids": [],
                }
            ],
            "verification": {"passed": True, "summary": "3 项检查通过"},
            "change_request_bridge": {
                "ok": True,
                "suppressed": True,
                "change_request_ids": [],
            },
        },
        "change_request_ids": [],
    }


def _direct_manifest(*, policy: dict | None = None) -> dict:
    manifest = {
        "id": "safe-direct",
        "employee_config_v2": {
            "perception": {"type": "text"},
            "memory": {"type": "session"},
            "cognition": {"system_prompt": "test"},
            "actions": {
                "handlers": ["direct_python"],
                "direct_python": {
                    "module": "safe_direct",
                    "implementation": "employee_module",
                    "execution_mode": "deterministic",
                    "read_only": True,
                    "input_schema": {
                        "type": "object",
                        "required": ["record"],
                    },
                    "output_schema": {
                        "type": "object",
                        "required": [
                            "ok",
                            "status",
                            "summary",
                            "evidence",
                            "read_only",
                            "side_effects",
                        ],
                    },
                    "burn_in_fixture": {"record": {"id": "fixture"}},
                },
            },
        },
    }
    if policy is not None:
        manifest["employee_config_v2"]["actions"]["direct_python"]["burn_in_policy"] = policy
    return manifest


def _accepted_direct_execution() -> dict:
    return {
        "result": {
            "outputs": [
                {
                    "handler": "direct_python",
                    "ok": True,
                    "output": {
                        "ok": True,
                        "status": "success",
                        "summary": "Deterministic fixture was audited without mutation.",
                        "evidence": ["input.record"],
                        "read_only": True,
                        "side_effects": [],
                    },
                }
            ],
            "verification": {"passed": True, "summary": "all checks passed"},
            "change_request_bridge": {"ok": True, "suppressed": True},
        },
        "change_request_ids": [],
    }


def test_plan_only_selects_unproven_low_risk_real_read_only_capability(
    monkeypatch,
) -> None:
    contracts = {
        "safe-agent": _contract("safe-agent"),
        "already-proven": _contract("already-proven"),
        "generic-shell": _contract("generic-shell"),
        "payment-worker": _contract("payment-worker", mission="支付对账"),
        "high-risk": _contract("high-risk", risk="high"),
        "external-message": _contract("external-message", mission="发送客服消息"),
        "shell-handler": _contract("shell-handler"),
    }
    manifests = {
        "safe-agent": _manifest("agent"),
        "already-proven": _manifest("agent"),
        "generic-shell": _manifest("llm_md", "echo"),
        "payment-worker": _manifest("agent"),
        "high-risk": _manifest("agent"),
        "external-message": _manifest("agent"),
        "shell-handler": _manifest("agent", "shell_exec"),
    }
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", "8")

    plan = burnin.build_burn_in_plan(
        limit=8,
        _contracts=contracts,
        _manifests=manifests,
        _proven_ids={"already-proven"},
        _recent_ids=set(),
    )

    assert [row["employee_id"] for row in plan["candidates"]] == ["safe-agent"]
    assert len(plan["candidates"][0]["manifest_sha256"]) == 64
    assert len(plan["candidates"][0]["contract_sha256"]) == 64
    assert plan["estimated_new_receipts"] == 1
    assert plan["max_eventual_new_receipts"] == 1
    reasons = {row["employee_id"]: row["reason"] for row in plan["skipped"]}
    assert reasons["already-proven"] == "fresh_receipt_exists"
    assert reasons["generic-shell"] == "no_safe_executable_handler"
    assert reasons["payment-worker"].startswith("prohibited_semantics")
    assert reasons["external-message"].startswith("prohibited_semantics")
    assert reasons["high-risk"] == "risk_not_low:high"
    assert reasons["shell-handler"] == "dangerous_handler:shell_exec"


def test_plan_accepts_only_fully_declared_read_only_direct_python_contract(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", "2")
    contracts = {
        "safe-direct": _contract("safe-direct"),
        "undeclared-direct": _contract("undeclared-direct"),
    }
    manifests = {
        "safe-direct": _direct_manifest(),
        "undeclared-direct": _manifest("direct_python"),
    }

    plan = burnin.build_burn_in_plan(
        limit=2,
        _contracts=contracts,
        _manifests=manifests,
        _proven_ids=set(),
        _recent_ids=set(),
    )

    assert [row["employee_id"] for row in plan["candidates"]] == ["safe-direct"]
    assert plan["candidates"][0]["capability_handlers"] == ["direct_python"]
    assert plan["candidates"][0]["burn_in_fixture"] == {"record": {"id": "fixture"}}
    reasons = {row["employee_id"]: row["reason"] for row in plan["skipped"]}
    assert reasons["undeclared-direct"] == "direct_python_input_not_declared"


def test_explicit_burn_in_handlers_preserve_normal_employee_runtime(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", "1")
    manifest = _direct_manifest()
    actions = manifest["employee_config_v2"]["actions"]
    actions["handlers"] = ["agent", "specialized", "llm_md", "echo"]
    actions["burn_in_handlers"] = ["direct_python"]
    actions["agent"] = {"workspace": {"read_only": False}}

    plan = burnin.build_burn_in_plan(
        limit=1,
        _contracts={"safe-direct": _contract("safe-direct")},
        _manifests={"safe-direct": manifest},
        _proven_ids=set(),
        _recent_ids=set(),
    )

    candidate = plan["candidates"][0]
    assert actions["handlers"] == ["agent", "specialized", "llm_md", "echo"]
    assert candidate["handlers"] == actions["handlers"]
    assert candidate["capability_handlers"] == ["direct_python"]
    assert candidate["burn_in_fixture"] == {"record": {"id": "fixture"}}


def test_changed_reviewed_manifest_bypasses_attempt_cooldown(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", "2")
    contract = _contract("safe-direct")
    manifest = _direct_manifest()
    current_sha = burnin._payload_sha256(manifest)

    unchanged = burnin.build_burn_in_plan(
        limit=2,
        _contracts={"safe-direct": contract},
        _manifests={"safe-direct": manifest},
        _proven_ids=set(),
        _recent_ids={"safe-direct"},
        _recent_manifest_shas={"safe-direct": {current_sha}},
    )
    changed = burnin.build_burn_in_plan(
        limit=2,
        _contracts={"safe-direct": contract},
        _manifests={"safe-direct": manifest},
        _proven_ids=set(),
        _recent_ids={"safe-direct"},
        _recent_manifest_shas={"safe-direct": {"a" * 64}},
    )

    assert unchanged["candidates"] == []
    assert unchanged["skipped"] == [{"employee_id": "safe-direct", "reason": "attempt_cooldown"}]
    assert [row["employee_id"] for row in changed["candidates"]] == ["safe-direct"]


def test_medium_risk_is_eligible_only_for_reviewed_read_only_direct_python(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", "8")
    contracts = {
        "medium-direct": _contract("medium-direct", risk="medium"),
        "medium-agent": _contract("medium-agent", risk="medium"),
        "high-direct": _contract("high-direct", risk="high"),
    }
    manifests = {
        "medium-direct": _direct_manifest(),
        "medium-agent": _manifest("agent"),
        "high-direct": _direct_manifest(),
    }

    plan = burnin.build_burn_in_plan(
        limit=8,
        _contracts=contracts,
        _manifests=manifests,
        _proven_ids=set(),
        _recent_ids=set(),
    )

    assert [row["employee_id"] for row in plan["candidates"]] == ["medium-direct"]
    assert plan["candidates"][0]["risk_level"] == "medium"
    assert plan["safety"]["medium_risk_read_only_direct"] is True
    assert plan["safety"]["medium_or_high_risk_side_effects"] is False
    reasons = {row["employee_id"]: row["reason"] for row in plan["skipped"]}
    assert reasons["medium-agent"] == "risk_not_low:medium"
    assert reasons["high-direct"] == "risk_not_low:high"


def test_sensitive_or_high_risk_direct_requires_explicit_fixture_only_policy(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", "8")
    reviewed = {
        "reviewed": True,
        "scope": "fixture_only",
        "external_effects": False,
        "allow_prohibited_semantics_fixture": True,
        "allow_high_risk_fixture": True,
    }
    contracts = {
        "sensitive-denied": _contract("sensitive-denied", mission="支付核对"),
        "sensitive-reviewed": _contract("sensitive-reviewed", mission="支付核对"),
        "high-reviewed": _contract("high-reviewed", risk="high"),
    }
    manifests = {
        "sensitive-denied": _direct_manifest(),
        "sensitive-reviewed": _direct_manifest(policy=reviewed),
        "high-reviewed": _direct_manifest(policy=reviewed),
    }

    plan = burnin.build_burn_in_plan(
        limit=8,
        _contracts=contracts,
        _manifests=manifests,
        _proven_ids=set(),
        _recent_ids=set(),
    )

    assert [row["employee_id"] for row in plan["candidates"]] == [
        "high-reviewed",
        "sensitive-reviewed",
    ]
    assert plan["safety"]["high_risk_read_only_direct"] is True
    assert plan["safety"]["prohibited_semantics_fixture_override"] is True
    reasons = {row["employee_id"]: row["reason"] for row in plan["skipped"]}
    assert reasons["sensitive-denied"].startswith("prohibited_semantics")


def test_acceptance_rejects_empty_or_mutating_agent_receipts() -> None:
    accepted = burnin.validate_burn_in_execution_result(_accepted_execution())
    assert accepted["passed"] is True

    bad = _accepted_execution()
    output = bad["result"]["outputs"][0]
    output["tool_call_kinds"] = ["write_workspace_file"]
    output["tool_call_success_count"] = 0
    output["tool_call_failure_count"] = 1
    rejected = burnin.validate_burn_in_execution_result(bad)
    assert rejected["passed"] is False
    assert "non_read_only_tool_attempted" in rejected["reasons"]
    assert "no_successful_read_only_observation" in rejected["reasons"]

    llm_ops = _accepted_execution()
    llm_ops["result"]["outputs"][0]["tool_call_kinds"] = ["list_available_ai_routes"]
    assert burnin.validate_burn_in_execution_result(llm_ops)["passed"] is True

    explored = _accepted_execution()
    explored_output = explored["result"]["outputs"][0]
    explored_output["tool_call_kinds"] = [
        "read_workspace_file",
        "analyze_project_summary",
    ]
    explored_output["tool_call_success_count"] = 1
    explored_output["tool_call_failure_count"] = 1
    explored_result = burnin.validate_burn_in_execution_result(explored)
    assert explored_result["passed"] is True
    assert explored_result["tool_call_failure_count"] == 1
    assert explored_result["tool_call_kinds"] == [
        "analyze_project_summary",
        "read_workspace_file",
    ]


def test_acceptance_requires_strict_read_only_direct_python_receipt() -> None:
    accepted = burnin.validate_burn_in_execution_result(_accepted_direct_execution())
    assert accepted["passed"] is True
    assert accepted["direct_python_receipt_count"] == 1

    mutated = _accepted_direct_execution()
    mutated["result"]["outputs"][0]["output"]["side_effects"] = ["wrote file"]
    rejected = burnin.validate_burn_in_execution_result(mutated)
    assert rejected["passed"] is False
    assert "direct_python_side_effects_present" in rejected["reasons"]


def test_direct_burn_in_task_does_not_claim_full_role_acceptance() -> None:
    task = burnin._candidate_direct_task("market-frontend-dev", "[marker]")
    assert "确定性只读子能力" in task
    assert "完整岗位" in task
    assert "测试通过" not in task
    assert "发布" in task


def test_run_defaults_to_dry_run_when_runtime_switch_is_off(monkeypatch) -> None:
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BURN_IN_ENABLED", raising=False)
    plan = {"ok": True, "dry_run": True, "candidates": [{"employee_id": "safe-agent"}]}

    result = burnin.run_burn_in(
        dry_run=False,
        _plan=plan,
        _executor=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert result["execution_blocked"] is True
    assert result["dry_run"] is True


def test_enabled_run_is_bounded_and_keeps_only_accepted_receipt(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", "1")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BURN_IN_AUDIT_PATH", str(tmp_path / "burnin.jsonl"))
    monkeypatch.setattr(burnin, "_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        "modstore_server.services.llm.resolve_platform_bench_llm",
        lambda: ("minimax", "MiniMax-M2.7"),
    )
    calls = []

    def fake_executor(employee_id, task, payload, user_id=0, *, bench_llm_override=None):
        calls.append((employee_id, task, payload, user_id, bench_llm_override))
        return _accepted_execution()

    plan = {
        "ok": True,
        "dry_run": True,
        "candidates": [
            {
                "employee_id": "safe-agent",
                "mission": "只读巡检",
                "mode": "execute",
                "risk_level": "low",
                "acceptance": ["真实证据"],
            },
            {
                "employee_id": "must-be-deferred",
                "mission": "只读巡检",
                "mode": "execute",
                "risk_level": "low",
                "acceptance": ["真实证据"],
            },
        ],
    }

    result = burnin.run_burn_in(dry_run=False, _plan=plan, _executor=fake_executor)

    assert result["accepted_receipt_count"] == 1
    assert result["selected_count"] == 1
    assert len(calls) == 1
    payload = calls[0][2]
    assert payload["burn_in_read_only"] is True
    assert float(payload["burn_in_deadline_epoch"]) > 0
    assert payload["suppress_employee_im"] is True
    assert payload["suppress_handoff"] is True
    assert payload["suppress_change_requests"] is True
    assert payload["allow_medium_risk"] is False
    assert calls[0][4] == ("minimax", "MiniMax-M2.7")
    assert (tmp_path / "burnin.jsonl").read_text(encoding="utf-8").count("\n") == 2


def test_agent_runner_enforces_read_only_tool_boundary(tmp_path) -> None:
    (tmp_path / "proof.txt").write_text("proof", encoding="utf-8")
    runner = EmployeeAgentRunner(
        {"read_only": True, "workspace_root": str(tmp_path)},
        workspace_root=str(tmp_path),
    )

    blocked = asyncio.run(
        runner._dispatch_tool(
            "write_workspace_file",
            {"path": "should-not-exist.txt", "content": "forbidden"},
        )
    )
    observed = asyncio.run(runner._dispatch_tool("read_workspace_file", {"path": "proof.txt"}))

    assert blocked["ok"] is False
    assert blocked["blocked"] is True
    assert not (tmp_path / "should-not-exist.txt").exists()
    assert observed["ok"] is True
    assert observed["content"] == "proof"
