"""Command receipts are bound to the exact screen, never inferred as success."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.aiopen.cursor_hub import AiOpenCursorHub


@pytest.mark.asyncio
async def test_multiple_screens_require_explicit_target():
    hub = AiOpenCursorHub()
    first, second = AsyncMock(), AsyncMock()
    await hub.connect("first", first)
    await hub.connect("second", second)
    result = await hub.dispatch("click", {"selector": "#delete"})
    assert result["code"] == "SCREEN_SELECTION_REQUIRED"
    first.send_text.assert_not_called()
    second.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_receipt_from_other_screen_cannot_complete_command():
    hub = AiOpenCursorHub()
    screen = AsyncMock()
    await hub.connect("owner", screen)
    task = asyncio.create_task(hub.dispatch("snapshot", session_id="owner"))
    await asyncio.sleep(0)
    command = json.loads(screen.send_text.call_args.args[0])
    reply = json.dumps({"type": "result", "id": command["id"], "result": {"success": True}})
    assert hub.handle_client_message(reply, session_id="other") is False
    assert not task.done()
    assert hub.handle_client_message(reply, session_id="owner") is True
    assert (await task)["success"] is True
    assert not hub._pending
    assert not hub._pending_sessions


@pytest.mark.asyncio
async def test_disconnect_marks_inflight_outcome_unverified():
    hub = AiOpenCursorHub()
    screen = AsyncMock()
    await hub.connect("owner", screen)
    task = asyncio.create_task(hub.dispatch("type", {"text": "secret-value"}, session_id="owner"))
    await asyncio.sleep(0)
    command = json.loads(screen.send_text.call_args.args[0])
    invalid = json.dumps({"type": "result", "id": command["id"], "result": {"message": "ok"}})
    assert hub.handle_client_message(invalid, session_id="owner") is False
    await hub.disconnect("owner")
    result = await task
    assert result["success"] is False
    assert result["code"] == "SCREEN_DISCONNECTED"
    assert "secret-value" not in json.dumps(hub.recent_commands())


@pytest.mark.asyncio
async def test_timeout_cleans_pending_and_never_claims_success():
    hub = AiOpenCursorHub()
    await hub.connect("owner", AsyncMock())
    result = await hub.dispatch("click", session_id="owner", timeout=0.001)
    assert result["success"] is False
    assert result["outcome"] == "unknown"
    assert not hub._pending
    assert not hub._pending_sessions


@pytest.mark.asyncio
async def test_duplicate_session_cannot_replace_active_screen():
    hub = AiOpenCursorHub()
    first = AsyncMock()
    await hub.connect("owner", first)
    with pytest.raises(ValueError, match="already connected"):
        await hub.connect("owner", AsyncMock())
    assert hub._sessions["owner"] is first
