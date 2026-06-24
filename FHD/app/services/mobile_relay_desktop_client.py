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

from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.application.cursor_super_employee_service import CursorSuperEmployeeService
from app.infrastructure.topology import FHD_API_BASE_URL
from app.services.relay_gitops import GIT_OP_KINDS, handle_git_op
from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

_STATE_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
_CONFIG_FILE = Path(get_app_data_dir()) / "mobile_relay_desktop.json"

# 并发执行：poll 循环只负责"认领+派发"，每个任务在独立线程里跑，
# 避免单个长任务(开发任务可跑数分钟)堵死整条队列、导致新消息卡住。
_INFLIGHT: set[str] = set()
_INFLIGHT_LOCK = threading.Lock()


def _max_concurrent() -> int:
    try:
        return max(1, int(os.environ.get("XCAGI_RELAY_MAX_CONCURRENT") or "3"))
    except (TypeError, ValueError):
        return 3


def _relay_base_url() -> str:
    value = (
        os.environ.get("XCAGI_RELAY_BASE_URL")
        or os.environ.get("XCAGI_PUBLIC_FHD_BASE_URL")
        or FHD_API_BASE_URL
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
            "claude": True,
            "claude_cli": True,
            "cursor": True,
            "cursor_cli": True,
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


def _complete_relay_task(
    task: dict[str, Any],
    relay_id: str,
    desktop_token: str,
    base_url: str,
) -> None:
    """在独立线程里执行单个任务并回写结果；不阻塞 poll 循环。"""
    task_id = str(task.get("task_id") or "")
    try:
        result = _execute_task(task)
        relay_status = str(result.pop("_relay_status", "") or "").strip()
        if not relay_status:
            relay_status = "failed" if result.get("error") else "completed"
        timeout = float(os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
        with httpx.Client(timeout=timeout) as client:
            client.post(
                _api_url(f"/api/mobile/v1/relay/desktop/tasks/{task_id}/complete", base_url),
                json={
                    "relay_id": relay_id,
                    "desktop_token": desktop_token,
                    "status": relay_status,
                    "result": result,
                },
            ).raise_for_status()
    except Exception:  # noqa: BLE001
        logger.warning("mobile relay task %s failed", task_id, exc_info=True)
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.discard(task_id)


def _poll_once() -> None:
    config = _read_config()
    relay_id = str(config.get("relay_id") or "").strip()
    desktop_token = str(config.get("desktop_token") or "").strip()
    base_url = str(config.get("relay_base_url") or "").strip() or _relay_base_url()
    if not relay_id or not desktop_token:
        return
    # 只认领空闲槽位数量的任务：claim 后必须有线程去跑，否则会把任务卡在 running。
    with _INFLIGHT_LOCK:
        free = _max_concurrent() - len(_INFLIGHT)
    if free <= 0:
        return
    timeout = float(os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            _api_url("/api/mobile/v1/relay/desktop/poll", base_url),
            json={"relay_id": relay_id, "desktop_token": desktop_token, "max_tasks": free},
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
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "")
        if not task_id:
            continue
        with _INFLIGHT_LOCK:
            if task_id in _INFLIGHT:
                continue
            _INFLIGHT.add(task_id)
        threading.Thread(
            target=_complete_relay_task,
            args=(task, relay_id, desktop_token, base_url),
            name=f"relay-task-{task_id[:8]}",
            daemon=True,
        ).start()


def _execute_task(task: dict[str, Any]) -> dict[str, Any]:
    kind = str(task.get("kind") or "codex.invoke").strip()
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    # git 操作（合并/diff/丢弃）：手机底部功能键触发，不需要 message，只需 payload.branch。
    if kind in GIT_OP_KINDS:
        return handle_git_op(kind, payload)
    message = str(
        payload.get("message")
        or payload.get("body")
        or payload.get("prompt")
        or payload.get("task")
        or ""
    ).strip()
    if not message:
        return {"error": "任务缺少 message"}
    # 中继泛化：按 kind 前缀选择超级员工(codex.* / claude.* / cursor.*)，本地执行后回写。
    if kind.startswith("claude"):
        service: Any = ClaudeSuperEmployeeService()
        tool_label = "Claude"
    elif kind.startswith("cursor"):
        service = CursorSuperEmployeeService()
        tool_label = "Cursor"
    elif kind.startswith("codex"):
        service = CodexSuperEmployeeService()
        tool_label = "Codex"
    else:
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
    # 派工模式 = 三态控件（自动 / 直答 / 多设备）。
    # 新客户端在用户「显式」选「多设备」时带 mode_explicit=True，此处保留其 mode →
    # 直接走 Para 多设备派工，不再被关键词分类器二次判断。
    # 旧客户端的聊天面固定下发 mode="code"（无 mode_explicit），会把每条闲聊都强制
    # 派到 Para（"你好"/"在干嘛" 也被当开发任务，回不到结果），故仍清掉这种「非显式」
    # 的强制派工 mode，交回内容分类器 _should_reply_with_cli：闲聊 → 本地 CLI 直答；
    # 含"修复/测试/部署"等开发关键词 → Para 派工。
    # 「直答」走 mode="chat"，不在下列强制集合内、原样透传 → CLI 直答。
    mode_explicit_raw = context.get("mode_explicit")
    mode_explicit = mode_explicit_raw is True or str(mode_explicit_raw or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not mode_explicit and str(context.get("mode") or "").strip().lower() in {
        "code",
        "task",
        "dispatch",
        "dev",
        "develop",
    }:
        context.pop("mode", None)
    try:
        result = service.invoke(
            user_id=user_id,
            message=message,
            context=context,
        )
        dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else {}
        dispatch_status = str(dispatch.get("status") or "").strip().lower()
        if dispatch_status == "completed":
            return {"ok": True, "codex": result, "_relay_status": "completed"}
        if dispatch.get("accepted") is not True:
            reason = str(dispatch.get("reason") or f"{tool_label}/MCP 调度器当前不可用").strip()
            return {
                "error": reason,
                "codex": result,
                "_relay_status": "blocked",
            }

        request_id = str(dispatch.get("request_id") or "").strip()
        task_id = str(dispatch.get("task_id") or "").strip()
        timeout = max(0.0, float(os.environ.get("XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC") or "300"))
        interval = max(0.05, float(os.environ.get("XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC") or "2"))
        deadline = time.monotonic() + timeout
        while True:
            terminal = _terminal_codex_message(
                service.list_messages(user_id=user_id, limit=200),
                request_id=request_id,
                task_id=task_id,
            )
            if terminal:
                result["assistant_message"] = terminal
                return {"ok": True, "codex": result, "_relay_status": "completed"}
            if time.monotonic() >= deadline:
                break
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        suffix = f"（task_id={task_id}）" if task_id else ""
        return {
            "error": f"{tool_label} 已派发，但在 {timeout:g} 秒内未回写{suffix}",
            "codex": result,
            "_relay_status": "blocked",
        }
    except Exception as exc:
        logger.exception("mobile relay Codex task failed")
        return {"error": str(exc)[:1000]}


def _terminal_codex_message(
    messages: list[dict[str, Any]],
    *,
    request_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    for row in reversed(messages):
        if str(row.get("role") or "").strip().lower() != "assistant":
            continue
        kind = str(row.get("kind") or "").strip().lower()
        # 兼容 codex_result/codex_direct 与 claude_result/claude_direct。
        if not (kind.endswith("_result") or kind.endswith("_direct")):
            continue
        row_request = str(row.get("dispatch_request_id") or row.get("request_id") or "").strip()
        row_task = str(row.get("task_id") or "").strip()
        if request_id and row_request != request_id:
            continue
        if task_id and row_task != task_id:
            continue
        if str(row.get("body") or "").strip():
            return row
    return None
