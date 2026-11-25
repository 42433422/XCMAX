import asyncio
import json
import logging
import os
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import ValidationError

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategy_planner
from modstore_server.db.identity import User
from tests.test_strategic_portfolio import database as database
from tests.test_strategic_portfolio import limits, opportunity


def _candidate(**overrides):
    row = {
        "title": "意图准确率提升",
        "hypothesis": "补意图样本能把准确率拉到 85%",
        "metric_id": "intent_accuracy",
        "threshold": 0.85,
        "direction": "max",
        "window_days": 14,
        "kill_criteria": ["两周无提升"],
        "expected_value": 4,
        "effort": 2,
    }
    row.update(overrides)
    return row


def test_parse_plan_accepts_fenced_json():
    text = '```json\n[{"title": "a"}]\n```'
    assert strategy_planner.parse_plan(text) == [{"title": "a"}]


def test_parse_plan_returns_empty_on_garbage():
    assert strategy_planner.parse_plan("不是 JSON") == []
    assert strategy_planner.parse_plan("") == []


def test_validate_candidate_rejects():
    assert strategy_planner.validate_candidate(_candidate()) is None
    assert strategy_planner.validate_candidate(_candidate(metric_id="nope")) == "unsupported_metric"
    assert strategy_planner.validate_candidate(_candidate(window_days=0)) == "invalid_window"
    assert (
        strategy_planner.validate_candidate(_candidate(kill_criteria=[])) == "invalid_kill_criteria"
    )
    assert strategy_planner.validate_candidate(_candidate(effort=9)) == "invalid_effort"


def test_rank_prefers_value_per_effort_and_drops_invalid():
    high = _candidate(title="high", expected_value=5, effort=1)
    low = _candidate(title="low", expected_value=2, effort=5)
    broken = _candidate(title="broken", metric_id="nope")
    ranked = strategy_planner.rank_candidates([low, broken, high])
    assert [row["title"] for row in ranked] == ["high", "low"]


def test_fit_envelope_stops_at_capacity():
    rows = [_candidate(title=f"c{i}") for i in range(3)]
    envelope = {"proposals": 2, "tokens": 100, "ci_minutes": 10, "human_hours": 2}
    kept = strategy_planner.fit_envelope(rows, envelope, [])
    assert len(kept) == 2
    assert all(row["budget"]["proposals"] >= 1 for row in kept)


def test_fallback_picks_real_domain_gap(monkeypatch):
    from modstore_server import strategy_bets

    monkeypatch.setattr(
        strategy_bets,
        "read_metric",
        lambda metric: 0.0 if metric == strategy_bets.DOMAIN_METRIC else None,
    )
    context = {
        "assets": {"status": "unknown"},
        "repo": {"status": "ok"},
        "domains": {"status": "ok"},
    }
    rows = strategy_planner.fallback_candidates(context)
    assert len(rows) == 1
    assert rows[0]["metric_id"] == strategy_bets.DOMAIN_METRIC
    assert rows[0]["window_days"] == 30


def test_fallback_returns_empty_when_targets_met(monkeypatch):
    from modstore_server import strategy_bets

    monkeypatch.setattr(
        strategy_bets,
        "read_metric",
        lambda metric: 1.0 if metric == strategy_bets.DOMAIN_METRIC else None,
    )
    rows = strategy_planner.fallback_candidates(
        {"assets": {"status": "unknown"}, "repo": {"status": "ok"}, "domains": {"status": "ok"}}
    )
    assert rows == []


def test_new_bet_id_is_deterministic_and_valid():
    first = strategy_planner._new_bet_id("意图准确率提升")
    second = strategy_planner._new_bet_id("意图准确率提升")
    assert first == second
    assert first.startswith("bet-")
    assert len(first) <= 64


def test_legacy_dispatch_never_turns_a_draft_into_external_work():
    row = {
        **_candidate(),
        "bet_id": "bet-test",
        "status": "proposed",
        "budget": {"tokens": 1000000},
    }
    assert strategy_planner.dispatch_bet(row)["status"] == "blocked"
    assert strategy_planner.dispatch_open_bets() == []


