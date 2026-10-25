"""Read-only employee collab sync can use an internal service key."""

from __future__ import annotations

import pytest

from modstore_server.employee_autonomy_service import create_collab_thread, post_collab_message
from modstore_server.models import init_db


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "unit-test-internal-key")
    init_db()
    yield


def test_collab_threads_allow_internal_key(client):
    out = create_collab_thread(
        title="[employee-circle] test dept",
        participants=["host-checker"],
        created_by_employee_id="host-checker",
    )
    assert out["ok"], out

    res = client.get(
        "/api/admin/employee-autonomy/collab/threads",
        headers={"X-Internal-Api-Key": "unit-test-internal-key"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] >= 1
    assert any(item["title"].startswith("[employee-circle]") for item in body["items"])


def test_collab_messages_allow_internal_key(client):
    out = create_collab_thread(
        title="[employee-circle] test dept",
        participants=["host-checker"],
        created_by_employee_id="host-checker",
    )
    assert out["ok"], out
    tid = int(out["thread_id"])
    msg = post_collab_message(
        thread_id=tid,
        sender_employee_id="host-checker",
        content="employee task completed: readonly health check finished.",
    )
    assert msg["ok"], msg

    res = client.get(
        f"/api/admin/employee-autonomy/collab/threads/{tid}/messages",
        headers={"X-Internal-Api-Key": "unit-test-internal-key"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 1
    assert body["items"][0]["sender_employee_id"] == "host-checker"


def test_collab_read_rejects_missing_internal_or_admin_auth(client):
    res = client.get("/api/admin/employee-autonomy/collab/threads")
    assert res.status_code == 401
