from __future__ import annotations

import json

from app.application.ai_group_chat_service import AiGroupChatService


def test_group_chat_messages_are_encrypted_at_rest(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-at-least-32-bytes")
    service = AiGroupChatService(storage_root=tmp_path)
    message = {"id": "m1", "group_id": "g1", "body": "sensitive customer message"}

    service._append_messages([message])

    persisted = service._messages_path.read_text(encoding="utf-8")
    assert persisted.startswith("enc:v1:")
    assert "sensitive customer message" not in persisted
    assert service._read_messages() == [message]


def test_group_chat_plaintext_is_migrated_on_read(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-at-least-32-bytes")
    service = AiGroupChatService(storage_root=tmp_path)
    message = {"id": "legacy", "group_id": "g1", "body": "legacy message"}
    service._messages_path.write_text(json.dumps(message) + "\n", encoding="utf-8")

    assert service._read_messages() == [message]
    migrated = service._messages_path.read_text(encoding="utf-8")
    assert migrated.startswith("enc:v1:")
    assert "legacy message" not in migrated
