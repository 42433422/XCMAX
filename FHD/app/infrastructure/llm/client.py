"""LLM mode configuration and clients: authenticated tool scope takes precedence
over the process-wide client configured through provider credentials.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_mode_lock = threading.Lock()
_client_lock = threading.Lock()

_mode: Literal["online", "offline"]
_offline_model: str | None = None
_openai_client: Any | None = None
_scoped_client: ContextVar[tuple[Any, str | None] | None] = ContextVar(
    "scoped_llm_client", default=None
)


@contextmanager
def llm_client_scope(client: Any, model: str) -> Iterator[None]:
    """Reuse the authenticated planner client for nested tools without persisting credentials."""
    token = _scoped_client.set((client, model))
    try:
        yield
    finally:
        _scoped_client.reset(token)


@contextmanager
def llm_client_factory_scope(factory: Any) -> Iterator[None]:
    """Defer client creation without making a model call at scope entry."""
    token = _scoped_client.set((factory, None))
    try:
        yield
    finally:
        _scoped_client.reset(token)


def _resolved_scoped_client() -> tuple[Any, str] | None:
    scoped = _scoped_client.get()
    if scoped is not None and scoped[1] is None:
        client = scoped[0]()
        if isinstance(client, tuple):
            client, model = client
            _scoped_client.set((client, model))
            return client, model
        from app.infrastructure.llm.providers.credentials import resolve_default_chat_model

        model = resolve_default_chat_model()
        if getattr(client, "is_modstore_openai_compatible", False):
            provider = str(client.default_provider or "").strip()
            model = f"{provider}/{client.default_model}" if provider else str(client.default_model)
        scoped = (client, model)
        _scoped_client.set(scoped)
    return cast("tuple[Any, str] | None", scoped)


def capture_worker_llm_scope(context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Copy minimal credentials into spawn arguments, never durable task context."""
    scoped = _scoped_client.get()
    if scoped is None:
        owner = (context or {}).get("local_user_id") or (context or {}).get("actor_id")
        if owner:
            return (
                {"kind": "account", "owner": int(owner)}
                if str(owner).isdigit() and int(owner) > 0
                else {"kind": "unavailable"}
            )
        return None
    try:
        scoped = _resolved_scoped_client()
        if scoped is None:
            return {"kind": "unavailable"}
        client, model = scoped
        if getattr(client, "is_modstore_openai_compatible", False) is True:
            adapter = client.adapter
            config = {
                "kind": "modstore",
                "platform_url": adapter.platform_url,
                "auth_token": adapter.auth_token,
                "user_id": adapter.user_id,
                "default_provider": adapter.default_provider,
                "default_model": adapter.default_model,
                "timeout": adapter.timeout,
            }
        else:
            if not isinstance(client.api_key, str) or not client.api_key:
                raise ValueError("unsupported scoped client")
            config = {"kind": "openai", "api_key": client.api_key, "base_url": str(client.base_url)}
        config["model"] = model
        json.dumps(config)
        return config
    except RECOVERABLE_ERRORS + (AttributeError, TypeError):
        return {"kind": "unavailable"}


def restore_worker_llm_client(config: dict[str, Any]) -> tuple[Any, str]:
    client: Any
    if config["kind"] in {"modstore", "account"}:
        from app.domain.conversation.legacy_services.modstore_adapter import (
            ModstoreOpenAICompatibleClient,
            ModstorePlatformAdapter,
        )

        if config["kind"] == "account":
            from app.fastapi_routes.market_account import latest_session_market_token

            token = latest_session_market_token(user_id=config["owner"])
            if not token:
                raise RuntimeError("任务所属账号没有可用的模型登录凭据，请重新登录")
            adapter = ModstorePlatformAdapter.from_session(auth_token=token)
            adapter.user_id = None
            return ModstoreOpenAICompatibleClient(
                adapter
            ), f"{adapter.default_provider}/{adapter.default_model}"
        adapter = ModstorePlatformAdapter(
            **{k: v for k, v in config.items() if k not in {"kind", "model"}}
        )
        for field in ("auth_token", "user_id", "default_provider", "default_model"):
            setattr(adapter, field, config[field])
        client = ModstoreOpenAICompatibleClient(adapter)
    elif config["kind"] == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
    else:
        raise RuntimeError("当前请求的模型不可用，不能回退到其他账号")
    return client, str(config["model"])


def _env_mode() -> Literal["online", "offline"] | None:
    if "FHD_LLM_MODE" in os.environ:
        raw = os.environ.get("FHD_LLM_MODE", "").strip().lower()
    else:
        raw = os.environ.get("LLM_MODE", "").strip().lower()
    if raw in ("offline", "local", "ollama"):
        return "offline"
    if raw in ("online", "cloud", "api"):
        return "online"
    return None


