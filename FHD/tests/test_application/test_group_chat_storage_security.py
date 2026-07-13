from __future__ import annotations

import json

from app.application.ai_group_chat_service import AiGroupChatService


def test_group_chat_messages_are_encrypted_at_rest(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-that-is-long-enough-for-storage")
    service = AiGroupChatService(storage_root=tmp_path)
    row = service._message_row(
        user_id=1,
        group_id="group-1",
        role="user",
        sender_id="user-1",
        sender_name="测试用户",
        sender_avatar="",
        body="private-order-details",
    )

    service._append_messages([row])

    stored = service._messages_path.read_text(encoding="utf-8")
    assert stored.startswith("v1:")
    assert "private-order-details" not in stored
    assert service._read_messages() == [row]


def test_group_chat_plaintext_is_migrated_on_read(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-that-is-long-enough-for-storage")
    service = AiGroupChatService(storage_root=tmp_path)
    legacy = {"id": "m1", "user_id": 1, "group_id": "g1", "body": "legacy-private"}
    service._messages_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    assert service._read_messages() == [legacy]
    migrated = service._messages_path.read_text(encoding="utf-8")
    assert migrated.startswith("v1:")
    assert "legacy-private" not in migrated
