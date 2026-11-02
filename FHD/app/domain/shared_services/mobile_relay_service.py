"""Cloud relay binding and task queue for mobile-to-desktop dispatch."""

from __future__ import annotations

import json
import logging
import secrets as secrets
from typing import Any, cast

from app.application.mobile_relay_ports import PairingPorts, TaskPorts
from app.db.session import get_db
from app.domain.shared_services.mobile_relay_pairing import RelayPairing
from app.domain.shared_services.mobile_relay_tasks import RelayTaskQueue
from app.domain.shared_services.mobile_relay_utils import _epoch_from_iso as _epoch_from_iso
from app.domain.shared_services.mobile_relay_utils import _json_dumps as _json_dumps
from app.domain.shared_services.mobile_relay_utils import _json_loads as _json_loads
from app.domain.shared_services.mobile_relay_utils import _public_base_url as _normalize_public_base_url
from app.domain.shared_services.mobile_relay_utils import _row_dict as _row_dict
from app.domain.shared_services.mobile_relay_utils import _token_hash as _token_hash
from app.domain.shared_services.mobile_relay_utils import _utc_after as _utc_after
from app.domain.shared_services.mobile_relay_utils import _utc_now as _utc_now
from app.infrastructure.mobile_relay import repository
from app.infrastructure.topology import FHD_API_BASE_URL
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _public_base_url(raw: str) -> str:
    """Preserve the legacy helper using the deployment-configured default."""
    return _normalize_public_base_url(raw, default_base_url=FHD_API_BASE_URL)


