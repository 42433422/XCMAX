"""AI 群聊服务（微信式多 AI 群组）。

自包含、按用户隔离、jsonl 持久化（与超级员工服务同一套存储惯例），
不触碰现有人际 IM（``ImConversation`` 等）以零回归。

能力：
- 默认按 6 个部门（``config/duty_roster.json``）种出 6 个群；
- 用户可创建自定义群、把任意 AI 员工拉进/移出群；
- 用户在群里发消息后，AI 成员各回一条；若 @ 了具体成员，则只有被 @ 的成员回复。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir

# 单条用户消息最多触发的 AI 回复数，避免大群一次发太多请求。
MAX_RESPONDERS = 6
# 喂给单个 AI 的群历史条数。
CONTEXT_TURNS = 10

CompletionFn = Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


async def _default_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
    # 延迟导入，避免在不需要 LLM 的路径（建群/拉人/读消息）上引入依赖。
    from app.mod_sdk.mod_employee_llm import mod_employee_complete

    return await mod_employee_complete(messages, max_tokens=600, temperature=0.4)


def _default_departments() -> dict[str, Any]:
    try:
        from app.mod_sdk.duty_roster import load_departments

        depts = load_departments()
        return depts if isinstance(depts, dict) else {}
    except Exception:  # noqa: BLE001 - 部门配置缺失时回退到内置 6 部门
        return {}


# 部门配置不可用时的内置兜底（保证"默认 6 部门 6 个群"始终成立）。
_FALLBACK_DEPARTMENTS: list[tuple[str, str]] = [
    ("ops_acquisition", "O-A 获客部"),
    ("ops_partner", "O-B 伙伴部"),
    ("prod_web", "P-W 网站部"),
    ("prod_mod", "P-M Mod 部"),
    ("prod_software", "P-S 软件部"),
    ("shared_retention", "S-R 归档部"),
]


class AiGroupChatService:
    """微信式 AI 群聊：建群 / 拉 AI 成员 / 群内多 AI 回复。"""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        completion_fn: CompletionFn | None = None,
        department_loader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        root = Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        self._root = root / "ai_group_chat"
        self._root.mkdir(parents=True, exist_ok=True)
        self._groups_path = self._root / "groups.jsonl"
        self._messages_path = self._root / "messages.jsonl"
        self._completion_fn = completion_fn or _default_completion
        self._department_loader = department_loader or _default_departments

    # ── 公开 API ──

    def list_groups(self, *, user_id: int) -> list[dict[str, Any]]:
        groups = self._user_groups(user_id)
        if not groups:
            groups = self._seed_department_groups(user_id)
        previews = self._latest_previews(user_id)
        return [self._public_group(g, previews.get(str(g.get("id")))) for g in groups]

    def create_group(self, *, user_id: int, name: str) -> dict[str, Any]:
        title = (name or "").strip()
        if not title:
            raise ValueError("群名不能为空")
        group = {
            "id": uuid.uuid4().hex,
            "user_id": int(user_id),
            "name": title[:60],
            "department_key": "",
            "members": [],
            "created_at": _utc_now(),
        }
        self._append_group(group)
        return self._public_group(group, None)

    def add_member(self, *, user_id: int, group_id: str, member: dict[str, Any]) -> dict[str, Any]:
        employee_id = str(member.get("employee_id") or "").strip()
        if not employee_id:
            raise ValueError("employee_id 不能为空")
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        if any(str(m.get("employee_id")) == employee_id for m in members):
            return self._public_group(group, None)  # 已在群里，幂等
        members.append(
            {
                "employee_id": employee_id,
                "mod_id": str(member.get("mod_id") or ""),
                "name": str(member.get("name") or employee_id)[:60],
                "avatar": str(member.get("avatar") or ""),
                "summary": str(member.get("summary") or "")[:280],
            }
        )
        group["members"] = members
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def remove_member(self, *, user_id: int, group_id: str, employee_id: str) -> dict[str, Any]:
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["members"] = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id")) != str(employee_id)
        ]
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def get_messages(
        self, *, user_id: int, group_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = [
            self._public_message(r)
            for r in self._read_messages()
            if int(r.get("user_id") or 0) == int(user_id)
            and str(r.get("group_id")) == str(group_id)
        ]
        return rows[-max(1, min(int(limit), 300)) :]

    async def post_message(
        self,
        *,
        user_id: int,
        group_id: str,
        text: str,
        sender_name: str = "我",
        mentions: list[str] | None = None,
    ) -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            raise ValueError("message 不能为空")
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")

        user_msg = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="user",
            sender_id="user",
            sender_name=sender_name or "我",
            sender_avatar="",
            body=body,
        )
        new_messages = [user_msg]

        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        responders = self._pick_responders(members, body, mentions)
        history = self.get_messages(user_id=user_id, group_id=group_id, limit=CONTEXT_TURNS)
        history = history + [self._public_message(user_msg)]

        for member in responders:
            reply = await self._ai_reply(group, member, history)
            ai_msg = self._message_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=str(member.get("employee_id")),
                sender_name=str(member.get("name") or member.get("employee_id")),
                sender_avatar=str(member.get("avatar") or ""),
                body=reply,
            )
            new_messages.append(ai_msg)
            history = history + [self._public_message(ai_msg)]

        self._append_messages(new_messages)
        return {
            "group": self._public_group(group, None),
            "messages": [self._public_message(m) for m in new_messages],
        }

    # ── 回复编排 ──

    def _pick_responders(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> list[dict[str, Any]]:
        if not members:
            return []
        # 显式 mentions（employee_id）优先。
        explicit = {str(m).strip() for m in (mentions or []) if str(m).strip()}
        # 文本里的 @名字 也算定向。
        for m in members:
            name = str(m.get("name") or "")
            if name and f"@{name}" in text:
                explicit.add(str(m.get("employee_id")))
        if explicit:
            targeted = [m for m in members if str(m.get("employee_id")) in explicit]
            return targeted[:MAX_RESPONDERS]
        # 无定向：全员各回一条（上限保护）。
        return members[:MAX_RESPONDERS]

    async def _ai_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> str:
        group_name = str(group.get("name") or "AI 群聊")
        me = str(member.get("name") or member.get("employee_id"))
        summary = str(member.get("summary") or "")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        system = (
            f"你是群聊「{group_name}」里的 AI 成员「{me}」。{summary}\n"
            f"群成员有：{roster}。\n"
            "请只代表你自己、用一两句话简洁地回应群里用户的最新消息；"
            "不要替其他成员发言，不要复述别人说过的话，不要加“作为AI”之类的免责声明。"
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        user_content = f"【群最近对话】\n{transcript}\n\n请以「{me}」身份回应最新这条消息。"
        try:
            res = await self._completion_fn(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ]
            )
        except Exception as exc:  # noqa: BLE001
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            return str(res["content"]).strip()
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return f"（{me} 暂时无法回应{f'：{err}' if err else ''}）"

    # ── 部门种子 ──

    def _seed_department_groups(self, user_id: int) -> list[dict[str, Any]]:
        depts = self._department_loader()
        pairs: list[tuple[str, str]] = []
        if isinstance(depts, dict) and depts:
            for key, info in depts.items():
                label = ""
                if isinstance(info, dict):
                    label = str(info.get("label") or "").strip()
                pairs.append((str(key), label or str(key)))
        if not pairs:
            pairs = list(_FALLBACK_DEPARTMENTS)
        seeded: list[dict[str, Any]] = []
        for key, label in pairs:
            seeded.append(
                {
                    "id": f"dept:{key}",
                    "user_id": int(user_id),
                    "name": label,
                    "department_key": key,
                    "members": [],
                    "created_at": _utc_now(),
                }
            )
        for g in seeded:
            self._append_group(g)
        return seeded

    # ── 持久化 ──

    def _public_group(
        self, group: dict[str, Any], preview: dict[str, Any] | None
    ) -> dict[str, Any]:
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        return {
            "id": str(group.get("id")),
            "name": str(group.get("name") or ""),
            "department_key": str(group.get("department_key") or ""),
            "member_count": len(members),
            "members": [
                {
                    "employee_id": str(m.get("employee_id")),
                    "mod_id": str(m.get("mod_id") or ""),
                    "name": str(m.get("name") or ""),
                    "avatar": str(m.get("avatar") or ""),
                    "summary": str(m.get("summary") or ""),
                }
                for m in members
            ],
            "created_at": str(group.get("created_at") or ""),
            "last_message_preview": str((preview or {}).get("preview") or ""),
            "last_message_at": str((preview or {}).get("created_at") or ""),
        }

    def _public_message(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("id") or ""),
            "group_id": str(row.get("group_id") or ""),
            "role": str(row.get("role") or "ai"),
            "sender_id": str(row.get("sender_id") or ""),
            "sender_name": str(row.get("sender_name") or ""),
            "sender_avatar": str(row.get("sender_avatar") or ""),
            "body": str(row.get("body") or ""),
            "created_at": str(row.get("created_at") or ""),
        }

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
    ) -> dict[str, Any]:
        return {
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
        return [g for g in self._all_groups() if int(g.get("user_id") or 0) == int(user_id)]

    def _all_groups(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self._groups_path)

    def _read_messages(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self._messages_path)

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
                fh.write(_safe_json_line(m))

    @staticmethod
    def _find(groups: list[dict[str, Any]], group_id: str) -> dict[str, Any] | None:
        return next((g for g in groups if str(g.get("id")) == str(group_id)), None)

    @staticmethod
    def _replace(groups: list[dict[str, Any]], updated: dict[str, Any]) -> list[dict[str, Any]]:
        return [updated if str(g.get("id")) == str(updated.get("id")) else g for g in groups]


__all__ = ["AiGroupChatService", "MAX_RESPONDERS"]
