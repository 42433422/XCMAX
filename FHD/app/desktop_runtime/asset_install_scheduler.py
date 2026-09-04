"""Consume durable paid-asset install commands on an authenticated desktop."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
INSTALL_ERRORS = (HTTPException, ValueError, *RECOVERABLE_ERRORS)

_INITIAL_DELAY_SECONDS = 8
_DEFAULT_INTERVAL_SECONDS = 30
_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _enabled() -> bool:
    raw = (os.environ.get("XCAGI_ASSET_INSTALL_AUTO_PULL") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _interval_seconds() -> int:
    try:
        return max(
            10,
            int(os.environ.get("XCAGI_ASSET_INSTALL_POLL_SECONDS") or _DEFAULT_INTERVAL_SECONDS),
        )
    except ValueError:
        return _DEFAULT_INTERVAL_SECONDS


def _bearer(token: str) -> str:
    value = str(token or "").strip()
    return value if value.lower().startswith("bearer ") else f"Bearer {value}"


async def poll_asset_install_commands_once() -> dict[str, Any]:
    from app.application.desktop_delivery_receipt import desktop_installation_id
    from app.desktop_runtime.paths import is_desktop_mode
    from app.fastapi_routes.market_account import _proxy_json, latest_session_market_token

    if not is_desktop_mode():
        return {"processed": 0, "reason": "not_desktop"}
    token = str(latest_session_market_token() or "").strip()
    if not token:
        return {"processed": 0, "reason": "market_login_required"}
    installation_id = desktop_installation_id()
    encoded_installation_id = quote(installation_id, safe="")
    payload = await _proxy_json(
        "GET",
        f"/api/asset-installations/commands?installation_id={encoded_installation_id}&pending_only=true&limit=10",
        authorization=token,
        return_error_payload=True,
        timeout=12.0,
        retries=2,
    )
    if not isinstance(payload, dict) or payload.get("__proxy_error__"):
        return {"processed": 0, "reason": "market_unavailable"}
    rows = payload.get("items") if isinstance(payload.get("items"), list) else []
    outcomes: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        command_id = int(raw.get("id") or 0)
        if command_id <= 0:
            continue
        claimed = await _proxy_json(
            "POST",
            f"/api/asset-installations/commands/{command_id}/claim",
            json_body={"installation_id": installation_id},
            authorization=token,
            return_error_payload=True,
            timeout=12.0,
            retries=2,
        )
        if not isinstance(claimed, dict) or claimed.get("__proxy_error__"):
            continue
        command = claimed.get("command") if isinstance(claimed.get("command"), dict) else {}
        asset = command.get("asset") if isinstance(command.get("asset"), dict) else {}
        pkg_id = str(asset.get("pkg_id") or "").strip()
        version = str(asset.get("version") or "").strip()
        result_body: dict[str, Any]
        try:
            if not pkg_id:
                raise ValueError("安装命令缺少 pkg_id")
            from app.fastapi_routes.mod_store_routes import _install_from_catalog

            result = await _install_from_catalog(
                pkg_id,
                version,
                activate=True,
                authorization=_bearer(token),
                download_path=str(asset.get("download_path") or ""),
                expected_sha256=str(asset.get("sha256") or ""),
            )
            data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            ok = bool(data.get("success"))
            result_body = {
                "installation_id": installation_id,
                "status": "installed" if ok else "failed",
                "installed_mod_id": pkg_id if ok else "",
                "installed_version": version if ok else "",
                "error": "" if ok else str(data.get("message") or "安装失败"),
                "result": data,
            }
        except INSTALL_ERRORS as exc:
            logger.warning("asset install command %s failed: %s", command_id, exc)
            result_body = {
                "installation_id": installation_id,
                "status": "failed",
                "installed_mod_id": "",
                "installed_version": "",
                "error": str(exc),
                "result": {},
            }
        completed = await _proxy_json(
            "POST",
            f"/api/asset-installations/commands/{command_id}/result",
            json_body=result_body,
            authorization=token,
            return_error_payload=True,
            timeout=12.0,
            retries=2,
        )
        outcomes.append(
            {
                "command_id": command_id,
                "status": result_body["status"],
                "reported": isinstance(completed, dict) and not completed.get("__proxy_error__"),
            }
        )
    return {"processed": len(outcomes), "installation_id": installation_id, "outcomes": outcomes}


async def _run(stop_event: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=_INITIAL_DELAY_SECONDS)
        return
    except TimeoutError:
        pass
    while not stop_event.is_set():
        try:
            result = await poll_asset_install_commands_once()
            if int(result.get("processed") or 0):
                logger.info("asset install commands consumed: %s", result)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("asset install command poll failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_interval_seconds())
        except TimeoutError:
            continue


def start_asset_install_scheduler() -> None:
    global _task, _stop_event
    if not _enabled() or "PYTEST_CURRENT_TEST" in os.environ:
        return
    from app.desktop_runtime.paths import is_desktop_mode

    if not is_desktop_mode():
        return
    if _task is not None and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_run(_stop_event), name="xcagi-asset-install")


async def stop_asset_install_scheduler() -> None:
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except TimeoutError:
            _task.cancel()
    _task = None
    _stop_event = None


__all__ = [
    "poll_asset_install_commands_once",
    "start_asset_install_scheduler",
    "stop_asset_install_scheduler",
]
