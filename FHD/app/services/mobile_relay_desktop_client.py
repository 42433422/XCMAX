"""Desktop-side cloud relay client.

The desktop runtime registers itself with the cloud relay, persists the private
desktop token locally, and polls the cloud for tasks submitted by the mobile app.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

_STATE_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
_CONFIG_FILE = Path(get_app_data_dir()) / "mobile_relay_desktop.json"


def _relay_base_url() -> str:
    value = (
        os.environ.get("XCAGI_RELAY_BASE_URL")
        or os.environ.get("XCAGI_PUBLIC_FHD_BASE_URL")
        or "https://xiu-ci.com/fhd-api"
    ).strip()
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/") + "/"


def _api_url(path: str, base_url: str | None = None) -> str:
    base = (base_url or _relay_base_url()).rstrip("/") + "/"
    return f"{base}{path.lstrip('/')}"


def _read_config() -> dict[str, Any]:
    try:
        if not _CONFIG_FILE.is_file():
            return {}
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.warning("mobile relay desktop config is unreadable: %s", _CONFIG_FILE, exc_info=True)
        return {}


def _public_payload_from_config(config: dict[str, Any]) -> dict[str, Any] | None:
    relay_id = str(config.get("relay_id") or "").strip()
    pairing_code = str(config.get("pairing_code") or "").strip()
    if not relay_id or not pairing_code:
        return None
    base_url = str(config.get("relay_base_url") or "").strip() or _relay_base_url()
    exp = int(config.get("exp") or 0)
    if exp <= 0:
        registered_at = int(config.get("registered_at") or 0)
        if registered_at > 0:
            exp = registered_at + int(os.environ.get("XCAGI_RELAY_PAIRING_TTL_SEC") or "86400")
    if exp > 0 and exp <= int(time.time()):
        return None
    expires_at = str(config.get("expires_at") or "").strip()
    return {
        "relay_id": relay_id,
        "pairing_code": pairing_code,
        **({"expires_at": expires_at} if expires_at else {}),
        **({"exp": exp} if exp > 0 else {}),
        "relay_base_url": base_url,
        "qr_json": {
            "v": 3,
            "kind": "xcagi_relay_pairing",
            "relay_id": relay_id,
            "code": pairing_code,
            "t": pairing_code,
            "relay_base_url": base_url,
        },
    }


def cached_desktop_relay_payload() -> dict[str, Any] | None:
    """Return the public part of the persisted relay binding, if available."""
    return _public_payload_from_config(_read_config())


def _write_config(data: dict[str, Any]) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def register_desktop_relay(*, host: str, port: int, label: str = "") -> dict[str, Any] | None:
    """Register this desktop with the public relay and start the poller."""
    base_url = _relay_base_url()
    device_label = label.strip() or f"XCAGI 桌面执行端 - {socket.gethostname()}"
    body = {
        "label": device_label,
        "device_id": f"{socket.gethostname()}:{port}",
        "relay_base_url": base_url,
        "capabilities": {
            "codex": True,
            "codex_cli": True,
            "desktop": True,
            "host": host,
            "port": int(port),
            "platform": platform.platform(),
        },
    }
    timeout = float(os.environ.get("XCAGI_RELAY_REGISTER_TIMEOUT_SEC") or "5")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                _api_url("/api/mobile/v1/relay/desktop/register", base_url), json=body
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("mobile relay desktop register failed: %s", exc)
        cached = cached_desktop_relay_payload()
        if cached:
            start_desktop_relay_poller()
            return cached
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("desktop_token") or not data.get("relay_id"):
        logger.warning("mobile relay desktop register returned invalid payload")
        return None
    config = {
        "relay_id": str(data.get("relay_id") or ""),
        "desktop_token": str(data.get("desktop_token") or ""),
        "relay_base_url": str(data.get("relay_base_url") or base_url),
        "pairing_code": str(data.get("pairing_code") or ""),
        "expires_at": str(data.get("expires_at") or ""),
        "exp": int(data.get("exp") or 0),
        "registered_at": int(time.time()),
        "label": device_label,
    }
    _write_config(config)
    start_desktop_relay_poller()
    return data


def start_desktop_relay_poller() -> bool:
    """Start the daemon poller if a relay config exists."""
    config = _read_config()
    if not config.get("relay_id") or not config.get("desktop_token"):
        return False
    global _WORKER_THREAD
    with _STATE_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return True
        _STOP_EVENT.clear()
        _WORKER_THREAD = threading.Thread(
            target=_poll_loop,
            name="xcagi-mobile-relay-desktop",
            daemon=True,
        )
        _WORKER_THREAD.start()
        return True


def stop_desktop_relay_poller() -> None:
    _STOP_EVENT.set()


def _poll_loop() -> None:
    interval = float(os.environ.get("XCAGI_RELAY_POLL_INTERVAL_SEC") or "4")
    while not _STOP_EVENT.is_set():
        try:
            _poll_once()
        except Exception:  # noqa: BLE001
            logger.warning("mobile relay poll failed", exc_info=True)
        _STOP_EVENT.wait(max(1.0, interval))


def _poll_once() -> None:
    config = _read_config()
    relay_id = str(config.get("relay_id") or "").strip()
    desktop_token = str(config.get("desktop_token") or "").strip()
    base_url = str(config.get("relay_base_url") or "").strip() or _relay_base_url()
    if not relay_id or not desktop_token:
        return
    timeout = float(os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            _api_url("/api/mobile/v1/relay/desktop/poll", base_url),
            json={"relay_id": relay_id, "desktop_token": desktop_token, "max_tasks": 5},
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else {}
        tasks = data.get("tasks") if isinstance(data, dict) else []
        if not isinstance(tasks, list):
            return
        for task in tasks:
            if isinstance(task, dict):
                result = _execute_task(task)
                client.post(
                    _api_url(
                        f"/api/mobile/v1/relay/desktop/tasks/{task.get('task_id')}/complete",
                        base_url,
                    ),
                    json={
                        "relay_id": relay_id,
                        "desktop_token": desktop_token,
                        "status": "failed" if result.get("error") else "done",
                        "result": result,
                    },
                ).raise_for_status()


def _execute_task(task: dict[str, Any]) -> dict[str, Any]:
    kind = str(task.get("kind") or "codex.invoke").strip()
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    message = str(
        payload.get("message")
        or payload.get("body")
        or payload.get("prompt")
        or payload.get("task")
        or ""
    ).strip()
    if not message:
        return {"error": "任务缺少 message"}
    if not kind.startswith("codex"):
        return {"error": f"暂不支持的任务类型：{kind}"}
    user_id = int(task.get("created_by_user_id") or payload.get("user_id") or 1)
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    context = {
        **context,
        "source": "mobile_relay",
        "relay_task_id": str(task.get("task_id") or ""),
        "client_surface": "mobile",
        "target_devices": ["all"],
    }
    try:
        result = CodexSuperEmployeeService().invoke(
            user_id=user_id,
            message=message,
            context=context,
        )
        return {"ok": True, "codex": result}
    except Exception as exc:
        logger.exception("mobile relay Codex task failed")
        return {"error": str(exc)[:1000]}
