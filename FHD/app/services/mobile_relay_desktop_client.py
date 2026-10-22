"""Desktop relay composition and stable public callback surface.

Persistence, pairing, task delivery, execution and lifecycle have independent
collaborators. The legacy module-level state remains an explicit adapter for
existing desktop integrations and test patches.
"""

from __future__ import annotations

import json as json
import logging
import os
import platform
import re as re
import shutil
import socket
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast as cast

import httpx

from app.services.desktop_relay.cleanup import CleanupPorts, WorkspaceCollector
from app.services.desktop_relay.configuration import ConfigurationPorts, RelayConfigStore
from app.services.desktop_relay.execution import ExecutionPorts, RelayTaskExecutor
from app.services.desktop_relay.lifecycle import LifecyclePorts, RelayLifecycle
from app.services.desktop_relay.lifecycle import poll_backoff_seconds as _relay_poll_backoff_seconds
from app.services.desktop_relay.messages import (
    _BLOCKED_STATUSES as _BLOCKED_STATUSES,
)
from app.services.desktop_relay.messages import (
    _BRANCH_TOKEN_RE as _BRANCH_TOKEN_RE,
)
from app.services.desktop_relay.messages import (
    _COMPLETED_STATUSES as _COMPLETED_STATUSES,
)
from app.services.desktop_relay.messages import (
    _DIFF_TEXT_MARKERS as _DIFF_TEXT_MARKERS,
)
from app.services.desktop_relay.messages import (
    _DISCARD_TEXT_MARKERS as _DISCARD_TEXT_MARKERS,
)
from app.services.desktop_relay.messages import (
    _EVIDENCE_FILE_RE as _EVIDENCE_FILE_RE,
)
from app.services.desktop_relay.messages import (
    _EXECUTION_EVIDENCE_MARKERS as _EXECUTION_EVIDENCE_MARKERS,
)
from app.services.desktop_relay.messages import (
    _EXECUTION_MESSAGE_MARKERS as _EXECUTION_MESSAGE_MARKERS,
)
from app.services.desktop_relay.messages import (
    _FAILED_STATUSES as _FAILED_STATUSES,
)
from app.services.desktop_relay.messages import (
    _FAILURE_BODY_MARKERS as _FAILURE_BODY_MARKERS,
)
from app.services.desktop_relay.messages import (
    _MERGE_TEXT_MARKERS as _MERGE_TEXT_MARKERS,
)
from app.services.desktop_relay.messages import (
    _body_has_execution_evidence as _body_has_execution_evidence,
)
from app.services.desktop_relay.messages import (
    _body_indicates_failed as _body_indicates_failed,
)
from app.services.desktop_relay.messages import (
    _body_indicates_unfinished as _body_indicates_unfinished,
)
from app.services.desktop_relay.messages import (
    _classify_terminal_result as _classify_terminal_result,
)
from app.services.desktop_relay.messages import (
    _extract_branch_after as _extract_branch_after,
)
from app.services.desktop_relay.messages import (
    _extract_merge_source as _extract_merge_source,
)
from app.services.desktop_relay.messages import (
    _extract_merge_target as _extract_merge_target,
)
from app.services.desktop_relay.messages import (
    _extract_target_branch as _extract_target_branch,
)
from app.services.desktop_relay.messages import (
    _extract_tool_calls as _extract_tool_calls,
)
from app.services.desktop_relay.messages import (
    _git_op_from_message as _git_op_from_message,
)
from app.services.desktop_relay.messages import (
    _message_requires_execution_evidence as _message_requires_execution_evidence,
)
from app.services.desktop_relay.messages import (
    _terminal_codex_message as _terminal_codex_message,
)
from app.services.desktop_relay.messages import (
    _terminal_error_summary as _terminal_error_summary,
)
from app.services.desktop_relay.messages import (
    _text_mentions_branch_op as _text_mentions_branch_op,
)
from app.services.desktop_relay.messages import (
    _trim_branch_token as _trim_branch_token,
)
from app.services.desktop_relay.polling import PollingPorts, RelayTaskDelivery
from app.services.desktop_relay.ports import (
    CompletionCall,
    ConditionalConfigUpdate,
    JsonObject,
    ReadConfig,
    SuperEmployeeFactory,
    Worker,
    WriteConfig,
    late_callback,
)
from app.services.desktop_relay.registration import RegistrationPorts, RelayRegistration
from app.services.relay_gitops import GIT_OP_KINDS as GIT_OP_KINDS
from app.services.relay_gitops import handle_git_op
from app.utils.device_system.device_identity import get_stable_device_id
from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir, get_desktop_state_dir

