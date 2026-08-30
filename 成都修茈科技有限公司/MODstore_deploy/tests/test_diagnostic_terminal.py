from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _factory():
    from modstore_server.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _runtime(*, failing: bool = False):
    state = "failing" if failing else "healthy"
    return {
        "ok": not failing,
        "status": "degraded" if failing else "healthy",
        "summary": {
            "actionable_failing": int(failing),
            "actionable_stale": 0,
            "deferred": 0,
        },
        "jobs": [
            {
                "job_id": "daily_digest",
                "state": state,
                "last_status": "failed" if failing else "success",
                "last_error_code": "digest_timeout" if failing else "",
                "consecutive_failures": 2 if failing else 0,
            }
        ],
    }


def _seed(db):
    from modstore_server.models import (
        IncidentEvent,
        OutboxDeadLetter,
        PlanTemplate,
        UpdateInstallationReceipt,
        User,
        UserPlan,
    )

    user = User(
        username="terminal_customer",
        email="terminal@example.com",
        password_hash="x",
        is_enterprise=True,
        account_state="active",
    )
    db.add(user)
    db.flush()
    db.add(
        PlanTemplate(
            id="saas-permanent-growth",
            name="企业成长版",
            price=0,
            is_active=True,
        )
    )
    db.add(
        UserPlan(
            user_id=user.id,
            plan_id="saas-permanent-growth",
            is_active=True,
            started_at=datetime.now(UTC),
        )
    )
    db.add(
        IncidentEvent(
            event_type="runtime.error",
            source="pytest",
            payload_json=('{"severity":"high","error":"token=top-secret-value connection failed"}'),
        )
    )
    db.add(
        OutboxDeadLetter(
            event_id="event-terminal-1",
            event_name="customer.sync",
            producer="pytest",
            attempts=3,
            last_error="Bearer abcdefghijklmnop rejected",
        )
    )
    db.add(
        UpdateInstallationReceipt(
            user_id=user.id,
            installation_id="terminal-installation-0000000001",
            idempotency_key="terminal-receipt-00000000000001",
            status="failed",
            error="download timeout",
            source="desktop_inventory",
        )
    )
    db.commit()
    return user


def test_parser_is_allowlisted_bounded_and_suggests_commands():
    from modstore_server.diagnostic_terminal import DiagnosticTerminalError, parse_command

    parsed = parse_command('find "首次 登录" --limit 12')
    assert parsed.name == "find"
    assert parsed.query == "首次 登录"
    assert parsed.limit == 12
    assert parse_command("体检").name == "doctor"

    with pytest.raises(DiagnosticTerminalError, match="未知命令"):
        parse_command("docter")
    with pytest.raises(DiagnosticTerminalError, match="1–200"):
        parse_command("logs --limit 201")
    with pytest.raises(DiagnosticTerminalError, match="不支持的选项"):
        parse_command("logs --path /etc/passwd")


def test_doctor_finds_real_problem_sources_and_redacts_secrets():
    from modstore_server.diagnostic_terminal import execute_diagnostic_command
    from modstore_server.models import CommerceAdminAction, Transaction

    factory = _factory()
    with factory() as db:
        _seed(db)
        commerce_before = db.query(CommerceAdminAction).count()
        transaction_before = db.query(Transaction).count()
        result = execute_diagnostic_command(
            db,
            "doctor",
            runtime_provider=lambda: _runtime(failing=True),
        )
        assert result["ok"] is True
        assert result["read_only"] is True
        assert result["status"] == "degraded"
        assert result["metrics"]["database"] == "ok"
        assert result["metrics"]["scheduler_failing"] == 1
        assert result["metrics"]["unresolved_dlq"] == 1
        assert result["metrics"]["pending_install"] == 1
        rendered = str(result)
        assert "top-secret-value" not in rendered
        assert "abcdefghijklmnop" not in rendered
        assert "[REDACTED]" in rendered
        assert db.query(CommerceAdminAction).count() == commerce_before
        assert db.query(Transaction).count() == transaction_before


def test_doctor_does_not_report_historical_failures_as_current_problems():
    from modstore_server.diagnostic_terminal import execute_diagnostic_command
    from modstore_server.models import IncidentEvent, UpdateInstallationReceipt

    factory = _factory()
    with factory() as db:
        _seed(db)
        old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
        db.query(IncidentEvent).update({IncidentEvent.created_at: old})
        db.query(UpdateInstallationReceipt).update({UpdateInstallationReceipt.reported_at: old})
        db.commit()

        result = execute_diagnostic_command(
            db,
            "doctor",
            runtime_provider=lambda: _runtime(),
        )

        assert result["metrics"]["system_events_24h"] == 0
        assert not any(row["kind"] == "incident" for row in result["items"])
        assert not any(row["kind"] == "installation" for row in result["items"])