def test_plan_strategy_without_operator_template_does_not_self_authorize(monkeypatch):
    monkeypatch.delenv("MODSTORE_STRATEGY_DISCOVERY_TEMPLATE", raising=False)
    result = strategy_planner.plan_strategy()
    assert result["status"] == "not_configured"
    assert result["registered"] == result["dispatched"] == []


@pytest.mark.parametrize("command", ["plan", "context"])
def test_cli_reports_counts_without_private_results(monkeypatch, capsys, command):
    result = {
        "ok": True,
        "status": "private-status-sentinel",
        "dry_run": True,
        "candidates": [{"title": "private-title-sentinel"}],
        "registered": ["private-decision-sentinel"],
        "dispatched": [],
        "evidence": {"owner_user_id": 7, "task": "private-task-sentinel"},
        "active_bets": ["private-bet-sentinel"],
        "domains": {"domains": [{"source": "private-evidence-sentinel"}]},
    }
    original = deepcopy(result)
    monkeypatch.setattr(strategy_planner, "plan_strategy", lambda **_kwargs: result)
    monkeypatch.setattr(strategy_planner, "collect_context", lambda: result)
    assert strategy_planner._main([command]) == 0
    output = capsys.readouterr().out
    assert "private-" not in output
    assert json.loads(output) == {
        "ok": True,
        "status": "unknown",
        "dry_run": True,
        "candidate_count": 1,
        "registered_count": 1,
        "dispatched_count": 0,
        "active_bet_count": 1,
        "domain_count": 1,
    }
    assert result == original


def test_cli_failure_does_not_print_private_validation_input(monkeypatch, capsys):
    def fail(**_kwargs):
        raise ValueError("private-goal-sentinel")

    monkeypatch.setattr(strategy_planner, "plan_strategy", fail)
    assert strategy_planner._main(["plan"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "ok": False,
        "status": "requires_reconciliation",
        "dry_run": False,
    }
    assert "private-" not in output.out + output.err


def test_scheduled_plan_logs_only_summary_and_keeps_private_result(monkeypatch, caplog):
    from modstore_server import workflow_scheduler, workflow_scheduler_startup_phase04

    jobs = {}
    monkeypatch.setattr(
        workflow_scheduler,
        "_scheduler",
        SimpleNamespace(
            add_job=lambda fn, _trigger, **kwargs: jobs.update({kwargs["id"]: fn}),
        ),
    )
    monkeypatch.setattr(workflow_scheduler, "_run_tracked_scheduler_job", lambda _id, fn: fn())
    result = {
        "ok": True,
        "status": "awaiting_approval",
        "candidates": [{"task": "private-task-sentinel"}],
        "registered": ["private-decision-sentinel"],
        "dispatched": [],
        "evidence": "private-evidence-sentinel",
    }
    original = deepcopy(result)
    monkeypatch.setattr(strategy_planner, "plan_strategy", lambda: result)
    workflow_scheduler_startup_phase04._register_scheduler_phase_04()
    caplog.clear()
    caplog.set_level(logging.INFO, logger=workflow_scheduler.logger.name)
    jobs["strategy_planner"]()
    assert "registered_count" in caplog.text and "awaiting_approval" in caplog.text
    assert "private-" not in caplog.text
    assert result == original

    def fail():
        raise ValueError("private-invalid-template-sentinel")

    monkeypatch.setattr(strategy_planner, "plan_strategy", fail)
    jobs["strategy_planner"]()
    assert "strategy planner job failed" in caplog.text
    assert "private-" not in caplog.text


@pytest.fixture(params=["input_data", "goal", "expires_at"])
def invalid_private_template(request, tmp_path, monkeypatch):
    private = "private-template-sentinel"
    template = {
        "owner_user_id": 7,
        "goal": "Improve delivery",
        "limits": limits(),
        "period_days": 7,
        "use_llm": False,
    }
    if request.param == "input_data":
        template["input_data"] = {str(index): private for index in range(65)}
        location, error_type = ("input_data",), "too_long"
    elif request.param == "goal":
        template["goal"] = private * 200
        location, error_type = ("goal",), "string_too_long"
    else:
        template["limits"]["expires_at"] = private
        location, error_type = ("limits",), "value_error"
    path = tmp_path / "strategy-template.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_STRATEGY_DISCOVERY_TEMPLATE", str(path))
    return template, private, location, error_type


