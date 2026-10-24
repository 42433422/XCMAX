"""Public group/message shapes and persisted message row construction."""

from __future__ import annotations

import uuid
from typing import Any

from app.application.group_chat.constants import (
    _BROKEN_MARKDOWN_LINK_RE,
    _LEGACY_SUPER_EMPLOYEE_IDS,
    _MARKDOWN_LINK_RE,
    _RELAY_TASK_ID_RE,
    _SUPER_EMPLOYEE_IDS,
    _TEMP_PATH_RE,
    _XIAOC_ASSISTANT_ID,
    PUBLIC_ACCEPTANCE_BODY_MAX_CHARS,
    PUBLIC_CHAT_BODY_MAX_CHARS,
)
from app.application.group_chat.employee_registry import _member_public_shape, _utc_now
from app.application.group_chat.message_formatting import ChatFormatting


class ChatProjection:
    @staticmethod
    def canonical_group_name(group: dict[str, Any]) -> str:
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        ids = {str(m.get("employee_id") or "").strip() for m in members}
        name = str(group.get("name") or "").strip()
        has_super_roster = _SUPER_EMPLOYEE_IDS.issubset(ids) or _LEGACY_SUPER_EMPLOYEE_IDS.issubset(
            ids
        )
        if has_super_roster and _XIAOC_ASSISTANT_ID in ids:
            roster_like = (
                not name
                or name in {"新建群聊", "群聊"}
                or (
                    "超级员工-Codex" in name
                    and "超级员工-Cursor" in name
                    and ("超级员工-Claude" in name)
                )
            )
            if roster_like:
                return "超级开发部"
        return name

    @staticmethod
    def public_group(group: dict[str, Any], preview: dict[str, Any] | None) -> dict[str, Any]:
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        return {
            "id": str(group.get("id")),
            "name": ChatProjection.canonical_group_name(group),
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

    @staticmethod
    def public_message(row: dict[str, Any]) -> dict[str, Any]:
        kind = str(row.get("kind") or "")
        body = str(row.get("body") or "")
        if kind in {"work_report", "work_progress", "relay_work_report", "work_acceptance"}:
            body = ChatProjection.clean_public_chat_body(body)
            if kind == "work_acceptance":
                body = ChatProjection.compact_public_acceptance_body(body)
            body = ChatProjection.cap_public_chat_body(
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
    def cap_public_chat_body(body: str, limit: int = PUBLIC_CHAT_BODY_MAX_CHARS) -> str:
        text = str(body or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n\n（聊天里已折叠长执行输出；完整内容保留在执行端记录。）"

    @staticmethod
    def clean_public_chat_body(body: str) -> str:
        lines = []
        for raw_line in str(body or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = _TEMP_PATH_RE.sub("临时执行工作区", raw_line)
            line = _MARKDOWN_LINK_RE.sub("\\1", line)
            line = _BROKEN_MARKDOWN_LINK_RE.sub("\\1", line)
            line = _RELAY_TASK_ID_RE.sub("。", line)
            for token in ("**", "__", "`"):
                line = line.replace(token, "")
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    @staticmethod
    def compact_public_acceptance_body(body: str) -> str:
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
            f"- {ChatFormatting.chat_friendly_summary(line, limit=70, include_detail_note=False)}"
            for line in member_lines
        ]
        out = [title]
        if conclusion:
            out.append(conclusion)
        if task:
            out.append(
                ChatFormatting.chat_friendly_summary(task, limit=72, include_detail_note=False)
            )
        if compact_members:
            out.append("成员：")
            out.extend(compact_members)
        if risk:
            out.append(risk)
        out.append("下一步：满意就继续派下一步；不满意就直接说要谁补什么。")
        return "\n".join(out)

    @staticmethod
    def message_row(
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

    @staticmethod
    def latest_previews(rows: list[dict[str, Any]], user_id: int) -> dict[str, dict[str, Any]]:
        previews: dict[str, dict[str, Any]] = {}
        for r in rows:
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