def test_account_find_delivery_routes_and_cli_share_the_same_service():
    from modstore_server.diagnostic_terminal import execute_diagnostic_command
    from modstore_server.diagnostic_terminal_cli import run

    factory = _factory()
    with factory() as db:
        user = _seed(db)
        account = execute_diagnostic_command(
            db,
            "account terminal_customer",
            runtime_provider=lambda: _runtime(),
        )
        assert account["items"][0]["data"]["active_plans"][0]["plan_id"] == (
            "saas-permanent-growth"
        )
        assert account["items"][0]["data"]["deliveries"][0]["status"] == "pending_install"

        found = execute_diagnostic_command(
            db,
            "find terminal",
            route_catalog=[
                {
                    "path": "/api/admin/diagnostic-terminal/execute",
                    "methods": ["POST"],
                    "name": "execute",
                }
            ],
            runtime_provider=lambda: _runtime(),
        )
        kinds = {entry["kind"] for entry in found["items"]}
        assert {"account", "delivery", "route"} <= kinds
        assert any(entry["reference"] == f"user:{user.id}" for entry in found["items"])

    cli_result = run(
        ["account", "terminal_customer", "--json"],
        session_factory=factory,
        runtime_provider=lambda: _runtime(),
    )
    assert cli_result["command"] == "account"
    assert cli_result["items"][0]["title"] == "terminal_customer"


def test_logs_only_read_controlled_paths_and_scrub_credentials(tmp_path, monkeypatch):
    from modstore_server.diagnostic_terminal import execute_diagnostic_command

    log_path = tmp_path / "nginx-error.log"
    log_path.write_text(
        "warning harmless\nerror password=hunter2 Bearer secret-token-123456\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPS_NGINX_ERROR_LOG", str(log_path))
    factory = _factory()
    with factory() as db:
        result = execute_diagnostic_command(
            db,
            "logs error",
            runtime_provider=lambda: _runtime(),
        )
    assert len(result["items"]) == 1
    assert result["items"][0]["source"] == "controlled_log:nginx-error.log"
    assert "hunter2" not in str(result)
    assert "secret-token-123456" not in str(result)
    assert "[REDACTED]" in str(result)


def test_admin_api_is_registered_authenticated_and_returns_runtime_routes(client):
    from modstore_server.api.app_factory import _iter_route_method_signatures
    from modstore_server.api.deps import require_admin

    signatures = set(_iter_route_method_signatures(client.app.routes))
    assert ("/api/admin/diagnostic-terminal/commands", "GET") in signatures
    assert ("/api/admin/diagnostic-terminal/execute", "POST") in signatures
    assert (
        client.post(
            "/api/admin/diagnostic-terminal/execute", json={"command": "doctor"}
        ).status_code
        == 401
    )

    client.app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id=1, username="admin", is_admin=True
    )
    try:
        commands = client.get("/api/admin/diagnostic-terminal/commands")
        assert commands.status_code == 200
        assert len(commands.json()["items"]) >= 10
        routes = client.post(
            "/api/admin/diagnostic-terminal/execute",
            json={"command": "routes diagnostic-terminal"},
        )
        assert routes.status_code == 200, routes.text
        assert any(
            row["reference"] == "/api/admin/diagnostic-terminal/execute"
            for row in routes.json()["items"]
        )
        bad = client.post(
            "/api/admin/diagnostic-terminal/execute",
            json={"command": "shell rm"},
        )
        assert bad.status_code == 422
    finally:
        client.app.dependency_overrides.pop(require_admin, None)


def test_cli_refuses_an_implicit_default_sqlite(monkeypatch):
    from modstore_server import diagnostic_terminal_cli as cli
    from modstore_server.diagnostic_terminal import DiagnosticTerminalError

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MODSTORE_DB_PATH", raising=False)
    monkeypatch.delenv("MODSTORE_PYTEST_USE_SQLITE", raising=False)
    monkeypatch.setattr(cli, "load_operator_environment", lambda _env_file="": [])
    with pytest.raises(DiagnosticTerminalError, match="默认本地 SQLite"):
        cli.run(["doctor"])


def test_cli_returns_a_safe_validation_exit_for_non_admin_actor(monkeypatch, capsys):
    from modstore_server import diagnostic_terminal_cli as cli
    from modstore_server.entitlement_fast_lane import FastLaneForbidden

    def _forbidden(_argv):
        raise FastLaneForbidden("操作人不是管理员：customer")

    monkeypatch.setattr(cli, "run", _forbidden)

    assert cli.main(["doctor", "--actor", "customer"]) == 2
    output = capsys.readouterr().out
    assert "操作人不是管理员" in output
    assert "Traceback" not in output
