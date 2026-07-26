import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.release_gate

from modstore_server.founder_scorecard_publisher import (  # noqa: E402
    _issue_market_admin_bearer,
    publish_founder_scorecard,
    register_founder_scorecard_job,
)


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    response.__exit__.return_value = False
    return response


def test_publisher_uses_two_credentials_and_requires_seven_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "automation-secret")
    monkeypatch.setattr(
        "modstore_server.founder_scorecard_publisher._issue_market_admin_bearer",
        lambda: "market-admin-jwt",
    )
    opened: list = []

    def _urlopen(request, *, timeout):
        opened.append((request, timeout))
        return _response(
            {
                "success": True,
                "data": {
                    "generated_at": "2026-07-26T10:00:00+00:00",
                    "overall_progress": 76,
                    "dimensions": [{"id": str(index)} for index in range(7)],
                },
                "publication": {
                    "ok": True,
                    "written": ["/var/lib/xcmax-public/download-founder-autonomy.json"],
                },
            }
        )

    monkeypatch.setattr(
        "modstore_server.founder_scorecard_publisher.urllib.request.urlopen",
        _urlopen,
    )

    result = publish_founder_scorecard()

    assert result == {
        "ok": True,
        "generated_at": "2026-07-26T10:00:00+00:00",
        "overall_progress": 76,
        "dimension_count": 7,
        "published_target_count": 1,
    }
    request, _timeout = opened[0]
    assert request.get_header("Authorization") == "Bearer market-admin-jwt"
    assert request.get_header("X-autonomy-token") == "automation-secret"


def test_machine_bearer_uses_first_admin_and_expires_quickly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = SimpleNamespace(id=42, username="ops-admin")
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = admin
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(
        "modstore_server.models.get_session_factory",
        lambda: session_factory,
    )
    issued: list[tuple[tuple, dict]] = []

    def _create_access_token(*args, **kwargs):
        issued.append((args, kwargs))
        return "short-lived-machine-jwt"

    monkeypatch.setattr(
        "modstore_server.auth_service.create_access_token",
        _create_access_token,
    )

    assert _issue_market_admin_bearer() == "short-lived-machine-jwt"
    assert issued == [
        (
            (42, "ops-admin"),
            {
                "is_admin": True,
                "expires_delta": timedelta(minutes=10),
                "actor": "founder-scorecard-publisher",
            },
        )
    ]


def test_access_token_records_machine_actor_and_custom_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modstore_server.auth_service import create_access_token, decode_access_token

    monkeypatch.setenv("MODSTORE_JWT_SECRET", "test-secret-" + ("x" * 32))
    before = datetime.now(timezone.utc)
    token = create_access_token(
        42,
        "ops-admin",
        is_admin=True,
        expires_delta=timedelta(minutes=10),
        actor="founder-scorecard-publisher",
    )

    payload = decode_access_token(token)
    assert payload is not None
    assert payload["actor"] == "founder-scorecard-publisher"
    assert payload["roles"] == ["ADMIN"]
    assert (
        before + timedelta(minutes=9, seconds=55)
        <= datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        <= before + timedelta(minutes=10, seconds=5)
    )


def test_publisher_fails_closed_without_autonomy_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTONOMY_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("MODSTORE_OPS_INGEST_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="no autonomy webhook token"):
        publish_founder_scorecard()


def test_registers_tracked_refresh_as_single_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODSTORE_FOUNDER_SCORECARD_REFRESH_MINUTES", "7")
    scheduler = MagicMock()

    register_founder_scorecard_job(scheduler)

    assert scheduler.add_job.call_count == 1
    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == "founder_scorecard_refresh"
    assert kwargs["replace_existing"] is True
    assert kwargs["coalesce"] is True
    assert kwargs["max_instances"] == 1
    assert str(scheduler.add_job.call_args.args[1]) == "interval[0:07:00]"
