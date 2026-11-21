"""Last finished conversation for one owner, tenant, and mod.

Restart reads this pointer and reopens that conversation. A different tenant
or an unfinished user has no pointer and keeps the setup screen.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken

from app.application.ai_chat.dialogue_memory import _lock, _memory_dir
from app.application.group_chat.storage import GroupChatRepository
from app.application.message_repository import MessageRepository
from app.application.task_conversation_store import durable_user_id, task_conversation_store
from app.domain.shared_services.conversation_service import (
    begin_conversation_write,
    lock_conversation_session,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_POINTER_ERRORS: tuple[type[Exception], ...] = (InvalidToken,) + RECOVERABLE_ERRORS


def _pointer_cipher(*, create: bool) -> Fernet:
    directory = _memory_dir()
    with _lock("cipher"):
        if not (
            os.environ.get("SECRET_KEY", "").strip()
            or os.environ.get("XCAGI_SECRET_KEY", "").strip()
        ):
            key_path = directory / GroupChatRepository._SECRET_FILE_NAME
            existing = key_path.read_text(encoding="utf-8").strip() if key_path.exists() else ""
            if not existing and not create:
                raise ValueError("Active conversation key is unavailable")
        return GroupChatRepository.message_cipher(data_dir=str(directory), require_persistent=True)


def remember_active_conversation(
    context: Mapping[str, Any] | None, *, conversation_id: str = ""
) -> None:
    scope = _scope(context, conversation_id)
    if scope is None:
        return
    key, payload = scope
    path = _memory_dir() / f"{key}-active.json"
    temporary = path.with_suffix(".json.tmp")
    try:
        from app.application.task_conversation_store import get_db

        with _lock(f"{key}-active"), get_db() as db:
            begin_conversation_write(db)
            lock_conversation_session(
                db,
                session_id=payload["conversation_id"],
                user_id=int(payload["owner"]),
                expected_revision=(context or {}).get("_conversation_revision"),
            )
            cipher = _pointer_cipher(create=True)
            if path.is_file():
                stored = path.read_text(encoding="utf-8").strip()
                prefix = GroupChatRepository._ENCRYPTED_MESSAGE_PREFIX
                if stored.startswith(prefix):
                    cipher.decrypt(stored.removeprefix(prefix).encode())
            temporary.write_text(
                MessageRepository._encrypted_json_line(payload, cipher),
                encoding="utf-8",
            )
            temporary.replace(path)
            db.commit()
    except _POINTER_ERRORS:
        return


def active_conversation_for(owner: Any, *, tenant_id: str = "", mod_id: str = "") -> str:
    key = _key(owner, tenant_id, mod_id)
    if not key:
        return ""
    path = _memory_dir() / f"{key}-active.json"
    if not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8").strip()
        prefix = GroupChatRepository._ENCRYPTED_MESSAGE_PREFIX
        if raw.startswith(prefix):
            raw = _pointer_cipher(create=False).decrypt(raw.removeprefix(prefix).encode()).decode()
        data = json.loads(raw)
    except _POINTER_ERRORS:
        return ""
    if not isinstance(data, dict):
        return ""
    if str(data.get("owner") or "") != str(durable_user_id(owner) or ""):
        return ""
    if str(data.get("tenant_id") or "") != str(tenant_id or ""):
        return ""
    conversation_id = str(data.get("conversation_id") or "").strip()
    if (
        not conversation_id
        or task_conversation_store.memory_snapshot(
            session_id=conversation_id,
            user_id=int(data["owner"]),
        )
        is None
    ):
        return ""
    return conversation_id


def _scope(
    context: Mapping[str, Any] | None, conversation_id: str
) -> tuple[str, dict[str, str]] | None:
    context = context or {}
    raw = str(
        conversation_id or context.get("conversation_id") or context.get("session_id") or ""
    ).strip()
    owner = durable_user_id(context.get("local_user_id") or context.get("actor_id"))
    if owner is None or not raw:
        return None
    tenant_id = str(context.get("tenant_id") or "")
    mod_id = str(context.get("mod_id") or context.get("active_mod_id") or "")
    key = _key(owner, tenant_id, mod_id)
    if not key:
        return None
    return key, {
        "owner": str(owner),
        "tenant_id": tenant_id,
        "mod_id": mod_id,
        "conversation_id": raw,
    }


def _key(owner: Any, tenant_id: str, mod_id: str) -> str:
    durable = durable_user_id(owner)
    if durable is None:
        return ""
    # The pointer is per owner and tenant. A mod header must not hide it.
    scope = [str(durable), str(tenant_id or "")]
    return hashlib.sha256(json.dumps(scope, ensure_ascii=False).encode()).hexdigest()
