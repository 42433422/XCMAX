"""Desktop pairing workflows for :class:`MobileRelayService`."""

from __future__ import annotations

import secrets
import uuid
from typing import Any, cast

from sqlalchemy import text

from app.services.mobile_relay_utils import (
    _epoch_from_iso,
    _json_dumps,
    _public_base_url,
    _row_dict,
    _token_hash,
    _utc_after,
    _utc_now,
)


class MobileRelayPairingMixin:
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def register_desktop(
        self,
        *,
        label: str,
        device_id: str,
        capabilities: dict[str, Any] | None = None,
        relay_base_url: str = "",
        ttl_seconds: int = 24 * 3600,
    ) -> dict[str, Any]:
        relay_id = uuid.uuid4().hex
        desktop_token = secrets.token_urlsafe(32)
        pairing_code = self._fresh_pairing_code()
        now = _utc_now()
        expires_at = _utc_after(ttl_seconds)
        normalized_base = _public_base_url(relay_base_url)
        with self._get_db() as db:
            self.ensure_tables(db)
            db.execute(
                text(
                    """
                    INSERT INTO mobile_relay_desktops (
                        relay_id, pairing_code, desktop_token_hash, desktop_label,
                        device_id, relay_base_url, status, capabilities_json,
                        expires_at, created_at, updated_at
                    ) VALUES (
                        :relay_id, :pairing_code, :desktop_token_hash, :desktop_label,
                        :device_id, :relay_base_url, 'pending', :capabilities_json,
                        :expires_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "relay_id": relay_id,
                    "pairing_code": pairing_code,
                    "desktop_token_hash": _token_hash(desktop_token),
                    "desktop_label": (label or "XCAGI 桌面执行端").strip()[:200],
                    "device_id": (device_id or "").strip()[:128],
                    "relay_base_url": normalized_base,
                    "capabilities_json": _json_dumps(capabilities or {}),
                    "expires_at": expires_at,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return {
            "relay_id": relay_id,
            "desktop_token": desktop_token,
            "pairing_code": pairing_code,
            "expires_at": expires_at,
            "exp": _epoch_from_iso(expires_at),
            "relay_base_url": normalized_base,
            "qr_json": {
                "v": 3,
                "kind": "xcagi_relay_pairing",
                "relay_id": relay_id,
                "code": pairing_code,
                "t": pairing_code,
                "relay_base_url": normalized_base,
            },
        }

    def confirm_mobile(
        self,
        *,
        user_id: int,
        username: str,
        relay_id: str,
        code: str,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        with self._get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_desktops
                        WHERE relay_id = :relay_id AND pairing_code = :code
                        """
                    ),
                    {"relay_id": relay_id.strip(), "code": code.strip()},
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            data = _row_dict(row)
            if data.get("status") == "revoked":
                return None
            if data.get("status") == "pending" and str(data.get("expires_at") or "") < now:
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET status = 'paired',
                        mobile_user_id = :user_id,
                        mobile_username = :username,
                        updated_at = :updated_at
                    WHERE relay_id = :relay_id
                    """
                ),
                {
                    "relay_id": relay_id.strip(),
                    "user_id": int(user_id),
                    "username": username.strip()[:200],
                    "updated_at": now,
                },
            )
            data.update(
                {
                    "status": "paired",
                    "mobile_user_id": int(user_id),
                    "mobile_username": username.strip()[:200],
                    "updated_at": now,
                }
            )
            return cast(dict[str, Any], self._public_desktop(data))

    def confirm_mobile_by_code(
        self,
        *,
        user_id: int,
        username: str,
        code: str,
    ) -> dict[str, Any] | None:
        clean_code = code.strip()
        if not clean_code:
            return None
        now = _utc_now()
        with self._get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_desktops
                        WHERE pairing_code = :code
                          AND status IN ('pending', 'paired')
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"code": clean_code},
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            data = _row_dict(row)
            if data.get("status") == "pending" and str(data.get("expires_at") or "") < now:
                return None
            relay_id = str(data.get("relay_id") or "").strip()
            if not relay_id:
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET status = 'paired',
                        mobile_user_id = :user_id,
                        mobile_username = :username,
                        updated_at = :updated_at
                    WHERE relay_id = :relay_id
                    """
                ),
                {
                    "relay_id": relay_id,
                    "user_id": int(user_id),
                    "username": username.strip()[:200],
                    "updated_at": now,
                },
            )
            data.update(
                {
                    "status": "paired",
                    "mobile_user_id": int(user_id),
                    "mobile_username": username.strip()[:200],
                    "updated_at": now,
                }
            )
            return cast(dict[str, Any], self._public_desktop(data))

    def bind_mobile_by_account(
        self,
        *,
        user_id: int,
        username: str,
        relay_id: str = "",
    ) -> dict[str, Any] | None:
        """Bind a desktop relay to the authenticated mobile account.

        The phone obtains ``relay_id`` from the LAN pairing exchange. Cloud
        binding is then authorized by the logged-in mobile account instead of a
        QR/short-code secret, which prevents stale QR relay IDs from becoming
        the source of truth.
        """
        clean_relay_id = relay_id.strip()
        if not clean_relay_id:
            return None
        now = _utc_now()
        with self._get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_desktops
                        WHERE relay_id = :relay_id
                          AND status IN ('pending', 'paired')
                        """
                    ),
                    {"relay_id": clean_relay_id},
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            data = _row_dict(row)
            if data.get("status") == "pending" and str(data.get("expires_at") or "") < now:
                return None
            owner_id = int(data.get("mobile_user_id") or 0)
            if owner_id > 0 and owner_id != int(user_id):
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET status = 'paired',
                        mobile_user_id = :user_id,
                        mobile_username = :username,
                        updated_at = :updated_at
                    WHERE relay_id = :relay_id
                    """
                ),
                {
                    "relay_id": clean_relay_id,
                    "user_id": int(user_id),
                    "username": username.strip()[:200],
                    "updated_at": now,
                },
            )
            data.update(
                {
                    "status": "paired",
                    "mobile_user_id": int(user_id),
                    "mobile_username": username.strip()[:200],
                    "updated_at": now,
                }
            )
            return cast(dict[str, Any], self._public_desktop(data))
