import json
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.release_gate

from modstore_server.founder_scorecard_publisher import (  # noqa: E402
    publish_founder_scorecard,
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
        "modstore_server.daily_digest_surface_audit._login_surface_audit_sync",
        lambda **_kwargs: {"access_token": "market-admin-jwt"},
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


def test_publisher_fails_closed_without_autonomy_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTONOMY_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("MODSTORE_OPS_INGEST_TOKEN", raising=False)
    monkeypatch.setattr(
        "modstore_server.daily_digest_surface_audit._login_surface_audit_sync",
        lambda **_kwargs: {"access_token": "market-admin-jwt"},
    )

    with pytest.raises(RuntimeError, match="no autonomy webhook token"):
        publish_founder_scorecard()
