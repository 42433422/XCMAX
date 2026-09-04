from __future__ import annotations

import logging

import httpx

from modstore_server.employee_im_bridge import notify_boss


def test_notify_boss_does_not_log_message_or_identity(monkeypatch, caplog) -> None:
    monkeypatch.setenv(
        "FHD_INTERNAL_EMPLOYEE_IM_URL", "http://127.0.0.1/api/internal/employee-im/send"
    )
    monkeypatch.setenv("FHD_INTERNAL_API_KEY", "test-key")

    class _Response:
        status_code = 503
        text = "upstream echoed customer-secret-message"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(httpx, "Client", _Client)
    with caplog.at_level(logging.INFO, logger="modstore_server.employee_im_bridge"):
        ok = notify_boss(
            "private-employee-id",
            body="customer-secret-message",
            hook="private-hook",
            boss_user_id=7,
        )

    assert ok is False
    assert "customer-secret-message" not in caplog.text
    assert "private-employee-id" not in caplog.text
    assert "private-hook" not in caplog.text
    assert "upstream echoed" not in caplog.text
