# mypy: disable-error-code="arg-type, no-any-return"
"""管理端可配置的 LiteLLM Router 运行参数（非密钥）。

优先级：显式环境变量 > 管理端持久化配置 > 代码默认值。
密钥池仍只允许通过环境变量注入，避免在管理端回显或落盘明文。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "state": None}
_CACHE_TTL_SECONDS = 5.0

DEFAULT_STATE: dict[str, Any] = {
    "enabled": True,
    "routing_strategy": "simple-shuffle",
    "num_retries": 2,
    "cooldown_seconds": 60.0,
    "allowed_fails": 2,
    "max_parallel": 0,
    "mid_stream_fallback": False,
    "request_timeout_seconds": 60.0,
    "stream_timeout_seconds": 180.0,
    "platform_fallbacks": [],
}

ROUTING_STRATEGIES = (
    "simple-shuffle",
    "least-busy",
    "usage-based-routing",
    "latency-based-routing",
    "cost-based-routing",
)


class RouterConfigError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def config_path() -> Path:
    explicit = (os.environ.get("MODSTORE_LLM_ROUTER_CONFIG_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = (
        os.environ.get("MODSTORE_RUNTIME_DIR")
        or os.environ.get("MODSTORE_DATA_DIR")
        or "/tmp/modstore_data"
    )
    return Path(root).expanduser().resolve() / "llm" / "llm-router-config.json"


def _read_unlocked() -> dict[str, Any]:
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "revision": "", **DEFAULT_STATE}
    except (OSError, ValueError):
        raise RouterConfigError("路由配置无法读取，请检查服务端持久化存储", 503) from None
    if not isinstance(raw, dict):
        raise RouterConfigError("路由配置损坏，请联系管理员恢复", 503)
    state = {"version": 1, "revision": str(raw.get("revision") or "")}
    for key, default in DEFAULT_STATE.items():
        value = raw.get(key, default)
        if isinstance(default, bool):
            state[key] = bool(value)
        elif isinstance(default, int):
            state[key] = int(value)
        elif isinstance(default, float):
            state[key] = float(value)
        elif isinstance(default, list):
            state[key] = list(value) if isinstance(value, list) else list(default)
        else:
            state[key] = str(value or default)
    if state["routing_strategy"] not in ROUTING_STRATEGIES:
        raise RouterConfigError("路由策略配置损坏，请联系管理员恢复", 503)
    return state


def read_state() -> dict[str, Any]:
    with _LOCK:
        return _read_unlocked()


def _write_unlocked(state: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _validated(payload: dict[str, Any]) -> dict[str, Any]:
    state = {"version": 1, **DEFAULT_STATE}
    for key, default in DEFAULT_STATE.items():
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise RouterConfigError(f"{key} 必须是布尔值")
            state[key] = value
        elif isinstance(default, int):
            if not isinstance(value, int) or isinstance(value, bool):
                raise RouterConfigError(f"{key} 必须是整数")
            state[key] = value
        elif isinstance(default, float):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise RouterConfigError(f"{key} 必须是数字")
            state[key] = float(value)
        elif isinstance(default, list):
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise RouterConfigError(f"{key} 必须是字符串列表")
            state[key] = [item.strip() for item in value if item.strip()]
        else:
            if not isinstance(value, str):
                raise RouterConfigError(f"{key} 必须是字符串")
            state[key] = value.strip()

    if state["routing_strategy"] not in ROUTING_STRATEGIES:
        raise RouterConfigError("不支持的 routing_strategy")
    if not 0 <= int(state["num_retries"]) <= 10:
        raise RouterConfigError("num_retries 必须在 0-10 之间")
    if not 0 <= int(state["allowed_fails"]) <= 20:
        raise RouterConfigError("allowed_fails 必须在 0-20 之间")
    if not 0 <= float(state["cooldown_seconds"]) <= 3600:
        raise RouterConfigError("cooldown_seconds 必须在 0-3600 之间")
    if not 0 <= int(state["max_parallel"]) <= 1000:
        raise RouterConfigError("max_parallel 必须在 0-1000 之间")
    if not 1 <= float(state["request_timeout_seconds"]) <= 600:
        raise RouterConfigError("request_timeout_seconds 必须在 1-600 之间")
    if not 1 <= float(state["stream_timeout_seconds"]) <= 1800:
        raise RouterConfigError("stream_timeout_seconds 必须在 1-1800 之间")
    for item in state["platform_fallbacks"]:
        if "/" not in item:
            raise RouterConfigError("platform_fallbacks 需使用 provider/model 格式")
    return state


def save_state(payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
    state = _validated(payload)
    state["revision"] = uuid.uuid4().hex
    state["updated_by"] = str(actor or "unknown")[:128]
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _LOCK:
        _write_unlocked(state)
    invalidate_cache()
    return state


def public_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    current = state or read_state_cached()
    return {key: current.get(key, default) for key, default in DEFAULT_STATE.items()} | {
        "revision": current.get("revision") or "",
        "updated_by": current.get("updated_by") or "",
        "updated_at": current.get("updated_at") or "",
        "routing_strategies": list(ROUTING_STRATEGIES),
    }


def read_state_cached() -> dict[str, Any]:
    now = time.monotonic()
    current_path = str(config_path())
    with _CACHE_LOCK:
        cached = _CACHE.get("state")
        if (
            cached is not None
            and _CACHE.get("path") == current_path
            and now - float(_CACHE.get("at") or 0.0) < _CACHE_TTL_SECONDS
        ):
            return dict(cached)
    state = read_state()
    with _CACHE_LOCK:
        _CACHE["state"] = state
        _CACHE["path"] = current_path
        _CACHE["at"] = now
    return dict(state)


def invalidate_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["state"] = None
        _CACHE["path"] = ""
        _CACHE["at"] = 0.0


def _env_raw(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _env_bool(name: str, fallback: bool) -> bool:
    raw = _env_raw(name).lower()
    if not raw:
        return fallback
    return raw not in {"0", "false", "no", "off"}


def _env_number(name: str, fallback: float, *, cast: type) -> Any:
    raw = _env_raw(name)
    if not raw:
        return fallback
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return fallback


def settings() -> dict[str, Any]:
    """返回生效配置：环境变量显式覆盖管理端设置。"""

    state = read_state_cached()
    env_fallbacks = _env_raw("MODSTORE_LLM_ROUTER_PLATFORM_FALLBACKS")
    return {
        "enabled": _env_bool("MODSTORE_LLM_ROUTER_ENABLED", bool(state["enabled"])),
        "routing_strategy": (
            _env_raw("MODSTORE_LLM_ROUTER_STRATEGY") or str(state["routing_strategy"])
        ),
        "num_retries": _env_number(
            "MODSTORE_LLM_ROUTER_NUM_RETRIES", int(state["num_retries"]), cast=int
        ),
        "cooldown_seconds": _env_number(
            "MODSTORE_LLM_ROUTER_COOLDOWN_SECONDS",
            float(state["cooldown_seconds"]),
            cast=float,
        ),
        "allowed_fails": _env_number(
            "MODSTORE_LLM_ROUTER_ALLOWED_FAILS", int(state["allowed_fails"]), cast=int
        ),
        "max_parallel": _env_number(
            "MODSTORE_LLM_ROUTER_MAX_PARALLEL", int(state["max_parallel"]), cast=int
        ),
        "mid_stream_fallback": _env_bool(
            "MODSTORE_LLM_ROUTER_MID_STREAM_FALLBACK", bool(state["mid_stream_fallback"])
        ),
        "request_timeout_seconds": _env_number(
            "MODSTORE_LLM_ROUTER_TIMEOUT_SECONDS",
            float(state["request_timeout_seconds"]),
            cast=float,
        ),
        "stream_timeout_seconds": _env_number(
            "MODSTORE_LLM_ROUTER_STREAM_TIMEOUT_SECONDS",
            float(state["stream_timeout_seconds"]),
            cast=float,
        ),
        "platform_fallbacks": (
            [item.strip() for item in env_fallbacks.split(",") if item.strip()]
            if env_fallbacks
            else list(state["platform_fallbacks"])
        ),
        "revision": str(state.get("revision") or ""),
    }


def reset_cache() -> None:
    invalidate_cache()


__all__ = [
    "DEFAULT_STATE",
    "ROUTING_STRATEGIES",
    "RouterConfigError",
    "config_path",
    "invalidate_cache",
    "public_state",
    "read_state",
    "read_state_cached",
    "reset_cache",
    "save_state",
    "settings",
]
