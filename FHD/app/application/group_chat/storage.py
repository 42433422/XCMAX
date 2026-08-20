"""JSONL persistence mixin for AiGroupChatStorageMixin."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken

from app.application.group_chat.constants import (
    _BROKEN_MARKDOWN_LINK_RE,
    _MARKDOWN_LINK_RE,
    _RELAY_TASK_ID_RE,
    _TEMP_PATH_RE,
    PUBLIC_ACCEPTANCE_BODY_MAX_CHARS,
    PUBLIC_CHAT_BODY_MAX_CHARS,
)
from app.application.group_chat.employee_registry import (
    _member_public_shape,
    _safe_json_line,
    _utc_now,
)


class AiGroupChatStorageMixin:
    if TYPE_CHECKING:
        _canonical_group_name: Any
        _groups_path: Any
        _messages_path: Path

        @staticmethod
        def _chat_friendly_summary(
            value: str, limit: int, *, include_detail_note: bool = True
        ) -> str:
            raise NotImplementedError

    _ENCRYPTED_MESSAGE_PREFIX = "enc:v1:"

    # ── 持久化 ──

    def _public_group(
        self, group: dict[str, Any], preview: dict[str, Any] | None
    ) -> dict[str, Any]:
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        return {
            "id": str(group.get("id")),
            "name": self._canonical_group_name(group),
            "department_key": str(group.get("department_key") or ""),
            "member_count": len(members),
            "members": [_member_public_shape(m) for m in members],
            "is_pinned": bool(group.get("is_pinned")),
            "is_hidden": bool(group.get("is_hidden")),
            "is_followed": bool(group.get("is_followed", True)),
            "unread_count": int(group.get("unread_count") or 0),
            "created_at": str(group.get("created_at") or ""),
            "last_message_preview": str((preview or {}).get("preview") or ""),
            "last_message_at": str((preview or {}).get("created_at") or ""),
        }

    def _public_message(self, row: dict[str, Any]) -> dict[str, Any]:
        kind = str(row.get("kind") or "")
        body = str(row.get("body") or "")
        if kind in {"work_report", "work_progress", "relay_work_report", "work_acceptance"}:
            body = self._clean_public_chat_body(body)
            if kind == "work_acceptance":
                body = self._compact_public_acceptance_body(body)
            body = self._cap_public_chat_body(
                body,
                limit=PUBLIC_ACCEPTANCE_BODY_MAX_CHARS
                if kind == "work_acceptance"
                else PUBLIC_CHAT_BODY_MAX_CHARS,
            )
        out: dict[str, Any] = {
            "id": str(row.get("id") or ""),
            "group_id": str(row.get("group_id") or ""),
            "role": str(row.get("role") or "ai"),
            "sender_id": str(row.get("sender_id") or ""),
            "sender_name": str(row.get("sender_name") or ""),
            "sender_avatar": str(row.get("sender_avatar") or ""),
            "body": body,
            "created_at": str(row.get("created_at") or ""),
        }
        for key in ("kind", "status", "work_order_id"):
            if row.get(key):
                out[key] = str(row.get(key) or "")
        payload = row.get("payload")
        if isinstance(payload, dict):
            out["payload"] = payload
        return out

    @staticmethod
    def _cap_public_chat_body(body: str, limit: int = PUBLIC_CHAT_BODY_MAX_CHARS) -> str:
        text = str(body or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n\n（聊天里已折叠长执行输出；完整内容保留在执行端记录。）"

    @classmethod
    def _clean_public_chat_body(cls, body: str) -> str:
        lines = []
        for raw_line in str(body or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = _TEMP_PATH_RE.sub("临时执行工作区", raw_line)
            line = _MARKDOWN_LINK_RE.sub(r"\1", line)
            line = _BROKEN_MARKDOWN_LINK_RE.sub(r"\1", line)
            line = _RELAY_TASK_ID_RE.sub("。", line)
            for token in ("**", "__", "`"):
                line = line.replace(token, "")
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    @classmethod
    def _compact_public_acceptance_body(cls, body: str) -> str:
        lines = [line.strip() for line in str(body or "").splitlines() if line.strip()]
        if not lines:
            return ""
        title = next(
            (line for line in lines if line.startswith("【小C验收】")), "【小C验收】这单已收口"
        )
        conclusion = next((line for line in lines if line.startswith("结论：")), "")
        task = next((line for line in lines if line.startswith("任务：")), "")
        risk = next((line for line in lines if line.startswith("风险：")), "")
        member_lines = [line for line in lines if line.startswith("- ")][:4]
        compact_members = [
            f"- {cls._chat_friendly_summary(line, limit=70, include_detail_note=False)}"
            for line in member_lines
        ]
        out = [title]
        if conclusion:
            out.append(conclusion)
        if task:
            out.append(cls._chat_friendly_summary(task, limit=72, include_detail_note=False))
        if compact_members:
            out.append("成员：")
            out.extend(compact_members)
        if risk:
            out.append(risk)
        out.append("下一步：满意就继续派下一步；不满意就直接说要谁补什么。")
        return "\n".join(out)

    def _message_row(
        self,
        *,
        user_id: int,
        group_id: str,
        role: str,
        sender_id: str,
        sender_name: str,
        sender_avatar: str,
        body: str,
        kind: str = "chat",
        status: str = "",
        work_order_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "user_id": int(user_id),
            "group_id": str(group_id),
            "role": role,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar,
            "body": body,
            "created_at": _utc_now(),
        }
        if kind and kind != "chat":
            row["kind"] = kind
        if status:
            row["status"] = status
        if work_order_id:
            row["work_order_id"] = work_order_id
        if payload:
            row["payload"] = payload
        return row

    def _latest_previews(self, user_id: int) -> dict[str, dict[str, Any]]:
        previews: dict[str, dict[str, Any]] = {}
        for r in self._read_messages():
            if int(r.get("user_id") or 0) != int(user_id):
                continue
            gid = str(r.get("group_id"))
            sender = str(r.get("sender_name") or "")
            body = str(r.get("body") or "")
            previews[gid] = {
                "preview": f"{sender}：{body}"[:60] if sender else body[:60],
                "created_at": str(r.get("created_at") or ""),
            }
        return previews

    def _user_groups(self, user_id: int) -> list[dict[str, Any]]:
        rows = [g for g in self._all_groups() if int(g.get("user_id") or 0) == int(user_id)]
        return self._dedupe_groups_by_id(rows)

    @staticmethod
    def _dedupe_groups_by_id(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    def _compact_groups_file_if_needed(self) -> None:
        """groups 存储出现同 (user_id, id) 重复条目时,去重重写文件(自愈历史脏数据)。"""
        all_groups = self._all_groups()
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
            compacted.extend(self._dedupe_groups_by_id(by_user[uid]))
        self._rewrite_groups(compacted)

    def _all_groups(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self._groups_path)

    def _read_messages(self) -> list[dict[str, Any]]:
        if not self._messages_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        saw_plaintext = False
        saw_legacy_key = False
        cipher = self._message_cipher()
        legacy_cipher = self._legacy_derived_cipher()
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
                        # 旧派生密钥加密的历史消息：解密成功则标记重写（迁移到新密钥）
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
            self._rewrite_messages(rows)
        return rows

    @staticmethod
    def _message_cipher() -> Fernet:
        secret = (
            os.environ.get("SECRET_KEY", "").strip()
            or os.environ.get("XCAGI_SECRET_KEY", "").strip()
        )
        if not secret:
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
                # 桌面单机：随机密钥持久化到数据目录（0600），稳定且不可预测
                secret = AiGroupChatStorageMixin._desktop_data_dir_secret(data_dir)
            elif desktop:
                # 无数据目录的桌面兜底：进程级随机密钥（不持久化；绝不用可预测字面量）
                secret = AiGroupChatStorageMixin._process_local_secret()
            else:
                raise RuntimeError("SECRET_KEY is required for encrypted AI group-chat storage")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    _SECRET_FILE_NAME = ".group-chat-secret"
    _process_secret: str | None = None

    @staticmethod
    def _desktop_data_dir_secret(data_dir: str) -> str:
        """从数据目录读取/生成持久化随机密钥（0600）。

        2026-08-01 前使用「可预测派生密钥」（data_dir 路径字面量 sha256），任何能猜到
        路径的人都可离线解密群聊内容；现改为首次启动生成 secrets.token_urlsafe(32) 并
        持久化。旧消息由 _legacy_derived_cipher 透明迁移（见 _read_messages）。
        """
        key_path = Path(data_dir).expanduser().resolve() / AiGroupChatStorageMixin._SECRET_FILE_NAME
        try:
            if key_path.is_file():
                existing = key_path.read_text(encoding="utf-8").strip()
                if existing:
                    return existing
            key_path.parent.mkdir(parents=True, exist_ok=True)
            generated = secrets.token_urlsafe(32)
            key_path.write_text(generated + "\n", encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(key_path, 0o600)
            return generated
        except OSError:
            return AiGroupChatStorageMixin._process_local_secret()

    @classmethod
    def _process_local_secret(cls) -> str:
        """进程级随机兜底密钥：本进程生命周期内稳定，重启后历史加密消息不可解密。"""
        if cls._process_secret is None:
            cls._process_secret = "process-local:" + secrets.token_urlsafe(32)
        return cls._process_secret

    @staticmethod
    def _legacy_derived_cipher() -> Fernet | None:
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

    def _encrypted_message_line(self, message: dict[str, Any]) -> str:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        token = self._message_cipher().encrypt(payload).decode("ascii")
        return f"{self._ENCRYPTED_MESSAGE_PREFIX}{token}\n"

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
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

    def _append_group(self, group: dict[str, Any]) -> None:
        with self._groups_path.open("a", encoding="utf-8") as fh:
            fh.write(_safe_json_line(group))

    def _rewrite_groups(self, groups: list[dict[str, Any]]) -> None:
        with self._groups_path.open("w", encoding="utf-8") as fh:
            for g in groups:
                fh.write(_safe_json_line(g))

    def _append_messages(self, messages: list[dict[str, Any]]) -> None:
        with self._messages_path.open("a", encoding="utf-8") as fh:
            for m in messages:
                fh.write(self._encrypted_message_line(m))

    def _rewrite_messages(self, messages: list[dict[str, Any]]) -> None:
        with self._messages_path.open("w", encoding="utf-8") as fh:
            for m in messages:
                fh.write(self._encrypted_message_line(m))

    def _resolve_group_id(self, *, user_id: int, group_id: str) -> str:
        raw = str(group_id or "").strip()
        if not raw:
            return raw
        group = self._find(self._user_groups(user_id), raw)
        alias = str((group or {}).get("alias_group_id") or "").strip()
        if not alias:
            return raw
        target = self._find(self._user_groups(user_id), alias)
        return alias if target is not None else raw

    @staticmethod
    def _find(groups: list[dict[str, Any]], group_id: str) -> dict[str, Any] | None:
        return next((g for g in groups if str(g.get("id")) == str(group_id)), None)

    @staticmethod
    def _replace(groups: list[dict[str, Any]], updated: dict[str, Any]) -> list[dict[str, Any]]:
        return [updated if str(g.get("id")) == str(updated.get("id")) else g for g in groups]