def test_scheduled_discovery_rejects_private_invalid_template_without_echo(
    invalid_private_template,
):
    template, private, location, error_type = invalid_private_template
    with pytest.raises(ValidationError) as failure:
        asyncio.run(strategy_planner.run_scheduled_discovery(template=template))
    diagnostic = str(failure.value)
    assert private not in diagnostic and location[0] in diagnostic
    errors = failure.value.errors(include_input=False)
    assert len(errors) == 1
    assert errors[0]["loc"] == location and errors[0]["type"] == error_type
    if location == ("limits",):
        assert "invalid ISO timestamp" in diagnostic


def test_strategy_cli_keeps_validation_failure_without_private_input(invalid_private_template):
    _, private, location, _ = invalid_private_template
    result = subprocess.run(
        [sys.executable, "-m", "modstore_server.strategy_planner", "plan"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "ok": False,
        "status": "requires_reconciliation",
        "dry_run": False,
    }
    assert private not in result.stdout + result.stderr


def test_registered_strategy_job_records_safe_validation_failure(
    database, invalid_private_template, monkeypatch, caplog
):
    from modstore_server import models, workflow_scheduler
    from modstore_server.db.scheduler_ops import JobRun
    from modstore_server.workflow_scheduler_startup_phase04 import _register_scheduler_phase_04

    _, private, location, error_type = invalid_private_template
    monkeypatch.setattr(models, "get_session_factory", lambda: database)
    scheduler = BackgroundScheduler()
    monkeypatch.setattr(workflow_scheduler, "_scheduler", scheduler)
    _register_scheduler_phase_04()
    with caplog.at_level(logging.ERROR, logger=workflow_scheduler.logger.name):
        scheduler.get_job("strategy_planner").func()
    assert "strategy planner job failed" in caplog.text
    assert private not in caplog.text
    with database() as session:
        run = session.query(JobRun).filter_by(job_id="strategy_planner").one()
        assert run.status == "failed" and run.finished_at
        assert location[0] in run.error and f"type={error_type}" in run.error
        assert private not in run.error


def test_scheduled_plan_is_sql_proposal_then_authenticated_approval_and_execution(
    database, tmp_path, monkeypatch
):
    with database() as session:
        session.add(User(id=7, username="strategy-admin", password_hash="unused", is_admin=True))
        session.commit()
    observations = []

    async def discover(**kwargs):
        observations.append(kwargs)
        return {"source": "observed_owner_metrics", "opportunities": [opportunity()]}

    monkeypatch.setattr(runtime, "discover_portfolio_opportunities", discover)
    template = tmp_path / "strategy-template.json"
    template.write_text(
        json.dumps(
            {
                "owner_user_id": 7,
                "goal": "Improve delivery",
                "limits": limits(),
                "period_days": 7,
                "use_llm": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_STRATEGY_DISCOVERY_TEMPLATE", str(template))
    ledger = tmp_path / "legacy.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger))

    first = strategy_planner.plan_strategy()
    repeated = strategy_planner.plan_strategy()
    assert first["status"] == "awaiting_approval" and first["dispatched"] == []
    assert first["registered"] == repeated["registered"] and repeated["idempotent"]
    assert len(observations) == 1 and observations[0]["owner_user_id"] == 7
    decision_id = first["registered"][0]
    before = portfolio.portfolio_status(decision_id, owner_user_id=7)
    assert before["status"] == "proposed" and not before.get("authorization")
    with pytest.raises(portfolio.PortfolioError):
        runtime.run_portfolio_cycle(decision_id, owner_user_id=7)

    portfolio.authorize_portfolio(
        decision_id,
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=first["proposal_sha256"],
    )
    executions = []

    def execute(task):
        executions.append(task)
        return {"ok": True, "status": "completed", "output": "local fixture result"}

    monkeypatch.setattr(runtime, "_execute", execute)
    state = runtime.run_portfolio_cycle(decision_id, owner_user_id=7)
    assert len(executions) == 1 and state["tasks"]["a"]["status"] == "completed"
    assert not ledger.exists()


def test_historical_domain_aliases_retain_unrated_status_without_stale_gaps(tmp_path, monkeypatch):
    from modstore_server import strategy_planner

    report = tmp_path / "domain.json"
    report.write_text(
        json.dumps(
            {
                "audited_at": "2026-11-15T00:00:00+00:00",
                "source": "historical-3396",
                "domains": [
                    {
                        "domain_id": "di-layering",
                        "status": "UNRATED",
                        "score": 9,
                        "blocking_gap": "outdated gap must not become current evidence",
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("MODSTORE_DOMAIN_AUDIT_PATH", str(report))
    context = strategy_planner._domain_status()
    assert context["domains"][0]["domain_id"] == "architecture"
    assert context["domains"][0]["score"] is None
    assert context["audited_at"].startswith("2026-11-15")
    assert "blocking_gap" not in json.dumps(context)


@pytest.fixture
def private_market_context(monkeypatch):
    context = {
        "assets": {"status": "unknown"},
        "repo": {"status": "ok"},
        "domains": {"status": "unknown"},
        "market": {
            "queries": [
                {
                    "query_id": "query-1",
                    "domain_id": "customer-service",
                    "acceptance_target": 0.9,
                    "window_days": 14,
                    "employee_id": "private-employee-sentinel",
                    "customer_goal_ids": ["private-customer-goal"],
                }
            ],
            "evidence": [
                {
                    "query_id": "query-1",
                    "evidence_id": "evidence-1",
                    "title": "private-market-observation",
                }
            ],
        },
        "active_bets": ["private-active-bet"],
    }
    monkeypatch.setattr(strategy_planner, "collect_context", lambda: context)
    monkeypatch.setattr(strategy_planner.strategy_bets, "read_metric", lambda _: None)
    return context


@pytest.mark.parametrize("command", ["plan", "context"])
def test_cli_summary_keeps_private_market_data_in_internal_result(
    private_market_context, capsys, command
):
    result = strategy_planner.plan_strategy(dry_run=True)
    assert result["candidates"][0]["employee_id"] == "private-employee-sentinel"
    assert result["candidates"][0]["customer_goal_ids"] == ["private-customer-goal"]
    assert strategy_planner._main([command, "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "private-" not in output
    summary = json.loads(output)
    assert summary["ok"] is True
    if command == "plan":
        assert summary["candidate_count"] == 1
    else:
        assert "candidate_count" not in summary
        assert summary["active_bet_count"] == 1


def test_registered_strategy_job_logs_counts_without_market_candidate_payload(
    private_market_context, monkeypatch, caplog
):
    from modstore_server import workflow_scheduler as scheduler
    from modstore_server.workflow_scheduler_startup_phase04 import _register_scheduler_phase_04

    result = strategy_planner.plan_strategy(dry_run=True)
    assert result["candidates"][0]["employee_id"] == "private-employee-sentinel"
    registered = {}
    tracked = []

    def add_job(func, *args, **kwargs):
        registered[kwargs["id"]] = func

    def run_tracked(name, callback):
        tracked.append(name)
        return callback()

    monkeypatch.setattr(scheduler, "_scheduler", SimpleNamespace(add_job=add_job))
    monkeypatch.setattr(scheduler, "_run_tracked_scheduler_job", run_tracked)
    monkeypatch.setattr(strategy_planner, "plan_strategy", lambda: result)
    _register_scheduler_phase_04()
    with caplog.at_level(logging.INFO, logger=scheduler.__name__):
        registered["strategy_planner"]()
    assert tracked == ["strategy_planner"]
    assert "private-" not in caplog.text
    records = [record for record in caplog.records if record.msg == "strategy plan: %s"]
    assert len(records) == 1
    assert records[0].args["candidate_count"] == 1
