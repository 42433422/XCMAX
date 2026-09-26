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
        now = _utc_now()
        expires_at = _utc_after(ttl_seconds)
        normalized_base = _public_base_url(relay_base_url)
        with self._get_db() as db:
            self.ensure_tables(db)
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET pairing_code = 'x' || substr(relay_id, 1, 15)
                    WHERE expires_at < :now AND length(pairing_code) = 6
                      AND pairing_code BETWEEN '100000' AND '999999'
                    """
                ),
                {"now": now},
            )
            pairing_code = self._fresh_pairing_code(db)
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

    def renew_desktop_pairing(
        self, *, relay_id: str, desktop_token: str, ttl_seconds: int = 24 * 3600
    ) -> dict[str, Any] | None:
        now = _utc_now()
        expires_at = _utc_after(ttl_seconds)
        with self._get_db() as db:
            self.ensure_tables(db)
            desktop = self._desktop_for_token(
                db, relay_id=relay_id, desktop_token=desktop_token
            )
            if not desktop:
                return None
            code = self._fresh_pairing_code(db)
            updated = db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET pairing_code = :code, expires_at = :expires_at, updated_at = :now
                    WHERE relay_id = :relay_id AND desktop_token_hash = :token_hash
                      AND status IN ('pending', 'paired')
                    """
                ),
                {
                    "code": code,
                    "expires_at": expires_at,
                    "now": now,
                    "relay_id": relay_id.strip(),
                    "token_hash": _token_hash(desktop_token.strip()),
                },
            )
            if updated.rowcount != 1:
                return None
        return {
            "relay_id": relay_id.strip(),
            "pairing_code": code,
            "expires_at": expires_at,
            "exp": _epoch_from_iso(expires_at),
            "relay_base_url": desktop.get("relay_base_url") or "",
        }

    def bind_mobile_by_account(
        self,
        *,
        user_id: int,
        username: str,
        relay_id: str = "",
        pairing_code: str = "",
    ) -> dict[str, Any] | None:
        """Bind a desktop relay to the authenticated mobile account.

        The signed-in phone obtains a relay ID from a QR or LAN exchange, or
        resolves a six-digit device code through the cloud relay. An existing
        binding remains owned by its original mobile account.
        """
        clean_relay_id = relay_id.strip()
        clean_code = pairing_code.strip()
        if len(clean_code) != 6 or not clean_code.isdigit():
            return None
        now = _utc_now()
        with self._get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_desktops
                        WHERE ((:relay_id != '' AND relay_id = :relay_id)
                               OR (:relay_id = '' AND pairing_code = :pairing_code))
                          AND status IN ('pending', 'paired')
                        """
                    ),
                    {"relay_id": clean_relay_id, "pairing_code": clean_code},
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            data = _row_dict(row)
            if clean_code and str(data.get("pairing_code") or "") != clean_code:
                return None
            if str(data.get("expires_at") or "") < now:
                return None
            owner_id = int(data.get("mobile_user_id") or 0)
            if owner_id > 0 and owner_id != int(user_id):
                return None
            clean_relay_id = str(data.get("relay_id") or "").strip()
            updated = db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET status = 'paired',
                        mobile_user_id = :user_id,
                        mobile_username = :username,
                        updated_at = :updated_at
                    WHERE relay_id = :relay_id
                      AND pairing_code = :pairing_code
                      AND expires_at >= :updated_at
                      AND (mobile_user_id IS NULL OR mobile_user_id = 0
                           OR mobile_user_id = :user_id)
                    """
                ),
                {
                    "relay_id": clean_relay_id,
                    "pairing_code": clean_code,
                    "user_id": int(user_id),
                    "username": username.strip()[:200],
                    "updated_at": now,
                },
            )
            if updated.rowcount != 1:
                return None
            data.update(
                {
                    "status": "paired",
                    "mobile_user_id": int(user_id),
                    "mobile_username": username.strip()[:200],
                    "updated_at": now,
                }
            )
            return cast(dict[str, Any], self._public_desktop(data))