logger = logging.getLogger(__name__)

ClaudeSuperEmployeeService: SuperEmployeeFactory | None = None
CodexSuperEmployeeService: SuperEmployeeFactory | None = None
CursorSuperEmployeeService: SuperEmployeeFactory | None = None
TraeSuperEmployeeService: SuperEmployeeFactory | None = None
_STATE_LOCK = threading.Lock()
_WORKER_THREAD: Worker | None = None
_STOP_EVENT = threading.Event()
_INFLIGHT: set[str] = set()
_INFLIGHT_LOCK = threading.Lock()
_CONFIG_FILE = Path(get_desktop_state_dir()) / "mobile_relay_desktop.json"
_LEGACY_CONFIG_FILE = Path(get_app_data_dir()) / "mobile_relay_desktop.json"
_LEGACY_MIGRATION_DONE = False


def _mark_legacy_migrated() -> None:
    global _LEGACY_MIGRATION_DONE
    _LEGACY_MIGRATION_DONE = True


def _set_worker(worker: Worker | None) -> None:
    global _WORKER_THREAD
    _WORKER_THREAD = worker


def _create_worker(callback: Callable[[], None], name: str) -> Worker:
    return threading.Thread(target=callback, name=name, daemon=True)


def _relay_http_client(timeout: float) -> httpx.Client:
    """云中继须直连公网 API；桌面系统代理未运行时 trust_env 会导致 Invalid port 等异常。"""
    return httpx.Client(timeout=timeout, trust_env=False)


def _ensure_super_employee_service_classes() -> None:
    global ClaudeSuperEmployeeService, CodexSuperEmployeeService, CursorSuperEmployeeService
    global TraeSuperEmployeeService
    if (
        ClaudeSuperEmployeeService is not None
        and CodexSuperEmployeeService is not None
        and (CursorSuperEmployeeService is not None)
        and (TraeSuperEmployeeService is not None)
    ):
        return
    if ClaudeSuperEmployeeService is None:
        from app.application.claude_super_employee_service import (
            ClaudeSuperEmployeeService as _ClaudeSuperEmployeeService,
        )

        ClaudeSuperEmployeeService = _ClaudeSuperEmployeeService
    if CodexSuperEmployeeService is None:
        from app.application.codex_super_employee_service import (
            CodexSuperEmployeeService as _CodexSuperEmployeeService,
        )

        CodexSuperEmployeeService = _CodexSuperEmployeeService
    if CursorSuperEmployeeService is None:
        from app.application.cursor_super_employee_service import (
            CursorSuperEmployeeService as _CursorSuperEmployeeService,
        )

        CursorSuperEmployeeService = _CursorSuperEmployeeService
    if TraeSuperEmployeeService is None:
        from app.application.trae_super_employee_service import (
            TraeSuperEmployeeService as _TraeSuperEmployeeService,
        )

        TraeSuperEmployeeService = _TraeSuperEmployeeService


def _max_concurrent() -> int:
    try:
        return max(1, int(os.environ.get("XCAGI_RELAY_MAX_CONCURRENT") or "3"))
    except (TypeError, ValueError):
        return 3


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


_config_store = RelayConfigStore(
    ConfigurationPorts(
        path=lambda: _CONFIG_FILE,
        legacy_path=lambda: _LEGACY_CONFIG_FILE,
        migration_done=lambda: _LEGACY_MIGRATION_DONE,
        mark_migrated=_mark_legacy_migrated,
        read_config=late_callback(lambda: _read_config),
        write_config=late_callback(lambda: _write_config),
        base_url=late_callback(lambda: _relay_base_url),
    ),
    logger,
)
_read_config: ReadConfig = _config_store.read
_write_config: WriteConfig = _config_store.write
_migrate_legacy_config_once = _config_store.migrate_legacy_once
_update_config_if_current: ConditionalConfigUpdate = _config_store.update_if_current
_replace_config_if_current: ConditionalConfigUpdate = _config_store.replace_if_current

