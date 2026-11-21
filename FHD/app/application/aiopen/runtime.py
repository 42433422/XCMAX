"""Shared mutable platform state and API key lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from hashlib import sha256
from pathlib import Path
from secrets import compare_digest
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any, Concatenate, ParamSpec, TypeVar

from filelock import FileLock

from app.domain.aiopen.principal import ScreenPrincipal

_KEY_INVALID = "AIOPEN_KEY_INVALID"
_KEY_EXPIRED = "AIOPEN_KEY_EXPIRED"
_SCOPE_DENIED = "AIOPEN_SCOPE_DENIED"
_RATE_LIMITED = "AIOPEN_RATE_LIMITED"
_QUOTA_EXCEEDED = "AIOPEN_QUOTA_EXCEEDED"
_CLIENT_PREFIX = "aiopen_client_"
_CLIENT_DIGEST_PREFIX = "client-sha256:"
_MAX_ACTIVE_CLIENT_KEYS = 8
_KeyParams = ParamSpec("_KeyParams")
_KeyResult = TypeVar("_KeyResult")


class ClientKeyLimitReached(Exception):
    """This principal already has the maximum number of active client keys."""


def _storage_key(secret: str) -> str:
    if secret.startswith(_CLIENT_PREFIX):
        return _CLIENT_DIGEST_PREFIX + sha256(secret.encode()).hexdigest()
    return "" if secret.startswith(_CLIENT_DIGEST_PREFIX) else secret


def _shared_keys(
    method: Callable[Concatenate[ApiKeyRegistry, _KeyParams], _KeyResult],
) -> Callable[Concatenate[ApiKeyRegistry, _KeyParams], _KeyResult]:
    """Serialize disk read/modify/write across workers using the existing filelock."""

    @wraps(method)
    def wrapped(
        self: ApiKeyRegistry, *args: _KeyParams.args, **kwargs: _KeyParams.kwargs
    ) -> _KeyResult:
        with self._lock:
            path = self._path()
            if path is None:
                return method(self, *args, **kwargs)
            path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(path) + ".lock", timeout=5):
                self._reload_shared(path)
                return method(self, *args, **kwargs)

    return wrapped


@dataclass
class RuntimeState:
    # AIOPEN control surfaces share this single runtime state.
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
        self._lock = RLock()

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
        with self._lock:
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
                            if isinstance(key, str) and key and isinstance(meta, dict):
                                entries.setdefault(key, meta)
            return entries

    def _reload_shared(self, path: Path) -> None:
        entries = self._state.keys(create=True)
        if not path.exists():
            if self._loaded:
                entries.clear()
            self._loaded = True
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            entries.clear()
            raise OSError("could not read shared API keys") from exc
        if not isinstance(raw, dict) or any(
            not isinstance(key, str) or not key or not isinstance(meta, dict)
            for key, meta in raw.items()
        ):
            entries.clear()
            raise OSError("invalid shared API keys")
        entries.clear()
        entries.update(raw)
        self._loaded = True

    def _persist(self) -> bool:
        path = self._path()
        if path is None:
            return True
        with self._lock:
            temporary = None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with NamedTemporaryFile(
                    mode="w", dir=path.parent, encoding="utf-8", delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump(self._entries(), stream, ensure_ascii=False, indent=2)
                temporary.replace(path)
                return True
            except OSError:
                if temporary is not None:
                    with suppress(OSError):
                        temporary.unlink(missing_ok=True)
                return False

    # ── 校验与生命周期 ────────────────────────────────────────────────

    @_shared_keys
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
        # Compatibility endpoints verify a service key without a per-tool scope.
        return got in entries and not got.startswith(_CLIENT_DIGEST_PREFIX)

    @_shared_keys
    def generate(
        self,
        label: str = "",
        *,
        principal: ScreenPrincipal | None = None,
        scopes: list[str] | None = None,
        expires_at: float | None = None,
        rate_limit_per_min: int | None = None,
        daily_quota: int | None = None,
        client_key: bool = False,
        keep_existing: bool = False,
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if client_key and (principal is None or not scopes or "*" in scopes or expires_at is None):
            raise ValueError("client keys require an owner, restricted scopes and expiration")
        key = (_CLIENT_PREFIX if client_key else "aiopen_") + self._token(24)
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
        if execution_context:
            from app.infrastructure.auth.agent_mod_scope import _bound_actor

            actor = _bound_actor(execution_context)
            if principal != ScreenPrincipal.from_user(actor):
                raise ValueError("API key execution identity does not match its owner")
            entry["execution_context"] = {
                name: deepcopy(execution_context[name])
                for name in (
                    "user_id",
                    "actor_id",
                    "tenant_id",
                    "mod_id",
                    "_actor_authorization",
                    "_mod_authorization",
                )
                if name in execution_context
            }
            entry["credential_id"] = sha256(key.encode()).hexdigest()
        if scopes:
            entry["scopes"] = [str(item).strip() for item in scopes if str(item).strip()]
        if expires_at is not None:
            entry["expires_at"] = float(expires_at)
        if rate_limit_per_min is not None and int(rate_limit_per_min) > 0:
            entry["rate_limit_per_min"] = int(rate_limit_per_min)
        if daily_quota is not None and int(daily_quota) > 0:
            entry["daily_quota"] = int(daily_quota)
        stored = _storage_key(key)
        with self._lock:
            entries = self._entries()
            removed = {}
            if client_key and principal is not None:
                if stored in entries:
                    raise OSError("client key generation collided with an existing key")
                owned = self._owned_client_keys(entries, principal)
                removed = owned
                if keep_existing:
                    now = self._clock()
                    removed = {
                        key: meta
                        for key, meta in owned.items()
                        if self._client_key_expired(meta, now)
                    }
                    if len(owned) - len(removed) >= _MAX_ACTIVE_CLIENT_KEYS:
                        raise ClientKeyLimitReached(
                            f"已达到 {_MAX_ACTIVE_CLIENT_KEYS} 个有效客户端口令的上限，请等待口令过期或撤销后重试。"
                        )
                for previous in removed:
                    del entries[previous]
                entry["key_preview"] = "客户端 · " + stored[-8:]
            entries[stored] = entry
            if not self._persist() and (client_key or execution_context):
                del entries[stored]
                entries.update(removed)
                raise OSError("could not persist client key")
            for previous in removed:
                self._rpm.pop(previous, None)
        return {
            "key": key,
            **{name: value for name, value in entry.items() if name != "execution_context"},
        }

    @_shared_keys
    def resolve_principal(self, provided: str | None) -> ScreenPrincipal | None:
        """Legacy/environment keys authenticate a service, not a screen owner."""
        key = (provided or "").strip()
        env_key = self._env_key()
        if env_key and compare_digest(key.encode("utf-8"), env_key.encode("utf-8")):
            return None
        entry = self._entries().get(_storage_key(key))
        if not isinstance(entry, dict):
            return None
        return ScreenPrincipal.from_ids(entry.get("principal_id"), entry.get("tenant_id"))

    @_shared_keys
    def revoke(self, key: str | None) -> bool:
        with self._lock:
            stored = _storage_key((key or "").strip())
            entries = self._entries()
            removed = entries.pop(stored, None)
            if removed is None:
                return False
            if not self._persist():
                entries[stored] = removed
                raise OSError("could not persist API key revocation")
            self._rpm.pop(stored, None)
        return True

    @_shared_keys
    def revoke_client_key(self, principal: ScreenPrincipal) -> bool:
        with self._lock:
            entries = self._entries()
            removed = self._owned_client_keys(entries, principal)
            for key in removed:
                del entries[key]
            if removed and not self._persist():
                entries.update(removed)
                raise OSError("could not persist client key revocation")
            for key in removed:
                self._rpm.pop(key, None)
            return bool(removed)

    @_shared_keys
    def has_active_client_key(self, principal: ScreenPrincipal) -> bool:
        with self._lock:
            now = self._clock()
            return any(
                not self._client_key_expired(meta, now)
                for meta in self._owned_client_keys(self._entries(), principal).values()
            )

    @staticmethod
    def _owned_client_keys(
        entries: dict[str, dict[str, Any]], principal: ScreenPrincipal
    ) -> dict[str, dict[str, Any]]:
        return {
            key: meta
            for key, meta in entries.items()
            if key.startswith(_CLIENT_DIGEST_PREFIX) and principal.owns(meta)
        }

    @staticmethod
    def _client_key_expired(meta: dict[str, Any], now: float) -> bool:
        expires_at = meta.get("expires_at")
        if isinstance(expires_at, bool) or not isinstance(expires_at, (str, int, float)):
            return True
        try:
            return not float(expires_at) > now
        except (TypeError, ValueError):
            return True

    @_shared_keys
    def list_keys(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._env_key():
            out.append(
                {"key_preview": "env:AIOPEN_API_KEY", "label": "环境变量", "created_at": None}
            )
        now = self._clock()
        for key, meta in self._entries().copy().items():
            self._roll_day(meta, now)
            out.append(
                {
                    "key_preview": meta.get("key_preview") or key[:12] + "…",
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

    def _execution_context(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        from app.infrastructure.auth.agent_mod_scope import _bound_actor
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        expires = entry.get("expires_at")
        if expires is not None and self._client_key_expired(entry, self._clock()):
            return None
        try:
            context = deepcopy(entry.get("execution_context"))
            if not isinstance(context, dict) or not entry.get("credential_id"):
                return None
            actor = _bound_actor(context)
            if ScreenPrincipal.from_user(actor) != ScreenPrincipal.from_ids(
                entry.get("principal_id"), entry.get("tenant_id")
            ):
                return None
        except RECOVERABLE_ERRORS:
            return None
        context["_credential_authorization"] = {
            "kind": "aiopen",
            "credential_id": entry["credential_id"],
            "scopes": list(entry.get("scopes") or ["*"]),
        }
        return context

    @_shared_keys
    def resolve_execution_context(self, provided: str | None) -> dict[str, Any] | None:
        entry = self._entries().get(_storage_key((provided or "").strip()))
        return self._execution_context(entry) if isinstance(entry, dict) else None

    @_shared_keys
    def permits_execution(self, context: dict[str, Any], tool_id: str, action: str) -> bool:
        """Recheck revocation, scope and the original actor before every attempt."""
        credential = context.get("_credential_authorization")
        if not isinstance(credential, dict) or credential.get("kind") != "aiopen":
            return False
        identifier = str(credential.get("credential_id") or "")
        for entry in self._entries().values():
            if not identifier or entry.get("credential_id") != identifier:
                continue
            actual = self._execution_context(entry)
            if actual is None or any(context.get(key) != value for key, value in actual.items()):
                return False
            scopes = actual["_credential_authorization"]["scopes"]
            return "*" in scopes or f"capability.{tool_id}.{action}" in scopes
        return False

    @_shared_keys
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
        stored = _storage_key(got)
        entry = entries.get(stored)
        if not isinstance(entry, dict):
            return self._deny(_KEY_INVALID, "X-AIOPEN-Key 无效")
        current = float(now if now is not None else self._clock())
        preview = str(entry.get("key_preview") or got[:12] + "…")
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
            window = [stamp for stamp in self._rpm.get(stored, []) if current - stamp < 60.0]
            if len(window) >= limit:
                self._rpm[stored] = window
                return self._deny(_RATE_LIMITED, f"超过每分钟 {limit} 次调用限制", preview)
            window.append(current)
            self._rpm[stored] = window
        quota = self._int(entry.get("daily_quota"))
        if quota > 0:
            self._roll_day(entry, current)
            if int((entry.get("usage") or {}).get("count") or 0) >= quota:
                return self._deny(_QUOTA_EXCEEDED, f"已达每日 {quota} 次调用配额", preview)
        return {"ok": True, "code": "", "message": "", "key_preview": preview, "env": False}

    @_shared_keys
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
        entry = self._entries().get(_storage_key(key))
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
        return {
            "key_preview": str(entry.get("key_preview") or key[:12] + "…"),
            "label": str(entry.get("label") or ""),
        }

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
