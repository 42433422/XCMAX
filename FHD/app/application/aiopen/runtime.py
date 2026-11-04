"""Shared mutable platform state and API key lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from secrets import compare_digest
from typing import Any

from app.domain.aiopen.principal import ScreenPrincipal


@dataclass
class RuntimeState:
    # The legacy qclaw panel and AIOPEN routes retain this same dictionary object.
    values: dict[str, Any]

    @property
    def remote_control_enabled(self) -> bool:
        return bool(self.values.get("remote_control_enabled", False))

    @property
    def openclaw_base(self) -> str:
        return str(self.values.get("openclaw_base", "http://localhost:28789")).rstrip("/")

    def keys(self, *, create: bool = False) -> dict[str, dict[str, Any]]:
        entries = self.values.get("runtime_keys")
        if isinstance(entries, dict):
            return entries
        if create:
            entries = {}
            self.values["runtime_keys"] = entries
            return entries
        return {}


class ApiKeyRegistry:
    def __init__(
        self,
        state: RuntimeState,
        env_key: Callable[[], str],
        token: Callable[[int], str],
        clock: Callable[[], float],
    ) -> None:
        self._state = state
        self._env_key = env_key
        self._token = token
        self._clock = clock

    def verify(self, provided: str | None) -> bool:
        """Require a configured key; uninitialized installations fail closed."""
        env_key = self._env_key()
        runtime_keys = self._state.keys()
        if not env_key and not runtime_keys:
            return False
        got = (provided or "").strip()
        if not got:
            return False
        if env_key and compare_digest(got.encode("utf-8"), env_key.encode("utf-8")):
            return True
        return got in runtime_keys

    def generate(
        self, label: str = "", *, principal: ScreenPrincipal | None = None
    ) -> dict[str, Any]:
        key = "aiopen_" + self._token(24)
        entry = {"label": (label or "").strip() or "未命名", "created_at": self._clock()}
        if principal is not None:
            entry.update(principal_id=principal.principal_id, tenant_id=principal.tenant_id)
        self._state.keys(create=True)[key] = entry
        return {"key": key, **entry}

    def resolve_principal(self, provided: str | None) -> ScreenPrincipal | None:
        """Legacy/environment keys authenticate a service, not a screen owner."""
        if not self.verify(provided):
            return None
        key = (provided or "").strip()
        env_key = self._env_key()
        if env_key and compare_digest(key.encode("utf-8"), env_key.encode("utf-8")):
            return None
        entry = self._state.keys().get(key)
        if not isinstance(entry, dict):
            return None
        return ScreenPrincipal.from_ids(entry.get("principal_id"), entry.get("tenant_id"))

    def revoke(self, key: str | None) -> bool:
        return self._state.keys(create=True).pop((key or "").strip(), None) is not None

    def list_keys(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._env_key():
            out.append(
                {"key_preview": "env:AIOPEN_API_KEY", "label": "环境变量", "created_at": None}
            )
        out.extend(
            {
                "key_preview": key[:12] + "…",
                "label": meta.get("label", ""),
                "created_at": meta.get("created_at"),
            }
            for key, meta in self._state.keys().items()
        )
        return out
