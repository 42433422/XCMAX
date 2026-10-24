"""Tenant-scoped JSONL groups and encrypted conversation persistence."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.application.group_chat.employee_registry import _safe_json_line


class GroupChatRepository:
    _ENCRYPTED_MESSAGE_PREFIX = "enc:v1:"
    _SECRET_FILE_NAME = ".group-chat-secret"
    _process_secret: str | None = None

    def __init__(self, root: Path) -> None:
        self.root = root / "ai_group_chat"
        self.root.mkdir(parents=True, exist_ok=True)
        self._groups_path = self.root / "groups.jsonl"
        self._messages_path = self.root / "messages.jsonl"

    def user_groups(self, user_id: int) -> list[dict[str, Any]]:
        rows = [g for g in self.all_groups() if int(g.get("user_id") or 0) == int(user_id)]
        return GroupChatRepository.dedupe_groups_by_id(rows)

    @staticmethod
    def dedupe_groups_by_id(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """同一 group id 仅保留一条(合并成员去重 + 置顶/关注取或)。

        历史上 ``_append_group`` 纯追加,部门群 seed 多次会在 JSONL 里累积同 id 重复条目,
        移动端 LazyColumn 用 ``"group:{id}"`` 作 key、重复 key 会直接抛
        ``IllegalArgumentException`` 整个 App 闪退。读取路径统一去重,保证对外永不出现重复 id。
        """
        out: list[dict[str, Any]] = []
        index: dict[str, int] = {}
        for g in groups:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or "")
            if not gid:
                out.append(g)
                continue
            if gid not in index:
                index[gid] = len(out)
                out.append(g)
                continue
            keep = out[index[gid]]
            seen_m = {
                str(m.get("employee_id") or "")
                for m in keep.get("members", [])
                if isinstance(m, dict)
            }
            for m in g.get("members", []) or []:
                if isinstance(m, dict) and str(m.get("employee_id") or "") not in seen_m:
                    keep.setdefault("members", []).append(m)
                    seen_m.add(str(m.get("employee_id") or ""))
            if g.get("is_pinned"):
                keep["is_pinned"] = True
            if g.get("is_followed"):
                keep["is_followed"] = True
        return out

    def compact_groups_file_if_needed(self) -> None:
        """groups 存储出现同 (user_id, id) 重复条目时,去重重写文件(自愈历史脏数据)。"""
        all_groups = self.all_groups()
        seen: set[tuple[int, str]] = set()
        has_dup = False
        for g in all_groups:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or "")
            if not gid:
                continue
            key = (int(g.get("user_id") or 0), gid)
            if key in seen:
                has_dup = True
                break
            seen.add(key)
        if not has_dup:
            return
        by_user: dict[int, list[dict[str, Any]]] = {}
        order: list[int] = []
        for g in all_groups:
            if not isinstance(g, dict):
                continue
            uid = int(g.get("user_id") or 0)
            if uid not in by_user:
                by_user[uid] = []
                order.append(uid)
            by_user[uid].append(g)
        compacted: list[dict[str, Any]] = []
        for uid in order:
            compacted.extend(GroupChatRepository.dedupe_groups_by_id(by_user[uid]))
        self.rewrite_groups(compacted)

    def all_groups(self) -> list[dict[str, Any]]:
        return self.read_jsonl(self._groups_path)

    def read_messages(self) -> list[dict[str, Any]]:
        if not self._messages_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        saw_plaintext = False
        saw_legacy_key = False
        cipher = self.message_cipher()
        legacy_cipher = self.legacy_derived_cipher()
        for line in self._messages_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                if raw.startswith(self._ENCRYPTED_MESSAGE_PREFIX):
                    token = raw.removeprefix(self._ENCRYPTED_MESSAGE_PREFIX).encode("ascii")
                    try:
                        item = json.loads(cipher.decrypt(token).decode("utf-8"))
                    except InvalidToken:
                        if legacy_cipher is None:
                            raise
                        item = json.loads(legacy_cipher.decrypt(token).decode("utf-8"))
                        saw_legacy_key = True
                else:
                    item = json.loads(raw)
                    saw_plaintext = True
            except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                continue
            if isinstance(item, dict):
                rows.append(item)
        if saw_plaintext or saw_legacy_key:
            self.rewrite_messages(rows)
        return rows

    @staticmethod
    def message_cipher(*, data_dir: str | None = None) -> Fernet:
        secret = (
            os.environ.get("SECRET_KEY", "").strip()
            or os.environ.get("XCAGI_SECRET_KEY", "").strip()
        )
        if not secret:
            data_dir = (
                data_dir
                or (
                    os.environ.get("XCAGI_DATA_DIR")
                    or os.environ.get("XCAGI_DESKTOP_DATA_DIR")
                    or ""
                ).strip()
            )
            desktop = (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if data_dir:
                secret = GroupChatRepository.desktop_data_dir_secret(data_dir)
            elif desktop:
                secret = GroupChatRepository.process_local_secret()
            else:
                raise RuntimeError("SECRET_KEY is required for encrypted AI group-chat storage")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @staticmethod
    def desktop_data_dir_secret(data_dir: str) -> str:
        """从数据目录读取/生成持久化随机密钥（0600）。

        2026-08-01 前使用「可预测派生密钥」（data_dir 路径字面量 sha256），任何能猜到
        路径的人都可离线解密群聊内容；现改为首次启动生成 secrets.token_urlsafe(32) 并
        持久化。旧消息由 _legacy_derived_cipher 透明迁移（见 _read_messages）。
        """
        key_path = Path(data_dir).expanduser().resolve() / GroupChatRepository._SECRET_FILE_NAME
        try:
            if key_path.is_file():
                existing = key_path.read_text(encoding="utf-8").strip()
                if existing:
                    return existing
            key_path.parent.mkdir(parents=True, exist_ok=True)
            generated = secrets.token_urlsafe(32)
            key_path.write_text(generated + "\n", encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(key_path, 384)
            return generated
        except OSError:
            return GroupChatRepository.process_local_secret()

    @classmethod
    def process_local_secret(cls) -> str:
        """进程级随机兜底密钥：本进程生命周期内稳定，重启后历史加密消息不可解密。"""
        if cls._process_secret is None:
            cls._process_secret = "process-local:" + secrets.token_urlsafe(32)
        return cls._process_secret

    @staticmethod
    def legacy_derived_cipher() -> Fernet | None:
        """旧的「可预测派生密钥」解密器，仅用于读取并迁移 2026-08-01 前加密的历史消息。

        禁止用于加密。配置了 SECRET_KEY 时返回 None（无 legacy 数据场景）。
        """
        if (
            os.environ.get("SECRET_KEY", "").strip()
            or os.environ.get("XCAGI_SECRET_KEY", "").strip()
        ):
            return None
        data_dir = (
            os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_DESKTOP_DATA_DIR") or ""
        ).strip()
        desktop = (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if data_dir:
            legacy = f"xcagi-desktop-group-chat:{Path(data_dir).expanduser().resolve()}"
        elif desktop:
            legacy = "xcagi-desktop-group-chat:default"
        else:
            return None
        digest = hashlib.sha256(legacy.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def encrypted_message_line(self, message: dict[str, Any]) -> str:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        token = self.message_cipher().encrypt(payload).decode("ascii")
        return f"{self._ENCRYPTED_MESSAGE_PREFIX}{token}\n"

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def append_group(self, group: dict[str, Any]) -> None:
        with self._groups_path.open("a", encoding="utf-8") as fh:
            fh.write(_safe_json_line(group))

    def rewrite_groups(self, groups: list[dict[str, Any]]) -> None:
        with self._groups_path.open("w", encoding="utf-8") as fh:
            for g in groups:
                fh.write(_safe_json_line(g))

    def append_messages(self, messages: list[dict[str, Any]]) -> None:
        with self._messages_path.open("a", encoding="utf-8") as fh:
            for m in messages:
                fh.write(self.encrypted_message_line(m))

    def rewrite_messages(self, messages: list[dict[str, Any]]) -> None:
        with self._messages_path.open("w", encoding="utf-8") as fh:
            for m in messages:
                fh.write(self.encrypted_message_line(m))

    def resolve_group_id(self, *, user_id: int, group_id: str) -> str:
        raw = str(group_id or "").strip()
        if not raw:
            return raw
        group = GroupChatRepository.find(self.user_groups(user_id), raw)
        alias = str((group or {}).get("alias_group_id") or "").strip()
        if not alias:
            return raw
        target = GroupChatRepository.find(self.user_groups(user_id), alias)
        return alias if target is not None else raw

    @staticmethod
    def find(groups: list[dict[str, Any]], group_id: str) -> dict[str, Any] | None:
        return next((g for g in groups if str(g.get("id")) == str(group_id)), None)

    @staticmethod
    def replace(groups: list[dict[str, Any]], updated: dict[str, Any]) -> list[dict[str, Any]]:
        key = GroupChatRepository.group_key(updated)
        return [updated if GroupChatRepository.group_key(g) == key else g for g in groups]

    @staticmethod
    def group_key(group: dict[str, Any]) -> tuple[int, str]:
        """Department IDs are shared across users; every mutation needs the owner."""
        return int(group.get("user_id") or 0), str(group.get("id"))
