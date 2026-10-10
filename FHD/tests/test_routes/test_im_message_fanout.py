from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.im.message_fanout import (
    build_im_message_payloads,
    push_im_message_to_members,
)


def test_build_payloads_match_legacy_web_contract() -> None:
    legacy, sync = build_im_message_payloads(5, {"message": {"id": 1}, "updated_at_ms": 9})
    assert legacy == {"type": "message", "conversation_id": 5, "message": {"id": 1}}
    assert sync == {
        "type": "im.message",
        "conversation_id": 5,
        "message": {"id": 1},
        "updated_at_ms": 9,
    }


@pytest.mark.asyncio
async def test_push_skips_sender_and_returns_members() -> None:
    hub = SimpleNamespace(send_to_user=AsyncMock())
    members = await push_im_message_to_members(
        2, 5, {"message": {"id": 1}, "member_user_ids": ["2", 58, 60]}, hub=hub
    )
    assert members == [2, 58, 60]
    assert [c.args[0] for c in hub.send_to_user.await_args_list] == [58, 58, 60, 60]


@pytest.mark.asyncio
async def test_push_with_no_members_is_noop() -> None:
    hub = SimpleNamespace(send_to_user=AsyncMock())
    assert await push_im_message_to_members(2, 5, {"message": {"id": 1}}, hub=hub) == []
    hub.send_to_user.assert_not_awaited()
