"""Shared mutable platform state and API key lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from secrets import compare_digest
from typing import Any

from app.domain.aiopen.principal import ScreenPrincipal

_KEY_INVALID = "AIOPEN_KEY_INVALID"
_KEY_EXPIRED = "AIOPEN_KEY_EXPIRED"
_SCOPE_DENIED = "AIOPEN_SCOPE_DENIED"
_RATE_LIMITED = "AIOPEN_RATE_LIMITED"
_QUOTA_EXCEEDED = "AIOPEN_QUOTA_EXCEEDED"


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
    """账号级 Key：作用域、过期、每分钟限流与每日配额。

    ``storage`` 返回 key 持久化文件路径（可选）；缺失时保持纯内存行为，
    便于单测与无数据目录环境。
    """

    def __init__(
        self,
        state: RuntimeState,
        env_key: Callable[[], str],
        token: Callable[[int], str],
        clock: Callable[[], float],
        storage: Callable[[], Path | None] | None = None,
    ) -> None:
        self._state = state
        self._env_key = env_key
        self._token = token
        self._clock = clock
        self._storage = storage
        self._rpm: dict[str, list[float]] = {}
        self._loaded = False

    # ── 持久化 ────────────────────────────────────────────────────────

    def _path(self) -> Path | None:
        if self._storage is None:
            return None
        try:
            return self._storage()
        except OSError:
            return None

    def _entries(self) -> dict[str, dict[str, Any]]:
        # 始终拿到可写引用：持久化加载必须挂回共享状态，否则重启后 Key 不可见。
        entries = self._state.keys(create=True)
        if not self._loaded:
            self._loaded = True
            path = self._path()
            if path is not None and path.is_file():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raw = None
                if isinstance(raw, dict):
                    for key, meta in raw.items():
                        if isinstance(key, str) and isinstance(meta, dict):
                            entries.setdefault(key, meta)
        return entries

    def _persist(self) -> None:
        path = self._path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(self._entries(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(path)
        except OSError:
            pass

    # ── 校验与生命周期 ────────────────────────────────────────────────

    def verify(self, provided: str | None) -> bool:
        """Require a configured key; uninitialized installations fail closed."""
        env_key = self._env_key()
        entries = self._entries()
        if not env_key and not entries:
            return False
        got = (provided or "").strip()
        if not got:
            return False
        if env_key and compare_digest(got.encode("utf-8"), env_key.encode("utf-8")):
            return True
        return got in entries

    def generate(
        self,
        label: str = "",
        *,
        principal: ScreenPrincipal | None = None,
        scopes: list[str] | None = None,
        expires_at: float | None = None,
        rate_limit_per_min: int | None = None,
        daily_quota: int | None = None,
    ) -> dict[str, Any]:
        key = "aiopen_" + self._token(24)
        now = self._clock()
        entry: dict[str, Any] = {
            "label": (label or "").strip() or "未命名",
            "created_at": now,
            "usage": {"day": self._day(now), "count": 0},
            "total_calls": 0,
            "error_calls": 0,
        }
        if principal is not None:
            entry.update(principal_id=principal.principal_id, tenant_id=principal.tenant_id)
        if scopes:
            entry["scopes"] = [str(item).strip() for item in scopes if str(item).strip()]
        if expires_at is not None:
            entry["expires_at"] = float(expires_at)
        if rate_limit_per_min is not None and int(rate_limit_per_min) > 0:
            entry["rate_limit_per_min"] = int(rate_limit_per_min)
        if daily_quota is not None and int(daily_quota) > 0:
            entry["daily_quota"] = int(daily_quota)
        self._entries()[key] = entry
        self._persist()
        return {"key": key, **entry}

    def resolve_principal(self, provided: str | None) -> ScreenPrincipal | None:
        """Legacy/environment keys authenticate a service, not a screen owner."""
        if not self.verify(provided):
            return None
        key = (provided or "").strip()
        env_key = self._env_key()
        if env_key and compare_digest(key.encode("utf-8"), env_key.encode("utf-8")):
            return None
        entry = self._entries().get(key)
        if not isinstance(entry, dict):
            return None
        return ScreenPrincipal.from_ids(entry.get("principal_id"), entry.get("tenant_id"))

    def revoke(self, key: str | None) -> bool:
        removed = self._entries().pop((key or "").strip(), None) is not None
        if removed:
            self._rpm.pop((key or "").strip(), None)
            self._persist()
        return removed

    def list_keys(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._env_key():
            out.append(
                {"key_preview": "env:AIOPEN_API_KEY", "label": "环境变量", "created_at": None}
            )
        now = self._clock()
        for key, meta in self._entries().items():
            self._roll_day(meta, now)
            out.append(
                {
                    "key_preview": key[:12] + "…",
                    "label": meta.get("label", ""),
                    "created_at": meta.get("created_at"),
                    "scopes": meta.get("scopes") or ["*"],
                    "expires_at": meta.get("expires_at"),
                    "rate_limit_per_min": meta.get("rate_limit_per_min"),
                    "daily_quota": meta.get("daily_quota"),
                    "today_calls": int((meta.get("usage") or {}).get("count") or 0),
                    "total_calls": int(meta.get("total_calls") or 0),
                    "error_calls": int(meta.get("error_calls") or 0),
                    "last_used_at": meta.get("last_used_at"),
                }
            )
        return out

    # ── 授权与计量 ────────────────────────────────────────────────────

    def authorize(
        self, provided: str | None, tool: str = "", *, now: float | None = None
    ) -> dict[str, Any]:
        """返回 ``{ok, code, message, key_preview}``；通过时附带 ``env`` 标记。"""
        got = (provided or "").strip()
        env_key = self._env_key()
        entries = self._entries()
        if not env_key and not entries:
            return self._deny(_KEY_INVALID, "未配置任何 AIOPEN Key")
        if not got:
            return self._deny(_KEY_INVALID, "缺少 X-AIOPEN-Key")
        if env_key and compare_digest(got.encode("utf-8"), env_key.encode("utf-8")):
            return {
                "ok": True,
                "code": "",
                "message": "",
                "key_preview": "env:AIOPEN_API_KEY",
                "env": True,
            }
        entry = entries.get(got)
        if not isinstance(entry, dict):
            return self._deny(_KEY_INVALID, "X-AIOPEN-Key 无效")
        current = float(now if now is not None else self._clock())
        preview = got[:12] + "…"
        expires_at = entry.get("expires_at")
        if expires_at is not None:
            try:
                expired = current >= float(expires_at)
            except (TypeError, ValueError):
                expired = False
            if expired:
                return self._deny(_KEY_EXPIRED, "Key 已过期", preview)
        scopes = entry.get("scopes")
        if tool and isinstance(scopes, list) and scopes and "*" not in scopes:
            if tool not in scopes:
                return self._deny(_SCOPE_DENIED, f"Key 未授权工具：{tool}", preview)
        limit = self._int(entry.get("rate_limit_per_min"))
        if limit > 0:
            window = [stamp for stamp in self._rpm.get(got, []) if current - stamp < 60.0]
            if len(window) >= limit:
                self._rpm[got] = window
                return self._deny(_RATE_LIMITED, f"超过每分钟 {limit} 次调用限制", preview)
            window.append(current)
            self._rpm[got] = window
        quota = self._int(entry.get("daily_quota"))
        if quota > 0:
            self._roll_day(entry, current)
            if int((entry.get("usage") or {}).get("count") or 0) >= quota:
                return self._deny(_QUOTA_EXCEEDED, f"已达每日 {quota} 次调用配额", preview)
        return {"ok": True, "code": "", "message": "", "key_preview": preview, "env": False}

    def record_use(
        self,
        provided: str | None,
        tool: str = "",
        *,
        ok: bool = True,
        now: float | None = None,
    ) -> dict[str, Any]:
        key = (provided or "").strip()
        env_key = self._env_key()
        if not key or (env_key and compare_digest(key.encode("utf-8"), env_key.encode("utf-8"))):
            return {"key_preview": "env:AIOPEN_API_KEY" if key else "", "label": "环境变量"}
        entry = self._entries().get(key)
        if not isinstance(entry, dict):
            return {"key_preview": key[:12] + "…", "label": ""}
        current = float(now if now is not None else self._clock())
        self._roll_day(entry, current)
        usage = entry.setdefault("usage", {"day": self._day(current), "count": 0})
        usage["count"] = int(usage.get("count") or 0) + 1
        entry["total_calls"] = int(entry.get("total_calls") or 0) + 1
        if not ok:
            entry["error_calls"] = int(entry.get("error_calls") or 0) + 1
        entry["last_used_at"] = current
        self._persist()
        return {"key_preview": key[:12] + "…", "label": str(entry.get("label") or "")}

    # ── 内部工具 ──────────────────────────────────────────────────────

    @staticmethod
    def _day(stamp: float) -> str:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d")

    @classmethod
    def _roll_day(cls, entry: dict[str, Any], stamp: float) -> None:
        day = cls._day(stamp)
        usage = entry.get("usage")
        if not isinstance(usage, dict) or usage.get("day") != day:
            entry["usage"] = {"day": day, "count": 0}

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _deny(code: str, message: str, key_preview: str = "") -> dict[str, Any]:
        return {"ok": False, "code": code, "message": message, "key_preview": key_preview}
