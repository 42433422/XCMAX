# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.mobile_relay_desktop_client")


def _relay_http_client(timeout: float) -> _facade().httpx.Client:
    """云中继须直连公网 API；桌面系统代理未运行时 trust_env 会导致 Invalid port 等异常。"""
    return _facade().httpx.Client(timeout=timeout, trust_env=False)


def _migrate_legacy_config_once() -> None:
    """旧版把配对凭证写到 get_app_data_dir()（可能回落仓库根）。

    若稳定路径尚无配置、而旧路径存在，则一次性迁移过来，避免源码升级后丢失既有配对。
    稳定路径已有配置时**绝不覆盖**（它才是当前权威绑定）。
    """
    global _LEGACY_MIGRATION_DONE
    if _facade()._LEGACY_MIGRATION_DONE:
        return
    _facade()._LEGACY_MIGRATION_DONE = True
    try:
        if _facade()._CONFIG_FILE.is_file() or not _facade()._LEGACY_CONFIG_FILE.is_file():
            return
        if _facade()._CONFIG_FILE.resolve() == _facade()._LEGACY_CONFIG_FILE.resolve():
            return
        _facade()._CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _facade()._CONFIG_FILE.write_text(
            _facade()._LEGACY_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        _facade().logger.info(
            "迁移历史云中继配对凭证 %s -> %s", _facade()._LEGACY_CONFIG_FILE, _facade()._CONFIG_FILE
        )
    except OSError:
        _facade().logger.warning("云中继配对凭证迁移失败", exc_info=True)


def _ensure_super_employee_service_classes() -> None:
    global ClaudeSuperEmployeeService, CodexSuperEmployeeService, CursorSuperEmployeeService
    global TraeSuperEmployeeService
    if (
        _facade().ClaudeSuperEmployeeService is not None
        and _facade().CodexSuperEmployeeService is not None
        and (_facade().CursorSuperEmployeeService is not None)
        and (_facade().TraeSuperEmployeeService is not None)
    ):
        return
    if _facade().ClaudeSuperEmployeeService is None:
        from app.application.claude_super_employee_service import (
            ClaudeSuperEmployeeService as _ClaudeSuperEmployeeService,
        )

        _facade().ClaudeSuperEmployeeService = _ClaudeSuperEmployeeService
    if _facade().CodexSuperEmployeeService is None:
        from app.application.codex_super_employee_service import (
            CodexSuperEmployeeService as _CodexSuperEmployeeService,
        )

        _facade().CodexSuperEmployeeService = _CodexSuperEmployeeService
    if _facade().CursorSuperEmployeeService is None:
        from app.application.cursor_super_employee_service import (
            CursorSuperEmployeeService as _CursorSuperEmployeeService,
        )

        _facade().CursorSuperEmployeeService = _CursorSuperEmployeeService
    if _facade().TraeSuperEmployeeService is None:
        from app.application.trae_super_employee_service import (
            TraeSuperEmployeeService as _TraeSuperEmployeeService,
        )

        _facade().TraeSuperEmployeeService = _TraeSuperEmployeeService


def _max_concurrent() -> int:
    try:
        return max(1, int(_facade().os.environ.get("XCAGI_RELAY_MAX_CONCURRENT") or "3"))
    except (TypeError, ValueError):
        return 3


def _relay_base_url() -> str:
    value = (
        _facade().os.environ.get("XCAGI_RELAY_BASE_URL")
        or _facade().os.environ.get("XCAGI_PUBLIC_FHD_BASE_URL")
        or "https://xiu-ci.com/fhd-api"
    ).strip()
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/") + "/"


def _api_url(path: str, base_url: str | None = None) -> str:
    base = (base_url or _facade()._relay_base_url()).rstrip("/") + "/"
    return f"{base}{path.lstrip('/')}"


def _read_config() -> dict[str, _facade().Any]:
    try:
        if not _facade()._CONFIG_FILE.is_file():
            return {}
        data = _facade().json.loads(_facade()._CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, _facade().json.JSONDecodeError):
        _facade().logger.warning(
            "mobile relay desktop config is unreadable: %s", _facade()._CONFIG_FILE, exc_info=True
        )
        return {}


def _public_payload_from_config(
    config: dict[str, _facade().Any],
) -> dict[str, _facade().Any] | None:
    relay_id = str(config.get("relay_id") or "").strip()
    pairing_code = str(config.get("pairing_code") or "").strip()
    if not relay_id or not pairing_code:
        return None
    base_url = str(config.get("relay_base_url") or "").strip() or _facade()._relay_base_url()
    exp = int(config.get("exp") or 0)
    if exp <= 0:
        registered_at = int(config.get("registered_at") or 0)
        if registered_at > 0:
            exp = registered_at + int(
                _facade().os.environ.get("XCAGI_RELAY_PAIRING_TTL_SEC") or "86400"
            )
    if exp > 0 and exp <= int(_facade().time.time()):
        return None
    expires_at = str(config.get("expires_at") or "").strip()
    return {
        "relay_id": relay_id,
        "pairing_code": pairing_code,
        "paired": bool(config.get("paired")),
        "mobile_username": str(config.get("mobile_username") or "").strip(),
        "last_relay_sync_at": int(config.get("last_relay_sync_at") or 0),
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


def cached_desktop_relay_payload() -> dict[str, _facade().Any] | None:
    """Return the public part of the persisted relay binding, if available."""
    config = _facade()._read_config()
    payload = _facade()._public_payload_from_config(config)
    if payload is not None:
        return payload
    if not config.get("paired"):
        return None
    relay_id = str(config.get("relay_id") or "").strip()
    if not relay_id:
        return None
    return {
        "relay_id": relay_id,
        "relay_base_url": str(config.get("relay_base_url") or "") or _facade()._relay_base_url(),
        "paired": True,
        "mobile_username": str(config.get("mobile_username") or "").strip(),
        "last_relay_sync_at": int(config.get("last_relay_sync_at") or 0),
    }


def _write_config(data: dict[str, _facade().Any]) -> None:
    _facade()._CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _facade()._CONFIG_FILE.write_text(
        _facade().json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def register_desktop_relay(
    *, host: str, port: int, label: str = "", force_new: bool = False
) -> dict[str, _facade().Any] | None:
    """Register this desktop with the public relay and start the poller.

    根治 relay 身份漂移：桌面只要本地已存有效身份（relay_id + desktop_token），默认**复用**它并
    起 poller，**绝不重新向服务器注册**。否则每次启动 / 每次点「出配对码」都会申请一个全新 relay_id
    覆盖本地，把已和手机配对好的旧身份丢弃——任务仍派给旧（离线）relay、新 relay 又是 pending 领不到，
    超级员工任务永远卡「排队中」。仅当本地无身份、或调用方显式 ``force_new=True``（用户主动重新配对）
    时才注册新身份。
    """
    if not force_new:
        existing = _facade()._read_config()
        has_identity = bool(
            str(existing.get("relay_id") or "").strip()
            and str(existing.get("desktop_token") or "").strip()
        )
        valid_payload = _facade()._public_payload_from_config(existing)
        if has_identity and (existing.get("paired") or valid_payload):
            _facade().start_desktop_relay_poller()
            return valid_payload or {
                "relay_id": str(existing.get("relay_id") or ""),
                "relay_base_url": str(existing.get("relay_base_url") or "")
                or _facade()._relay_base_url(),
                "paired": bool(existing.get("paired")),
            }
    base_url = _facade()._relay_base_url()
    device_label = label.strip() or f"XCAGI 桌面执行端 - {_facade().socket.gethostname()}"
    body = {
        "label": device_label,
        "device_id": _facade().get_stable_device_id(),
        "relay_base_url": base_url,
        "capabilities": {
            "codex": True,
            "codex_cli": True,
            "claude": True,
            "claude_cli": True,
            "cursor": True,
            "cursor_cli": True,
            "trae": True,
            "trae_cli": True,
            "desktop": True,
            "host": host,
            "port": int(port),
            "platform": _facade().platform.platform(),
        },
    }
    timeout = float(_facade().os.environ.get("XCAGI_RELAY_REGISTER_TIMEOUT_SEC") or "5")
    try:
        with _facade()._relay_http_client(timeout) as client:
            resp = client.post(
                _facade()._api_url("/api/mobile/v1/relay/desktop/register", base_url), json=body
            )
            resp.raise_for_status()
            payload = resp.json()
    except (_facade().httpx.HTTPError, _facade().httpx.InvalidURL, ValueError) as exc:
        _facade().logger.warning("mobile relay desktop register failed: %s", exc)
        cached = _facade().cached_desktop_relay_payload()
        if cached:
            _facade().start_desktop_relay_poller()
            return cached
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("desktop_token") or (not data.get("relay_id")):
        _facade().logger.warning("mobile relay desktop register returned invalid payload")
        return None
    config = {
        "relay_id": str(data.get("relay_id") or ""),
        "desktop_token": str(data.get("desktop_token") or ""),
        "relay_base_url": str(data.get("relay_base_url") or base_url),
        "pairing_code": str(data.get("pairing_code") or ""),
        "expires_at": str(data.get("expires_at") or ""),
        "exp": int(data.get("exp") or 0),
        "registered_at": int(_facade().time.time()),
        "label": device_label,
    }
    _facade()._write_config(config)
    _facade().start_desktop_relay_poller()
    return data


def _gc_orphan_workspaces() -> int:
    """回收崩溃残留的隔离工作区，避免磁盘缓慢膨胀（满足『无垃圾残留』）。

    只清 age-based 超期（默认 6h）的**已知临时目录**：dev-loop 的 ``xcagi-wt-*``
    与产品域 scratch 子目录；活跃任务都是近期的，绝不会误删。另对底座仓库跑
    ``git worktree prune`` 清理目录已不存在的 worktree 元数据。返回清理的目录数。
    """
    try:
        max_age = float(
            _facade().os.environ.get("XCAGI_RELAY_WORKSPACE_GC_MAX_AGE_SEC") or str(6 * 3600)
        )
    except (TypeError, ValueError):
        max_age = 6 * 3600.0
    now = _facade().time.time()
    tmp = _facade().Path(_facade().tempfile.gettempdir())
    targets: list[_facade().Path] = list(tmp.glob("xcagi-wt-*"))
    scratch = tmp / "xcmax_product_scratch"
    if scratch.is_dir():
        targets += [p for p in scratch.iterdir() if p.is_dir()]
    removed = 0
    for path in targets:
        try:
            if now - path.stat().st_mtime < max_age:
                continue
        except OSError:
            continue
        _facade().shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            removed += 1
    if removed:
        _facade().logger.info("relay 工作区 GC：清理 %d 个超期残留目录", removed)
    return removed


def start_desktop_relay_poller() -> bool:
    """Start the daemon poller if a relay config exists."""
    config = _facade()._read_config()
    if not config.get("relay_id") or not config.get("desktop_token"):
        return False
    _facade().logging.getLogger("httpx").setLevel(_facade().logging.WARNING)
    try:
        _facade()._gc_orphan_workspaces()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("relay 工作区 GC 失败", exc_info=True)
    global _WORKER_THREAD
    with _facade()._STATE_LOCK:
        if _facade()._WORKER_THREAD and _facade()._WORKER_THREAD.is_alive():
            return True
        _facade()._STOP_EVENT.clear()
        _facade()._WORKER_THREAD = _facade().threading.Thread(
            target=_facade()._poll_loop, name="xcagi-mobile-relay-desktop", daemon=True
        )
        _facade()._WORKER_THREAD.start()
        return True


def stop_desktop_relay_poller() -> None:
    """Stop the poll loop and wait for its in-flight HTTP request to close.

    Merely setting the event leaves the daemon thread alive until the current
    synchronous ``httpx`` request returns.  During repeated FastAPI lifespan
    start/stop cycles that leaked the request transport into the next test (and
    can do the same during a desktop restart).  Join outside ``_STATE_LOCK`` so
    shutdown cannot deadlock with a concurrently starting poller.
    """
    facade = _facade()
    facade._STOP_EVENT.set()
    with facade._STATE_LOCK:
        worker = facade._WORKER_THREAD
    if worker is None or worker is facade.threading.current_thread():
        return
    try:
        request_timeout = float(facade.os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
    except (TypeError, ValueError):
        request_timeout = 30.0
    worker.join(timeout=max(1.0, request_timeout + 1.0))
    with facade._STATE_LOCK:
        if facade._WORKER_THREAD is worker and (not worker.is_alive()):
            facade._WORKER_THREAD = None
    if worker.is_alive():
        facade.logger.warning(
            "mobile relay poller did not stop within %.1fs", request_timeout + 1.0
        )


def _relay_poll_backoff_seconds(
    failure_count: int, *, base_interval: float, max_interval: float
) -> float:
    """Return bounded exponential backoff for an unavailable public relay."""
    failures = max(0, int(failure_count))
    if failures <= 0:
        return max(1.0, base_interval)
    return _facade().cast(
        "float", min(max_interval, max(1.0, base_interval) * 2 ** min(failures - 1, 8))
    )
