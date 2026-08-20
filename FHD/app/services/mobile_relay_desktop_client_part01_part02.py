# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.mobile_relay_desktop_client")


def _poll_loop() -> None:
    interval = float(_facade().os.environ.get("XCAGI_RELAY_POLL_INTERVAL_SEC") or "4")
    max_backoff = float(_facade().os.environ.get("XCAGI_RELAY_POLL_MAX_BACKOFF_SEC") or "300")
    failure_count = 0
    while not _facade()._STOP_EVENT.is_set():
        wait_seconds = max(1.0, interval)
        try:
            _facade()._poll_once()
            if failure_count:
                _facade().logger.info(
                    "mobile relay poll recovered after %d failure(s)", failure_count
                )
            failure_count = 0
        except (_facade().httpx.HTTPError, _facade().httpx.InvalidURL, ValueError) as exc:
            failure_count += 1
            wait_seconds = _facade()._relay_poll_backoff_seconds(
                failure_count, base_interval=interval, max_interval=max_backoff
            )
            if failure_count == 1 or failure_count & failure_count - 1 == 0:
                _facade().logger.warning(
                    "mobile relay unavailable; retry in %.0fs (failure %d): %s",
                    wait_seconds,
                    failure_count,
                    exc,
                )
            else:
                _facade().logger.debug("mobile relay remains unavailable: %s", exc)
        except _facade().RECOVERABLE_ERRORS as exc:
            failure_count += 1
            wait_seconds = _facade()._relay_poll_backoff_seconds(
                failure_count, base_interval=interval, max_interval=max_backoff
            )
            _facade().logger.warning(
                "mobile relay poll failed; retry in %.0fs: %s", wait_seconds, exc
            )
        _facade()._STOP_EVENT.wait(wait_seconds)


def _complete_relay_task(
    task: dict[str, _facade().Any], relay_id: str, desktop_token: str, base_url: str
) -> None:
    """在独立线程里执行单个任务并回写结果；不阻塞 poll 循环。"""
    task_id = str(task.get("task_id") or "")
    started = _facade().time.monotonic()
    try:
        result = _facade()._execute_task(task)
        relay_status = str(result.pop("_relay_status", "") or "").strip()
        if not relay_status:
            relay_status = "failed" if result.get("error") else "completed"
        result["elapsed_seconds"] = round(max(0.0, _facade().time.monotonic() - started), 1)
        if (
            relay_status in _facade()._FAILED_STATUSES
            or relay_status in _facade()._BLOCKED_STATUSES
        ):
            result.setdefault("error_code", relay_status)
            result.setdefault("error_message", str(result.get("error") or "").strip())
        timeout = float(_facade().os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
        with _facade()._relay_http_client(timeout) as client:
            client.post(
                _facade()._api_url(
                    f"/api/mobile/v1/relay/desktop/tasks/{task_id}/complete", base_url
                ),
                json={
                    "relay_id": relay_id,
                    "desktop_token": desktop_token,
                    "status": relay_status,
                    "result": result,
                },
            ).raise_for_status()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("mobile relay task %s failed", task_id, exc_info=True)
    finally:
        with _facade()._INFLIGHT_LOCK:
            _facade()._INFLIGHT.discard(task_id)


def _poll_once() -> None:
    config = _facade()._read_config()
    relay_id = str(config.get("relay_id") or "").strip()
    desktop_token = str(config.get("desktop_token") or "").strip()
    base_url = str(config.get("relay_base_url") or "").strip() or _facade()._relay_base_url()
    if not relay_id or not desktop_token:
        return
    with _facade()._INFLIGHT_LOCK:
        free = _facade()._max_concurrent() - len(_facade()._INFLIGHT)
    if free <= 0:
        return
    timeout = float(_facade().os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
    with _facade()._relay_http_client(timeout) as client:
        resp = client.post(
            _facade()._api_url("/api/mobile/v1/relay/desktop/poll", base_url),
            json={"relay_id": relay_id, "desktop_token": desktop_token, "max_tasks": free},
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else {}
        tasks = data.get("tasks") if isinstance(data, dict) else []
    config_changed = False
    now_epoch = int(_facade().time.time())
    if config.get("last_relay_sync_at") != now_epoch:
        config["last_relay_sync_at"] = now_epoch
        config_changed = True
    desktop = data.get("desktop") if isinstance(data, dict) else None
    if isinstance(desktop, dict):
        is_paired = (
            str(desktop.get("status") or "") == "paired"
            or int(desktop.get("mobile_user_id") or 0) > 0
        )
        if is_paired and (not config.get("paired")):
            config["paired"] = True
            config_changed = True
        mobile_username = str(desktop.get("mobile_username") or "").strip()
        if mobile_username and config.get("mobile_username") != mobile_username:
            config["mobile_username"] = mobile_username
            config_changed = True
    if config_changed:
        _facade()._write_config(config)
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "")
        if not task_id:
            continue
        with _facade()._INFLIGHT_LOCK:
            if task_id in _facade()._INFLIGHT:
                continue
            _facade()._INFLIGHT.add(task_id)
        _facade().threading.Thread(
            target=_facade()._complete_relay_task,
            args=(task, relay_id, desktop_token, base_url),
            name=f"relay-task-{task_id[:8]}",
            daemon=True,
        ).start()


def _extract_tool_calls(
    assistant: dict[str, _facade().Any], tool_label: str
) -> list[dict[str, _facade().Any]]:
    """从 assistant_message body 里提取 dev-loop 关键步骤，供手机端时间线展示。

    dev-loop 结束文本含 "闭环结果" 段落（分支/验证/推送），据此解析。
    非开发任务（闲聊直答）返回空列表。
    """
    body = str(assistant.get("body") or assistant.get("content") or "").strip()
    if not body or "闭环结果" not in body:
        return []
    import re

    calls: list[dict[str, _facade().Any]] = []
    m = re.search("分支[：:]\\s*(\\S+)", body)
    if m:
        calls.append(
            {
                "action": "create_branch",
                "icon": "branch",
                "label": f"创建分支 {m.group(1)}",
                "detail": m.group(1),
            }
        )
    m = re.search("验证[：:]\\s*(通过|未通过)[（(]([^)）]*)", body)
    if m:
        ok = m.group(1) == "通过"
        calls.append(
            {
                "action": "verify",
                "icon": "check",
                "label": f"验证{('通过' if ok else '未通过')}",
                "detail": m.group(2)[:200],
                "success": ok,
            }
        )
    m = re.search("推送[：:]\\s*(.+?)(?:\\n|$)", body)
    if m:
        push_text = m.group(1).strip()[:200]
        calls.append(
            {
                "action": "push",
                "icon": "upload",
                "label": "推送分支",
                "detail": push_text,
                "success": "成功" in push_text or "已推送" in push_text,
            }
        )
    calls.insert(
        0,
        {
            "action": "cli_run",
            "icon": "terminal",
            "label": f"{tool_label} CLI 执行",
            "detail": "调用无头 agent 修改代码",
        },
    )
    return calls