class MobileRelayService:
    """Compose SQL storage, pairing and task execution through explicit capabilities."""

    def __init__(self):
        self._pairing = RelayPairing(
            PairingPorts(
                database=lambda: self._get_db(),
                ensure_tables=lambda db: self.ensure_tables(db),
                fresh_pairing_code=lambda db: self._fresh_pairing_code(db),
                desktop_for_token=lambda db, relay_id, desktop_token: self._desktop_for_token(
                    db, relay_id=relay_id, desktop_token=desktop_token
                ),
                public_desktop=lambda data: self._public_desktop(data),
                public_base_url=FHD_API_BASE_URL,
            )
        )
        self._tasks = RelayTaskQueue(
            TaskPorts(
                database=lambda: self._get_db(),
                ensure_tables=lambda db: self.ensure_tables(db),
                desktop_belongs_to_user=lambda user_id, relay_id: self._desktop_belongs_to_user(
                    user_id=user_id, relay_id=relay_id
                ),
                desktop_for_token=lambda db, relay_id, desktop_token: self._desktop_for_token(
                    db, relay_id=relay_id, desktop_token=desktop_token
                ),
                public_desktop=lambda data: self._public_desktop(data),
                notify_task_creator=lambda task: self._notify_task_creator(task),
                get_task=lambda user_id, task_id: self.get_task(user_id=user_id, task_id=task_id),
            )
        )

    @staticmethod
    def _get_db():
        return get_db()

    def ensure_tables(self, db) -> None:
        return repository.ensure_tables(db)

    def list_desktops(self, *, user_id: int) -> list[dict[str, Any]]:
        return repository.list_desktops(
            user_id=user_id,
            database=lambda: get_db(),
            ensure_schema=lambda db: self.ensure_tables(db),
            project=lambda data: self._public_desktop(data),
        )

    @staticmethod
    def _notify_task_creator(task: dict[str, Any]) -> None:
        """CLI 执行类任务(*.invoke)到达终态时推送创建者。

        git.merge/diff/discard 是人守在 App 里等结果的同步交互，事后补推只会
        变成噪音，跳过；cancelled 是用户自己取消的，也不推。推送失败仅记日志，
        绝不影响 complete 主流程。channel 必须用 App 已注册的通知渠道(xcagi_chat)。
        """
        try:
            uid = int(task.get("created_by_user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        kind = str(task.get("kind") or "").strip()
        status = str(task.get("status") or "").strip()
        title = {
            "completed": "✅ 超级员工任务完成",
            "failed": "❌ 超级员工任务失败",
            "blocked": "⏸️ 超级员工任务受阻",
        }.get(status)
        if uid <= 0 or not kind.endswith(".invoke") or not title:
            return
        # _row_dict 已把 result_json 解析进 "result"；直查裸行时兜底再解一次。
        result = task.get("result")
        if not isinstance(result, dict):
            try:
                result = json.loads(task.get("result_json") or "{}")
            except (TypeError, ValueError):
                result = {}
        body = ""
        if isinstance(result, dict):
            body = str(
                result.get("summary")
                or result.get("answer")
                or result.get("output")
                or result.get("error_message")
                or result.get("error")
                or ""
            ).strip()
        tool = kind.split(".", 1)[0]
        if not body:
            body = f"{tool} 已结束本次任务，打开对话查看详情。"
        try:
            from app.domain.shared_services.mobile_push import notify_user

            notify_user(
                uid,
                title=title,
                body=body[:200],
                data={
                    "channel": "xcagi_chat",
                    "type": "relay_task_done",
                    "route": "xcagi://chat",
                    "task_id": str(task.get("task_id") or ""),
                    "task_status": status,
                    "tool": tool,
                },
            )
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - 推送是尽力而为的旁路
            logger.warning(
                "relay task completion push failed task_id=%s", task.get("task_id"), exc_info=True
            )

    def _fresh_pairing_code(self, db) -> str:
        return repository.fresh_pairing_code(db)

    def _desktop_belongs_to_user(self, *, user_id: int, relay_id: str) -> bool:
        return repository.desktop_belongs_to_user(
            user_id=user_id,
            relay_id=relay_id,
            database=lambda: get_db(),
            ensure_schema=lambda db: self.ensure_tables(db),
        )

    def _desktop_for_token(self, db, *, relay_id: str, desktop_token: str) -> dict[str, Any] | None:
        return repository.desktop_for_token(db, relay_id=relay_id, desktop_token=desktop_token)

    def _public_desktop(self, data: dict[str, Any]) -> dict[str, Any]:
        return repository.public_desktop(data)

    def register_desktop(
        self,
        *,
        label: str,
        device_id: str,
        capabilities: dict[str, Any] | None = None,
        relay_base_url: str = "",
        ttl_seconds: int = 24 * 3600,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._pairing.register_desktop(
                label=label,
                device_id=device_id,
                capabilities=capabilities,
                relay_base_url=relay_base_url,
                ttl_seconds=ttl_seconds,
            ),
        )

    def renew_desktop_pairing(
        self, *, relay_id: str, desktop_token: str, ttl_seconds: int = 24 * 3600
    ) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self._pairing.renew_desktop_pairing(
                relay_id=relay_id, desktop_token=desktop_token, ttl_seconds=ttl_seconds
            ),
        )

    def bind_mobile_by_account(
        self, *, user_id: int, username: str, relay_id: str = "", pairing_code: str = ""
    ) -> dict[str, Any] | None:
        """Bind a desktop relay to the authenticated mobile account.

        The signed-in phone obtains a relay ID from a QR or LAN exchange, or
        resolves a six-digit device code through the cloud relay. An existing
        binding remains owned by its original mobile account.
        """
        return cast(
            dict[str, Any] | None,
            self._pairing.bind_mobile_by_account(
                user_id=user_id, username=username, relay_id=relay_id, pairing_code=pairing_code
            ),
        )

    def create_task(
        self, *, user_id: int, relay_id: str, kind: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self._tasks.create_task(user_id=user_id, relay_id=relay_id, kind=kind, payload=payload),
        )

    def get_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        return cast(dict[str, Any] | None, self._tasks.get_task(user_id=user_id, task_id=task_id))

    def cancel_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        """手机端取消任务：仅 queued/running 可取消，标记为 cancelled。"""
        return cast(
            dict[str, Any] | None, self._tasks.cancel_task(user_id=user_id, task_id=task_id)
        )

    def poll_desktop(
        self, *, relay_id: str, desktop_token: str, max_tasks: int = 5
    ) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self._tasks.poll_desktop(
                relay_id=relay_id, desktop_token=desktop_token, max_tasks=max_tasks
            ),
        )

    def complete_desktop_task(
        self,
        *,
        relay_id: str,
        desktop_token: str,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self._tasks.complete_desktop_task(
                relay_id=relay_id,
                desktop_token=desktop_token,
                task_id=task_id,
                status=status,
                result=result,
            ),
        )
