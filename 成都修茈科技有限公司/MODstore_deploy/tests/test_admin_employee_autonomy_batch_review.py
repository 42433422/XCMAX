from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import modstore_server.admin_employee_autonomy_api as autonomy_api


def test_batch_review_accepts_current_contract(monkeypatch) -> None:
    calls: list[tuple[int, int, bool]] = []
    monkeypatch.setattr(
        autonomy_api,
        "approve_suggestion",
        lambda suggestion_id, *, approved_by_user_id, dispatch_now: (
            calls.append((suggestion_id, approved_by_user_id, dispatch_now)) or {"ok": True}
        ),
    )

    result = autonomy_api.batch_review_employee_suggestions(
        {"ids": [1, "2"], "action": "approve", "dispatch_now": True},
        SimpleNamespace(id=7),
    )

    assert result == {
        "ok": True,
        "action": "approve",
        "total": 2,
        "success": 2,
        "failed": 0,
        "errors": [],
    }
    assert calls == [(1, 7, True), (2, 7, True)]


def test_batch_review_keeps_legacy_frontend_compatible(monkeypatch) -> None:
    calls: list[tuple[int, str, int]] = []
    monkeypatch.setattr(
        autonomy_api,
        "reject_suggestion",
        lambda suggestion_id, *, rejected_reason, rejected_by_user_id: (
            calls.append((suggestion_id, rejected_reason, rejected_by_user_id)) or {"ok": True}
        ),
    )

    result = autonomy_api.batch_review_employee_suggestions(
        {"reject_ids": [9], "note": "重复建议"},
        SimpleNamespace(id=8),
    )

    assert result["action"] == "reject"
    assert result["success"] == 1
    assert calls == [(9, "重复建议", 8)]


def test_batch_review_rejects_ambiguous_legacy_payload() -> None:
    with pytest.raises(HTTPException, match="不能同时提交"):
        autonomy_api.batch_review_employee_suggestions(
            {"approve_ids": [1], "reject_ids": [2]},
            SimpleNamespace(id=8),
        )
