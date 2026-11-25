"""Proactive events dedupe, persist and fan out without duplicating alerts."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.proactive.service import (
    DEDUPE_WINDOW_SECONDS,
    ProactiveEvent,
    ProactiveService,
    apprise_sender,
    in_app_sender,
)


def event(**overrides):
    base = {"kind": "inventory_low", "title": "库存不足", "detail": "华东仓低于安全线"}
    base.update(overrides)
    return ProactiveEvent(**base)


def test_duplicate_event_is_deduped_within_window(tmp_path):
    now = 1000.0
    service = ProactiveService(tmp_path, tenant_id="a", clock=lambda: now)
    first = service.publish(event())
    second = service.publish(event())
    assert first["deduped"] is False
    assert second["deduped"] is True
    assert len(service.recent()) == 1


def test_event_is_republished_after_window(tmp_path):
    clock = {"now": 1000.0}
    service = ProactiveService(tmp_path, tenant_id="a", clock=lambda: clock["now"])
    service.publish(event())
    clock["now"] += DEDUPE_WINDOW_SECONDS + 1
    again = service.publish(event())
    assert again["deduped"] is False
    assert len(service.recent()) == 2


def test_channel_failure_keeps_event_and_reports_error(tmp_path):
    def broken(_event):
        raise RuntimeError("渠道不可用")

    service = ProactiveService(tmp_path, tenant_id="a", senders=[broken])
    result = service.publish(event())
    assert result["ok"] is False and result["stored"] is True
    assert "RuntimeError" in result["errors"][0]
    assert len(service.recent()) == 1


def test_successful_senders_are_recorded(tmp_path):
    seen = []
    result = ProactiveService(tmp_path, tenant_id="a", senders=[seen.append]).publish(event())
    assert result["delivered"] == ["append"]
    assert seen[0].title == "库存不足"


def test_apprise_sender_is_noop_without_urls(monkeypatch):
    monkeypatch.delenv("PROACTIVE_APPRISE_URLS", raising=False)
    assert apprise_sender()(event()) is False  # must not import apprise or raise


@pytest.mark.parametrize("socket_status", ["offline", "broken", "online"])
def test_in_app_sender_reports_only_successful_socket_sends(monkeypatch, socket_status):
    from app.infrastructure.im import ws_hub

    hub = ws_hub.ImWsHub()
    socket = AsyncMock()
    if socket_status == "broken":
        socket.send_text.side_effect = ConnectionError("disconnected")
    if socket_status != "offline":
        hub._connections[7].add(socket)
    monkeypatch.setattr(ws_hub, "im_ws_hub", hub)

    assert in_app_sender(event()) is False
    assert in_app_sender(event(user_ids=(7, 7))) is (socket_status == "online")
    if socket_status == "online":
        socket.send_text.assert_awaited_once()
        assert json.loads(socket.send_text.call_args.args[0])["type"] == "proactive"
    elif socket_status == "broken":
        assert hub.connected_user_ids() == set()


def test_failed_channels_retry_without_repeating_success_or_persistence(tmp_path):
    delivered, attempts = [], []

    def flaky(message):
        attempts.append(message.event_id)
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")

    service = ProactiveService(tmp_path, tenant_id="a", senders=[delivered.append, flaky])
    first = service.publish(event())
    second = service.publish(event())
    assert first["ok"] is False and second["ok"] is True
    assert second["deduped"] is True
    assert first["event_id"] == second["event_id"]
    assert len(delivered) == len(service.recent()) == 1
    assert len(attempts) == 2


def test_dedupe_and_reads_are_scoped_to_tenant_recipient_and_event_content(tmp_path):
    service = ProactiveService(tmp_path, tenant_id="a")
    service.publish(event(user_ids=(1,)))
    assert service.publish(event(user_ids=(2,)))["deduped"] is False
    assert service.publish(event(user_ids=(1,), detail="另一仓库"))["deduped"] is False
    assert service.recent() == []
    assert len(service.recent(user_id=1)) == 2
    assert len(service.recent(user_id=2)) == 1
    other = ProactiveService(tmp_path, tenant_id="b")
    assert other.recent(user_id=1) == []
    assert other.publish(event(user_ids=(1,)))["deduped"] is False


def test_interrupted_channel_is_not_blindly_resent(tmp_path):
    service = ProactiveService(tmp_path, tenant_id="a")
    first = service.publish(event())
    with sqlite3.connect(service._root / "outbox.sqlite3") as db:
        db.execute(
            "INSERT INTO deliveries VALUES (?, ?, ?)", (first["event_id"], "0:append", "inflight")
        )
    delivered = []
    retry = ProactiveService(tmp_path, tenant_id="a", senders=[delivered.append]).publish(event())
    assert retry["ok"] is False
    assert "未知" in retry["errors"][0]
    assert delivered == []


def test_missing_channel_is_skipped_not_delivered(tmp_path, monkeypatch):
    monkeypatch.delenv("PROACTIVE_APPRISE_URLS", raising=False)
    result = ProactiveService(tmp_path, tenant_id="a", senders=[apprise_sender()]).publish(event())
    assert result["stored"] and result["skipped"] == ["send"]
    assert result["delivered"] == []


def test_concurrent_processes_store_and_deliver_once(tmp_path):
    code = """
from pathlib import Path
import json, sys
from app.application.proactive.service import ProactiveEvent, ProactiveService
root=Path(sys.argv[1])
def record(event):
    with (root/'receipts').open('a') as stream:
        stream.write(event.event_id+'\\n')
print(json.dumps(ProactiveService(root, tenant_id='a', senders=[record]).publish(ProactiveEvent(kind='low',title='stock'))))
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    outputs = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0, 0, 0], outputs
    results = [json.loads(stdout) for stdout, _ in outputs]
    assert sum(not row["deduped"] for row in results) == 1
    assert len((tmp_path / "receipts").read_text().splitlines()) == 1
