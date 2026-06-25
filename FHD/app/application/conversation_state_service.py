from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir

_CONVERSATION_STATE_FILENAME = "conversation_state.jsonl"


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


class ConversationStateService:
    """管理单人 AI 会话的显示/置顶/隐藏/关注/未读 状态。

    与会话的真实消息存储解耦 —— 该服务仅记录 UI 展示态，
    每个 ``user_id`` + ``conversation_id`` 对应一条状态记录。
    """

    def __init__(self, storage_root: str | Path | None = None) -> None:
        root = Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        self._state_path = root / _CONVERSATION_STATE_FILENAME
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 读写 ───────────────────────────────────────────────────────────

    def _read_all(self) -> list[dict[str, Any]]:
        if not self._state_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with self._state_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return rows

    def _rewrite_all(self, rows: list[dict[str, Any]]) -> None:
        with self._state_path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(_safe_json_line(r))

    # ── 查询 ───────────────────────────────────────────────────────────

    def get_state(self, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        """返回指定会话的状态；若不存在则返回默认态（新建一条记录）。"""
        rows = self._read_all()
        for r in rows:
            if int(r.get("user_id") or 0) == int(user_id) and str(r.get("conversation_id")) == str(
                conversation_id
            ):
                return self._public(r)

        new_row: dict[str, Any] = {
            "user_id": int(user_id),
            "conversation_id": str(conversation_id),
            "is_pinned": False,
            "is_hidden": False,
            "is_followed": True,
            "unread_count": 0,
        }
        rows.append(new_row)
        self._rewrite_all(rows)
        return self._public(new_row)

    def get_all_states(self, *, user_id: int) -> list[dict[str, Any]]:
        """返回当前用户所有会话的状态列表。"""
        uid = int(user_id)
        return [self._public(r) for r in self._read_all() if int(r.get("user_id") or 0) == uid]

    # ── 操作 ───────────────────────────────────────────────────────────

    def toggle_pinned(self, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        return self._update(
            user_id, conversation_id, lambda r: dict(r, is_pinned=not bool(r.get("is_pinned")))
        )

    def mark_unread(self, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        def _up(r: dict[str, Any]) -> dict[str, Any]:
            current = int(r.get("unread_count") or 0)
            return dict(r, unread_count=max(1, current + 1 if current > 0 else 1))

        return self._update(user_id, conversation_id, _up)

    def mark_read(self, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        return self._update(user_id, conversation_id, lambda r: dict(r, unread_count=0))

    def toggle_followed(self, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        return self._update(
            user_id,
            conversation_id,
            lambda r: dict(r, is_followed=not bool(r.get("is_followed", True))),
        )

    def toggle_hidden(self, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        return self._update(
            user_id, conversation_id, lambda r: dict(r, is_hidden=not bool(r.get("is_hidden")))
        )

    def delete(self, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        uid = int(user_id)
        cid = str(conversation_id)
        rows = self._read_all()
        remaining = [
            r
            for r in rows
            if not (int(r.get("user_id") or 0) == uid and str(r.get("conversation_id")) == cid)
        ]
        if len(remaining) == len(rows):
            return {"deleted": False, "conversation_id": cid}
        self._rewrite_all(remaining)
        return {"deleted": True, "conversation_id": cid}

    # ── 工具 ───────────────────────────────────────────────────────────

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": int(row.get("user_id") or 0),
            "conversation_id": str(row.get("conversation_id", "")),
            "is_pinned": bool(row.get("is_pinned")),
            "is_hidden": bool(row.get("is_hidden")),
            "is_followed": bool(row.get("is_followed", True)),
            "unread_count": int(row.get("unread_count") or 0),
        }

    def _update(
        self,
        user_id: int,
        conversation_id: str,
        updater: Any,
    ) -> dict[str, Any]:
        uid = int(user_id)
        cid = str(conversation_id)
        rows = self._read_all()
        target: dict[str, Any] | None = None
        for r in rows:
            if int(r.get("user_id") or 0) == uid and str(r.get("conversation_id")) == cid:
                target = r
                break
        if target is None:
            target = {
                "user_id": uid,
                "conversation_id": cid,
                "is_pinned": False,
                "is_hidden": False,
                "is_followed": True,
                "unread_count": 0,
            }
            rows.append(target)
        updated = updater(target)
        rows = [updated if r is target else r for r in rows]
        self._rewrite_all(rows)
        return self._public(updated)
