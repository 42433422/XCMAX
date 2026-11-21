"""Persistence layer for the super-employee service.

Extracted from ``super_employee_service.py`` to isolate the messages.jsonl /
outbox file I/O behind a single responsibility. The service delegates here so
the storage format can evolve and be tested independently of dispatch / CLI /
git concerns.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock

from app.application.group_chat.storage import GroupChatRepository


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


class MessageRepository:
    """Persist super-employee conversation messages and dispatch outbox files."""

    def __init__(self, storage_root: Path, subdir: str) -> None:
        self._root = storage_root / subdir
        self._root.mkdir(parents=True, exist_ok=True)
        self._messages_path = self._root / "messages.jsonl"
        self._outbox_dir = self._root / "outbox"
        self._outbox_dir.mkdir(parents=True, exist_ok=True)

    @property
    def messages_path(self) -> Path:
        return self._messages_path

    @property
    def outbox_dir(self) -> Path:
        return self._outbox_dir

    def write_outbox(
        self,
        request: dict[str, Any],
        *,
        status: str,
        accepted: bool,
        reason: str,
    ) -> dict[str, Any]:
        path = (
            self._outbox_dir
            / f"{request['created_at'].replace(':', '').replace('+', 'Z')}-{int(request.get('user_id') or 0)}-{request['request_id']}.json"
        )
        # Persist the send intent before crossing the remote side-effect boundary.
        # Atomic replacement preserves the last receipt if a writer is interrupted.
        fd, temporary = tempfile.mkstemp(dir=self._outbox_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(request, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {
            "request_id": request["request_id"],
            "status": status,
            "accepted": accepted,
            "queued": True,
            "device_scope": "all_devices",
            "reason": reason,
            "outbox_path": str(path),
        }

    def dispatch_lock(self, user_id: int, request_id: str) -> FileLock:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request_id):
            raise ValueError("request_id 格式无效")
        key = hashlib.sha256(f"{int(user_id)}:{request_id}".encode()).hexdigest()
        return FileLock(self._outbox_dir / f"{key}.lock", timeout=30)

    def read_dispatch_request(self, user_id: int, request_id: str) -> dict[str, Any] | None:
        for path in self._outbox_dir.glob(f"*-{request_id}.json"):
            request = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                raise ValueError("持久化执行回执必须是对象")
            if request.get("request_id") == request_id and int(request.get("user_id") or 0) == int(
                user_id
            ):
                return request
        return None

    def message_row(
        self,
        *,
        user_id: int,
        role: str,
        body: str,
        created_at: str,
        request_id: str,
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": uuid.uuid4().hex,
            "user_id": int(user_id),
            "role": role,
            "body": body,
            "created_at": created_at,
            "dispatch_request_id": request_id,
            "status": status,
        }
        if extra:
            row.update({k: v for k, v in extra.items() if v not in (None, "")})
        return row

    def append_messages(self, messages: list[dict[str, Any]]) -> None:
        cipher = self._message_cipher()
        with self._messages_path.open("a", encoding="utf-8") as fh:
            for msg in messages:
                fh.write(self._encrypted_json_line(msg, cipher))

    def read_all_message_rows(self) -> list[dict[str, Any]]:
        if not self._messages_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        cipher = self._message_cipher()
        prefix = GroupChatRepository._ENCRYPTED_MESSAGE_PREFIX
        for line in self._messages_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                if line.startswith(prefix):
                    payload = cipher.decrypt(line.removeprefix(prefix).encode("ascii"))
                    item = json.loads(payload.decode("utf-8"))
                else:
                    # Read existing plaintext JSONL without rewriting it. New writes are
                    # encrypted, so a read does not mutate a user's historical messages.
                    item = json.loads(line)
            except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def write_all_message_rows(self, rows: list[dict[str, Any]]) -> None:
        cipher = self._message_cipher()
        with self._messages_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(self._encrypted_json_line(row, cipher))

    def _message_cipher(self) -> Fernet:
        return GroupChatRepository.message_cipher(data_dir=str(self._root.parent))

    @staticmethod
    def _encrypted_json_line(payload: dict[str, Any], cipher: Fernet) -> str:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        token = cipher.encrypt(raw).decode("ascii")
        return f"{GroupChatRepository._ENCRYPTED_MESSAGE_PREFIX}{token}\n"

    def public_message(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(item.get("id") or ""),
            "role": str(item.get("role") or "assistant"),
            "body": str(item.get("body") or ""),
            "created_at": str(item.get("created_at") or ""),
            "status": str(item.get("status") or ""),
            "dispatch_request_id": str(item.get("dispatch_request_id") or ""),
            "kind": str(item.get("kind") or ""),
            "task_id": str(item.get("task_id") or ""),
            "task_status": str(item.get("task_status") or ""),
            "subtask_id": str(item.get("subtask_id") or ""),
            "device_name": str(item.get("device_name") or ""),
        }


__all__ = ["MessageRepository"]