_registration = RelayRegistration(
    RegistrationPorts(
        read_config=late_callback(lambda: _read_config),
        write_config=late_callback(lambda: _write_config),
        update_config=late_callback(lambda: _update_config_if_current),
        replace_config=late_callback(lambda: _replace_config_if_current),
        base_url=late_callback(lambda: _relay_base_url),
        api_url=late_callback(lambda: _api_url),
        http_client=late_callback(lambda: _relay_http_client),
        now=lambda: time.time(),
        environment=lambda: os.environ,
        device_id=late_callback(lambda: get_stable_device_id),
        hostname=lambda: socket.gethostname(),
        platform=lambda: platform.platform(),
        start_poller=late_callback(lambda: start_desktop_relay_poller),
        public_payload=late_callback(lambda: _public_payload_from_config),
    ),
    logger,
)
_public_payload_from_config: Callable[[JsonObject], JsonObject | None] = (
    _registration.public_payload
)
cached_desktop_relay_payload = _registration.cached_payload
register_desktop_relay = _registration.register

_collector = WorkspaceCollector(
    CleanupPorts(
        temporary_root=lambda: Path(tempfile.gettempdir()),
        max_age=lambda: float(
            os.environ.get("XCAGI_RELAY_WORKSPACE_GC_MAX_AGE_SEC") or str(6 * 3600)
        ),
        now=lambda: time.time(),
        remove_tree=lambda path: shutil.rmtree(path, ignore_errors=True),
    ),
    logger,
)
_gc_orphan_workspaces = _collector.collect

_executor = RelayTaskExecutor(
    ExecutionPorts(
        ensure_services=late_callback(lambda: _ensure_super_employee_service_classes),
        claude_factory=lambda: ClaudeSuperEmployeeService,
        codex_factory=lambda: CodexSuperEmployeeService,
        cursor_factory=lambda: CursorSuperEmployeeService,
        trae_factory=lambda: TraeSuperEmployeeService,
        git_op=late_callback(lambda: handle_git_op),
        git_message=late_callback(lambda: _git_op_from_message),
        classify_result=late_callback(lambda: _classify_terminal_result),
        terminal_message=late_callback(lambda: _terminal_codex_message),
        tool_calls=late_callback(lambda: _extract_tool_calls),
        environment=lambda: os.environ,
        monotonic=lambda: time.monotonic(),
        sleep=lambda seconds: time.sleep(seconds),
    ),
    logger,
)
_execute_task = _executor.execute

_delivery = RelayTaskDelivery(
    PollingPorts(
        read_config=late_callback(lambda: _read_config),
        update_config=late_callback(lambda: _update_config_if_current),
        base_url=late_callback(lambda: _relay_base_url),
        api_url=late_callback(lambda: _api_url),
        http_client=late_callback(lambda: _relay_http_client),
        timeout=lambda: float(os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30"),
        now=lambda: time.time(),
        monotonic=lambda: time.monotonic(),
        state_lock=lambda: _STATE_LOCK,
        stop_signal=lambda: _STOP_EVENT,
        inflight=lambda: _INFLIGHT,
        inflight_lock=lambda: _INFLIGHT_LOCK,
        max_concurrent=late_callback(lambda: _max_concurrent),
        create_worker=late_callback(lambda: _create_worker),
        complete_task=lambda: _complete_relay_task,
        execute_task=late_callback(lambda: _execute_task),
    ),
    logger,
)
_poll_once = _delivery.poll_once
_complete_relay_task: CompletionCall = _delivery.complete

_lifecycle = RelayLifecycle(
    LifecyclePorts(
        read_config=late_callback(lambda: _read_config),
        state_lock=lambda: _STATE_LOCK,
        stop_signal=lambda: _STOP_EVENT,
        worker=lambda: _WORKER_THREAD,
        set_worker=_set_worker,
        create_worker=late_callback(lambda: _create_worker),
        current_worker=lambda: threading.current_thread(),
        collect_workspaces=late_callback(lambda: _gc_orphan_workspaces),
        poll_loop=lambda: _poll_loop,
        poll_once=late_callback(lambda: _poll_once),
        backoff=late_callback(lambda: _relay_poll_backoff_seconds),
        environment=lambda: os.environ,
        monotonic=lambda: time.monotonic(),
    ),
    logger,
)
_poll_loop: Callable[[], None] = _lifecycle.poll_loop
start_desktop_relay_poller: Callable[[], bool] = _lifecycle.start
stop_desktop_relay_poller = _lifecycle.stop