def _initial_mode() -> Literal["online", "offline"]:
    m = _env_mode()
    if m is not None:
        return m
    return "online"


_mode = _initial_mode()


def _resolve_openai_timeout_seconds() -> float:
    raw = (os.environ.get("XCAGI_OPENAI_TIMEOUT_SEC") or "45").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 45.0
    return max(5.0, min(value, 300.0))


def _resolve_openai_max_retries() -> int:
    raw = (os.environ.get("XCAGI_OPENAI_MAX_RETRIES") or "0").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 0
    return max(0, min(value, 5))


def resolve_mode() -> Literal["online", "offline"]:
    with _mode_lock:
        return _mode


def set_mode(mode: str, model: str | None = None) -> None:
    """切换 ``online`` / ``offline``；offline 时可传入 Ollama 模型名。"""
    global _mode, _offline_model
    if mode not in ("online", "offline"):
        raise ValueError("mode must be 'online' or 'offline'")
    with _mode_lock:
        _mode = cast('Literal["online", "offline"]', mode)
        if mode == "offline":
            if model is not None:
                s = str(model).strip()
                _offline_model = s or None
        else:
            _offline_model = None
    dispose_llm_client()


def _first_api_key() -> tuple[str, str | None]:
    """返回 (api_key, base_url 可选)。

    优先 OPENAI/XCauto；否则 DeepSeek（常用兼容基座）。
    """
    from app.infrastructure.llm.providers.credentials import resolve_openai_env_credentials

    return resolve_openai_env_credentials()


def require_api_key() -> None:
    if _scoped_client.get() is not None or resolve_mode() == "offline":
        return
    key, _ = _first_api_key()
    if not key:
        raise RuntimeError(
            "未配置 OPENAI_API_KEY（或 DEEPSEEK_API_KEY）；online 模式下无法调用云端大模型。"
        )


def get_llm_client() -> Any | None:
    """online：返回 ``openai.OpenAI`` 单例（需已配置密钥）。

    offline：返回 ``None``（由本地 Ollama 等路径处理，不强制云端客户端）。
    """
    if scoped := _resolved_scoped_client():
        return scoped[0]
    if resolve_mode() == "offline":
        return None
    require_api_key()
    global _openai_client
    with _client_lock:
        if _openai_client is not None:
            return _openai_client
        from openai import OpenAI

        api_key, base_url = _first_api_key()
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": _resolve_openai_timeout_seconds(),
            "max_retries": _resolve_openai_max_retries(),
        }
        if base_url:
            kwargs["base_url"] = base_url
        _openai_client = OpenAI(**kwargs)
        return _openai_client


def dispose_llm_client() -> None:
    """Close and clear the process-wide OpenAI-compatible client."""
    global _openai_client
    with _client_lock:
        client = _openai_client
        _openai_client = None
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except (OSError, RuntimeError, TypeError, ValueError):
            logger.debug("LLM client close failed", exc_info=True)


def get_offline_status() -> dict[str, Any]:
    """供 ``GET /api/mode`` 展示本机 Ollama 是否可达。"""
    host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    url = f"{host}/api/tags"
    with _mode_lock:
        preferred = _offline_model
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        models_raw = body.get("models") or []
        names: list[str] = []
        for m in models_raw:
            if isinstance(m, dict) and m.get("name"):
                names.append(str(m["name"]))
            elif isinstance(m, str):
                names.append(m)
        return {
            "ollama_host": host,
            "ollama_reachable": True,
            "models": names,
            "preferred_offline_model": preferred,
        }
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.debug("ollama probe failed: %s", e)
        return {
            "ollama_host": host,
            "ollama_reachable": False,
            "models": [],
            "preferred_offline_model": preferred,
            "error": str(e),
        }


def get_openai_compatible_client() -> Any:
    if scoped := _resolved_scoped_client():
        return scoped[0]
    cli = get_llm_client()
    if cli is None:
        raise RuntimeError("offline mode has no OpenAI-compatible client")
    return cli


def resolve_chat_model() -> str:
    if scoped := _resolved_scoped_client():
        return scoped[1]
    from app.infrastructure.llm.providers.credentials import resolve_default_chat_model

    return resolve_default_chat_model()


__all__ = [
    "resolve_mode",
    "llm_client_scope",
    "llm_client_factory_scope",
    "set_mode",
    "require_api_key",
    "get_llm_client",
    "dispose_llm_client",
    "get_offline_status",
    "get_openai_compatible_client",
    "resolve_chat_model",
]
