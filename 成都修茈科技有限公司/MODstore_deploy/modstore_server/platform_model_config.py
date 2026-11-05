"""Encrypted platform credentials shared by gateway and employee workers."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from modstore_server.llm_crypto import (
    decrypt_secret,
    encrypt_secret,
    fernet_configured,
    mask_api_key,
)

_LOCK = threading.RLock()
SCOPE = "shared_market_gateway"
SCOPE_DESCRIPTION = (
    "供连接此市场模型网关、共享同一持久化配置目录和加密主密钥的 API/员工节点使用；"
    "下一次模型调用读取新配置。独立部署、桌面本地直连模型和其他网关不会自动同步。"
)
BYOK_POLICY = (
    "用户有效 BYOK 优先且仅供该用户使用；平台密钥供未使用 BYOK 的平台调用共享。"
    "跟随平台模式使用最新平台默认和平台凭据；用户明确选择与 BYOK 模式保持独立。"
    "BYOK 不可用时不自动切换为收费平台；员工显式运行路线保持优先。"
)


class PlatformConfigError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class PlatformApiKey(str):
    """Legacy string contract with the endpoint snapshot bound to this exact key.

    No global credential cache: a new value is read on every resolution. Keeping
    the snapshot with the key prevents old two-step callers from mixing a key
    read before rotation with an endpoint read after rotation.
    """

    configuration: Mapping[str, Any]

    def __new__(cls, value: str, configuration: dict[str, Any]):
        instance = super().__new__(cls, value)
        instance.configuration = MappingProxyType(
            {
                key: configuration[key]
                for key in ("provider", "base_url", "model", "display_name", "revision")
            }
            | {"source": configuration.get("source", "stored")}
        )
        return instance

    @property
    def managed(self) -> bool:
        return bool(self.configuration["source"] == "stored")

    def __repr__(self) -> str:
        return "PlatformApiKey('[REDACTED]')"

    def __str__(self) -> str:
        return self

    def strip(self, chars: str | None = None) -> PlatformApiKey:
        value = super().strip(chars)
        return self if value == self else PlatformApiKey(value, dict(self.configuration))


def config_path() -> Path:
    from modstore_server.db.db_base import default_db_path

    root = os.environ.get("MODSTORE_DATA_DIR") or os.environ.get("MODSTORE_RUNTIME_DIR")
    return (
        (Path(root).expanduser().resolve() if root else default_db_path().parent)
        / "llm"
        / "platform-model-config.json"
    )


@contextmanager
def _locked():
    """Use the same lock location on every worker sharing the persisted file."""
    with _LOCK:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.write(b" ")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_unlocked() -> dict[str, Any]:
    path = config_path()
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {"version": 1, "default_provider": None, "providers": {}}
    except (OSError, ValueError):
        raise PlatformConfigError("平台模型配置无法读取，请检查服务端持久化存储", 503) from None
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or not isinstance(state.get("providers"), dict)
    ):
        raise PlatformConfigError("平台模型配置损坏，请联系管理员恢复", 503)
    for provider, row in state["providers"].items():
        if (
            not isinstance(row, dict)
            or row.get("provider") != provider
            or any(
                not isinstance(row.get(key), str) or not row[key]
                for key in ("api_key_encrypted", "base_url", "model", "revision")
            )
        ):
            raise PlatformConfigError("平台模型配置损坏，请联系管理员恢复", 503)
    if state.get("default_provider") and state["default_provider"] not in state["providers"]:
        raise PlatformConfigError("平台默认模型配置损坏，请联系管理员恢复", 503)
    return state


def read_state() -> dict[str, Any]:
    try:
        try:
            config_path().stat()
        except FileNotFoundError:
            # Existing environment-only deployments may mount code/config read-only.
            return {"version": 1, "default_provider": None, "providers": {}}
        with _locked():
            return _read_unlocked()
    except OSError:
        raise PlatformConfigError("平台模型配置存储不可用", 503) from None


def stored_config(provider: str) -> dict[str, Any] | None:
    row: dict[str, Any] | None = read_state()["providers"].get(provider)
    return row


def stored_key(row: dict[str, Any]) -> str:
    try:
        key = decrypt_secret(row["api_key_encrypted"]).strip()
        if not key:
            raise ValueError("empty key")
        return key
    except (ValueError, RuntimeError, TypeError, UnicodeError):
        raise PlatformConfigError("平台密钥无法解密，请检查服务端加密主密钥", 503) from None


def normalize_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(c) < 33 for c in raw)
            or "\\" in raw
        ):
            raise ValueError("invalid URL")
        _ = parsed.port
    except ValueError:
        raise PlatformConfigError(
            "API 地址必须是无用户名、密码、查询参数的 HTTPS 基础地址"
        ) from None
    raw = raw.removesuffix("/chat/completions")
    if not urlsplit(raw).path:
        raw += "/v1"
    return raw


def _environment_config(provider: str) -> dict[str, Any]:
    from modstore_server.llm_key_resolver import (
        _environment_api_key,
        _environment_base_url,
    )
    from modstore_server.services.llm import _BENCH_DEFAULT_MODELS

    key = _environment_api_key(provider)
    base = (_environment_base_url(provider) or "").rstrip("/")
    if base and not base.endswith(("/v1", "/v2", "/v3", "/v4")):
        base += "/v1"
    try:
        base = normalize_base_url(base)
    except PlatformConfigError:
        base = ""  # Never publish credentials embedded in a legacy environment URL.
    return {
        "provider": provider,
        "base_url": base,
        "model": _BENCH_DEFAULT_MODELS.get(provider, ""),
        "display_name": "",
        "has_key": bool(key and base),
        "masked_key": mask_api_key(key or ""),
        "source": "environment" if key else "none",
        "revision": None,
    }


def public_config(provider: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state if state is not None else read_state()
    row: dict[str, Any] | None = state["providers"].get(provider)
    if row:
        result = {
            key: row.get(key)
            for key in ("provider", "base_url", "model", "display_name", "revision")
        }
        try:
            masked_key = mask_api_key(stored_key(row))
            available = True
        except PlatformConfigError:
            masked_key, available = "（密钥无法解密，请重新输入）", False
        result.update(has_key=available, masked_key=masked_key, source="stored")
    else:
        result = _environment_config(provider)
    result["is_default"] = state.get("default_provider") == provider
    return result


def prepare_config(
    provider: str, payload: dict[str, Any], state: dict[str, Any]
) -> tuple[dict[str, str], str]:
    """A preserved credential is never sent to a newly supplied endpoint."""
    base = normalize_base_url(payload["base_url"])
    model = payload["model"].strip()
    display_name = payload["display_name"].strip() or model
    if not model or any(ord(c) < 32 for c in model + display_name):
        raise PlatformConfigError("模型 ID 与展示名称不能为空或包含控制字符")
    row = state["providers"].get(provider)
    current = public_config(provider, state)
    supplied = payload.get("api_key")
    key = supplied.get_secret_value().strip() if supplied is not None else ""
    if not key:
        if not current["has_key"]:
            raise PlatformConfigError("请填写平台 API 密钥")
        if base != current["base_url"]:
            raise PlatformConfigError("修改 API 地址后必须重新输入密钥")
        if row:
            key = stored_key(row)
        else:
            from modstore_server.llm_key_resolver import _environment_api_key

            key = _environment_api_key(provider) or ""
    if len(key) > 4096 or any(ord(c) < 33 for c in key) or "…" in key or "****" in key:
        raise PlatformConfigError("平台 API 密钥格式不正确，请输入完整密钥")
    if key in base or key in model or key in display_name:
        raise PlatformConfigError("API 地址、模型 ID 和展示名称不能包含密钥")
    return {
        "provider": provider,
        "base_url": base,
        "model": model,
        "display_name": display_name,
    }, key


def save_config(provider: str, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
    if not fernet_configured():
        raise PlatformConfigError("服务端尚未配置有效的 MODSTORE_LLM_MASTER_KEY，配置未保存", 503)
    try:
        with _locked():
            state = _read_unlocked()
            old = state["providers"].get(provider)
            if "expected_revision" in payload and payload["expected_revision"] != (old or {}).get(
                "revision"
            ):
                raise PlatformConfigError("配置已被其他管理员修改，请刷新后重试", 409)
            row, key = prepare_config(provider, payload, state)
            row.update(
                api_key_encrypted=encrypt_secret(key),
                revision=uuid.uuid4().hex,
                updated_at=datetime.now(UTC).isoformat(),
                actor=actor,
            )
            state["providers"][provider] = row
            if payload.get("make_default", True):
                state["default_provider"] = provider
            path = config_path()
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with os.fdopen(
                    os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    json.dump(state, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return state
    except OSError:
        raise PlatformConfigError("平台模型配置保存失败，请检查持久化存储权限", 503) from None


def default_config() -> dict[str, Any] | None:
    state = read_state()
    provider = state.get("default_provider")
    row: dict[str, Any] | None = state["providers"].get(provider)
    if row:
        stored_key(row)  # Fail closed if a selected platform key cannot be decrypted.
    return row


def configured_model(
    provider: str, api_key: str | None, base_url: str | None
) -> dict[str, Any] | None:
    """Only enrich the platform catalog; a user's BYOK catalog stays independent."""
    if (
        isinstance(api_key, PlatformApiKey)
        and api_key.managed
        and api_key.configuration["provider"] == provider
    ):
        return dict(api_key.configuration)
    return None
