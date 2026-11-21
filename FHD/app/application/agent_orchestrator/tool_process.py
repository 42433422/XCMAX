"""Spawn-only tool boundary; never inherit a request transaction or live cookie jar."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from contextvars import copy_context
from datetime import date, datetime
from decimal import Decimal
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any, cast

import psutil

from app.utils.operational_errors import BOUNDARY_ERRORS

_STREAM_FRAME_LIMIT = 256 * 1024
_RESOURCE_POLL_SECONDS = 0.1


class _WorkerResourceError(RuntimeError):
    def __init__(self, code: str, *, limit_bytes: int, rss_bytes: int = 0):
        super().__init__(code)
        self.code, self.limit_bytes, self.rss_bytes = code, limit_bytes, rss_bytes


class _ProcessTreeMemoryGuard:
    """Parent-owned sampled RSS budget, not a kernel memory isolation boundary.

    Retain observed PID/create-time identities across reparenting. Descendants
    created and orphaned entirely between samples remain an observation limit.
    Shared pages count in each process, making the sum conservative.
    """

    def __init__(self, pid: int, limit_bytes: int):
        self.limit_bytes, self.peak_bytes = limit_bytes, 0
        self.processes: dict[tuple[int, float], Any] = {}
        try:
            if not _process_namespace_matches():
                raise psutil.AccessDenied(pid)
            root = psutil.Process(pid)
            self.root_identity = (root.pid, root.create_time())
            self.processes[self.root_identity] = root
        except (psutil.Error, OSError) as exc:
            raise self._unavailable() from exc

    def _unavailable(self):
        return _WorkerResourceError(
            "tool_memory_monitor_unavailable",
            limit_bytes=self.limit_bytes,
            rss_bytes=self.peak_bytes,
        )

    @property
    def descendants(self):
        return tuple(p for identity, p in self.processes.items() if identity != self.root_identity)

    def check(self) -> None:
        pending = list(self.processes.items())
        inspected = set()
        total = 0
        try:
            while pending:
                identity, process = pending.pop()
                if identity in inspected:
                    continue
                inspected.add(identity)
                try:
                    # is_running checks PID reuse before memory reads and discovery.
                    if not process.is_running():
                        self.processes.pop(identity, None)
                        continue
                    for child in process.children(recursive=True):
                        try:
                            child_identity = (child.pid, child.create_time())
                        except psutil.NoSuchProcess:
                            continue
                        self.processes.setdefault(child_identity, child)
                        pending.append((child_identity, self.processes[child_identity]))
                    total += process.memory_info().rss
                except psutil.NoSuchProcess:
                    self.processes.pop(identity, None)
                    continue
                self.peak_bytes = max(self.peak_bytes, total)
                if total > self.limit_bytes:
                    raise _WorkerResourceError(
                        "tool_memory_limit_exceeded", limit_bytes=self.limit_bytes, rss_bytes=total
                    )
        except (psutil.Error, OSError) as exc:
            # A live process that cannot be inspected is never counted as zero.
            raise self._unavailable() from exc


class _WorkerProcessSupervisor:
    """Share process release, bounded waits and cleanup with the browser CI contract."""

    def __init__(self, process, *, memory_limit_bytes: int | None = None):
        self.process, self.memory_limit_bytes = process, memory_limit_bytes
        self.memory_guard = None
        self.clean = True
        self._closed = False

    def start(self):
        self.process.start()
        if self.memory_limit_bytes is not None:
            self.memory_guard = _ProcessTreeMemoryGuard(self.process.pid, self.memory_limit_bytes)
            self.check()
        return self

    def check(self):
        if self.memory_guard is not None:
            self.memory_guard.check()

    def release(self, start):
        self.check()
        start.set()

    def wait_ack(self, control, marker, deadline, *, renew=None):
        return _worker_acknowledged(
            control, self.process, marker, deadline, renew=renew, memory_guard=self.memory_guard
        )

    def wait_event(self, event, deadline):
        while True:
            self.check()
            remaining = max(0, deadline - time.monotonic())
            if event.wait(
                min(remaining, _RESOURCE_POLL_SECONDS) if self.memory_guard else remaining
            ):
                self.check()
                return True
            if time.monotonic() >= deadline:
                return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.process.pid is not None:
            try:
                self.clean = (
                    _reap(self.process, observed=self.memory_guard.descendants)
                    if self.memory_guard is not None
                    else _reap(self.process)
                )
                if self.clean:
                    self.process.close()
            except OSError:
                self.clean = False

    def __enter__(self):
        try:
            return self.start()
        except BOUNDARY_ERRORS:
            self.close()
            raise

    def __exit__(self, *_exc):
        self.close()


@contextmanager
def _worker_stream(connection):
    """Restore observation scope across spawn; the OS pipe bounds queued bytes."""
    if connection is None:
        yield
        return
    from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime

    lifetime = StreamLifetime()
    lock = threading.Lock()

    def send(kind, value):
        encoded = json.dumps(
            {"kind": kind, "value": value}, allow_nan=False, default=_json_scalar
        ).encode("utf-8")
        if len(encoded) > _STREAM_FRAME_LIMIT:
            raise ValueError("tool stream frame exceeds transport limit")
        # Never pickle a tool-controlled object. A slow receiver may apply
        # backpressure, but the caller still reaps this process at its deadline.
        with lock:
            connection.send_bytes(encoded)

    lifetime.observe_notes(lambda value: send("note", value))
    lifetime.observe_deltas(lambda value: send("delta", value))
    lifetime.observe_tools(lambda *, sequence, record: send("tool", record))
    token = current_lifetime.set(lifetime)
    try:
        yield lambda: send("end", lifetime.reason == "tool_receipt_persistence_failed")
    finally:
        current_lifetime.reset(token)


def _relay_stream(connection, lifetime, drained, failed, stopped, *, keep_connection=False):
    """Deliver in order without letting an observer disable process deadlines."""
    publishers = {
        "note": (str, lifetime.publish_note),
        "delta": (str, lifetime.publish_delta),
        "tool": (dict, lifetime.publish_tool_record),
    }
    try:
        while not stopped.is_set():
            event = json.loads(connection.recv_bytes(_STREAM_FRAME_LIMIT))
            if isinstance(event, dict) and event.get("kind") == "end":
                if not isinstance(event.get("value"), bool):
                    raise ValueError("invalid tool stream completion")
                if event["value"]:
                    failed.set()
                break
            if not isinstance(event, dict) or event.get("kind") not in publishers:
                raise ValueError("invalid tool stream event")
            value_type, publish = publishers[event["kind"]]
            if not isinstance(event.get("value"), value_type):
                raise ValueError("invalid tool stream value")
            if not stopped.is_set():
                publish(event["value"])
    except BOUNDARY_ERRORS:
        if not stopped.is_set():
            failed.set()
            logging.getLogger(__name__).warning("tool stream receipt failed", exc_info=True)
    finally:
        if not keep_connection:
            connection.close()
        lifetime.worker_finished()
        drained.set()


def dump_tool_output(output: dict) -> str:
    """Encode a tool result for the idempotency ledger and the worker transport."""
    return json.dumps(output, ensure_ascii=False, default=_json_scalar)


def _json_scalar(value):
    # Match API numeric/date encoding; never stringify arbitrary service objects.
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        return int(value) if isinstance(exponent, int) and exponent >= 0 else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"unsupported tool result value:{type(value).__name__}")


# 明显敏感的环境键片段：子进程不应继承调用方凭据。
_SENSITIVE_ENV_MARKERS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
    "PRIVATE_KEY",
    "COOKIE",
)
# 子进程自身配置前缀，始终透传。
_ENV_KEEP_PREFIXES = ("XCAGI_",)


def _scrubbed_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """清洗继承环境：删除敏感键，保留系统必需变量与 XCAGI_* 配置。"""
    source = os.environ if environ is None else environ
    return {
        key: value
        for key, value in source.items()
        if key.upper().startswith(_ENV_KEEP_PREFIXES)
        or not any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
    }


def _sandbox_enabled() -> bool:
    return str(os.environ.get("XCAGI_TOOL_SANDBOX") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _env_scrub_enabled() -> bool:
    """环境清洗默认关闭：部分工具需要调用模型凭据，贸然删除会导致业务失败。"""
    return str(os.environ.get("XCAGI_TOOL_SANDBOX_SCRUB_ENV") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _limit_from_env(name: str, default: int) -> int:
    """读取正整数限制值；缺失或非法时回退默认值。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        logging.getLogger(__name__).warning("invalid %s, fallback to %s", name, default)
        return default
    return value


def _apply_resource_limits(*, browser: bool = False):
    """设置子进程 POSIX 限制并保留继承的硬上限；设置失败记录告警，不阻断执行。"""
    if not _sandbox_enabled():
        return
    log = logging.getLogger(__name__)
    try:
        import resource
    except ImportError:
        # 非 POSIX 平台（如 Windows）没有 resource 模块，由父进程 deadline 兜底。
        log.warning("tool worker resource limits unavailable on this platform")
        return
    previous_as = None
    targets = (
        ("RLIMIT_CPU", _limit_from_env("XCAGI_TOOL_CPU_SECONDS", 60)),
        # V8 reserves a large virtual cage; browser RSS is separately bounded
        # across the whole process tree by browser_tool_process's parent watchdog.
        (
            "RLIMIT_AS",
            _limit_from_env(
                "XCAGI_BROWSER_ADDRESS_MB" if browser else "XCAGI_TOOL_MEMORY_MB",
                1572864 if browser else 2048,
            )
            * 1024
            * 1024,
        ),
        ("RLIMIT_NOFILE", _limit_from_env("XCAGI_TOOL_MAX_FILES", 256)),
    )
    for name, value in targets:
        limit_type = getattr(resource, name, None)
        if limit_type is None:
            continue
        try:
            prior = resource.getrlimit(limit_type)
            _, hard = prior
            # 硬限制不可通过非特权方式提高，软限制不得超过现有硬限制。
            target = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(limit_type, (target, hard))
            if name == "RLIMIT_AS":
                previous_as = prior
        except (OSError, ValueError) as exc:
            log.warning("tool worker %s limit not applied: %s", name, type(exc).__name__)
    return previous_as


def _worker_start(control, start, deadline, *, monitored_memory=False, browser=False):
    # Startup still uses AS. Restore only the inherited AS limit after the
    # supervising parent has checked RSS and released this trusted handshake.
    previous_as = (
        _apply_resource_limits(browser=browser)
        if multiprocessing.parent_process() is not None
        else None
    )
    if os.name != "nt":
        os.setsid()
    control.send_bytes(b"r")
    if not start.wait(max(0, deadline - time.monotonic())):
        return False
    if monitored_memory and previous_as is not None:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, previous_as)
    return True


def _worker(
    executor_type,
    payload,
    folder,
    control,
    start,
    deadline,
    llm_scope=None,
    catalog_profile=None,
    catalog_claim=None,
    stream_connection=None,
    elt_claim=None,
    surface_claim=None,
    monitored_memory=False,
    *,
    initialize=True,
    retain=False,
    browser=False,
):
    from app.application.agent_orchestrator.business_write_guard import restore_worker_claim
    from app.application.agent_orchestrator.run_models import agent_step_from_dict
    from app.application.agent_orchestrator.tool_timeouts import (
        ELT_FILE_PHASES,
        ELT_FILE_WATCHDOG_SECONDS,
        uses_elt_file_deadlines,
    )
    from app.application.tool_execution_deadline import invocation_deadline
    from app.infrastructure.llm.client import (
        llm_client_factory_scope,
        restore_worker_llm_client,
        scoped_route_metadata,
    )
    from app.neuro_bus.tracer import TraceContext

    # 真正执行工具前先收敛子进程能力：环境清洗 + POSIX 资源软限制。
    # 失败只告警，调度语义仍由父进程 deadline 与进程回收保证。
    if initialize and _env_scrub_enabled():
        scrubbed_env = _scrubbed_env()
        try:
            os.environ.clear()
            os.environ.update(scrubbed_env)
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning(
                "tool worker env scrub skipped: %s", type(exc).__name__
            )
    # 资源限制只属于 spawn 出的工具子进程。在原进程内调用
    # _worker（测试或误入父进程）时若施加 RLIMIT_CPU，累计 CPU
    # 已超过工具预算就会立即 SIGXCPU 杀死调用方。
    if initialize:
        if not _worker_start(
            control,
            start,
            deadline,
            monitored_memory=monitored_memory,
            browser=browser,
        ):
            return
    else:
        control.send_bytes(b"r")
        if not start.wait(max(0, deadline - time.monotonic())):
            return
    route_metadata: dict[str, str | int] = {}
    worker_client: tuple[Any, str] | None = None
    finish_stream = None

    def restore_llm_scope():
        nonlocal worker_client
        if worker_client is None:
            worker_client = restore_worker_llm_client(llm_scope)
        return worker_client

    try:
        data = json.loads(payload)
        step = agent_step_from_dict(data["step"])
        context = data["context"]
        context.pop("durable_elt_batch", None)
        if elt_claim is not None:
            context["durable_elt_batch"] = True
        business_db_url = str(data.get("business_db_url") or "")
        office_stage = (data["step"].get("tool_id"), data["step"].get("action")) == (
            "excel_import",
            "office_stage",
        )
        surface_step = step.tool_id in {"browser", "aiopen"}
        if office_stage and not business_db_url:
            raise RuntimeError("office approval database is unavailable")
        if business_db_url and not _bind_worker_business_db(
            business_db_url, bind_workflow_db=office_stage or surface_step
        ):
            Path(folder, "result").write_text(
                json.dumps(
                    {
                        "output": {
                            "success": False,
                            "error_code": "business_db_unbound",
                            "outcome": "unknown",
                            "retryable": False,
                            "reconciliation_required": True,
                            "message": "工具进程未能绑定调用方业务库",
                        },
                        "uncertain": [],
                        "llm_route_metadata": {},
                    }
                ),
                encoding="utf-8",
            )
            control.send_bytes(b"d")
            return
        from app.application.agent_orchestrator.catalog_product_worker import (
            restore_catalog_claim,
            restore_catalog_worker_profile,
        )

        restore_catalog_worker_profile(catalog_profile)
        with (
            TraceContext(
                context.get("trace_id"),
                context.get("span_id"),
                request_id=context.get("request_id"),
                trace_flags=context.get("trace_flags"),
                trace_state=context.get("trace_state"),
            ),
            restore_catalog_claim(catalog_claim),
            restore_worker_claim(elt_claim, elt_step_id=step.step_id if elt_claim else ""),
            restore_worker_claim(surface_claim),
            invocation_deadline(deadline) as budget,
            llm_client_factory_scope(restore_llm_scope) if llm_scope is not None else nullcontext(),
            _worker_stream(stream_connection) as finish_stream,
        ):
            if uses_elt_file_deadlines(step.tool_id, step.action, step.params or {}):

                def renew_file_deadline(phase: str) -> float:
                    marker = ELT_FILE_PHASES[phase]
                    renewed_deadline = time.monotonic() + ELT_FILE_WATCHDOG_SECONDS[marker]
                    budget.deadline = renewed_deadline
                    control.send_bytes(marker)
                    return renewed_deadline

                context["_renew_elt_file_deadline"] = renew_file_deadline
            try:
                output = executor_type().execute(step, runtime_context=context)
            finally:
                route_metadata = scoped_route_metadata(worker_client[0] if worker_client else None)
        encoded = json.dumps(
            {"output": output, "uncertain": budget.uncertain, "llm_route_metadata": route_metadata},
            allow_nan=False,
            default=_json_scalar,
        )
        if len(encoded.encode()) > 8 * 1024 * 1024:
            raise ValueError("tool result exceeds transport limit")
        Path(folder, "result").write_text(encoded, encoding="utf-8")
        control.send_bytes(b"d")
    except BOUNDARY_ERRORS as exc:
        # Dispatch may already have written: preserve uncertainty without waiting
        # out the deadline or inviting a duplicate write. Never expose raw errors.
        Path(folder, "result").write_text(
            json.dumps(
                {
                    "output": {
                        "outcome": "unknown",
                        "error_code": "tool_result_transport_failed",
                        "exception_type": type(exc).__name__,
                        "retryable": False,
                    },
                    "uncertain": [],
                    "llm_route_metadata": route_metadata,
                }
            ),
            encoding="utf-8",
        )
        control.send_bytes(b"d")
    finally:
        if stream_connection is not None:
            try:
                # A forked descendant can retain this FD. An ordered end frame
                # drains our events without waiting for every descendant's EOF.
                if finish_stream is not None:
                    finish_stream()
                else:
                    stream_connection.send_bytes(b'{"kind":"end","value":false}')
            except OSError:
                pass  # The parent already records an interrupted/missing receipt.
            finally:
                if not retain:
                    stream_connection.close()
        # Keep ancestry intact until the parent has reaped tool-created children.
        if not retain:
            start.clear()
            start.wait()


def _process_namespace_matches() -> bool:
    procfs = getattr(psutil, "PROCFS_PATH", None)
    if procfs is None:
        return True
    try:
        for line in Path(procfs, "self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("NSpid:"):
                # IDs are relative to the procfs mount. An ancestor's procfs
                # cannot safely identify the PIDs used by this process's syscalls.
                return line.split()[1:] == [str(os.getpid())]
    except OSError:
        pass
    return False


def _reap(process, *, observed=()) -> bool:
    children = []
    tree_collected = False
    clean = True
    root = None
    try:
        if not _process_namespace_matches():
            # Only this owned child handle is trustworthy. Its descendants are
            # unverified, so killing it cannot establish successful cleanup.
            return False
        children = list(observed)
        root = psutil.Process(process.pid)
        root.suspend()
        # Freeze parents before collecting descendants to stop ordinary spawn races.
        for _ in range(2):
            for parent in [root, *observed]:
                try:
                    if parent is not root:
                        parent.suspend()
                    for child in parent.children(recursive=True):
                        if child not in children:
                            children.append(child)
                        try:
                            child.suspend()
                        except psutil.NoSuchProcess:
                            continue
                except psutil.NoSuchProcess:
                    continue
        tree_collected = True
    except psutil.NoSuchProcess:
        pass
    except psutil.Error:
        clean = False
    finally:
        # Observed descendants remain owned even after an intermediate exits.
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                clean = False
        try:
            if root is not None and tree_collected:
                root.kill()
            else:
                process.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.Error:
            process.kill()
            clean = False
        process.join(timeout=1)
    try:
        _, alive = psutil.wait_procs(children, timeout=1)
        for child in alive:
            try:
                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    return False
            except psutil.NoSuchProcess:
                pass
    except psutil.Error:
        return False
    return clean and tree_collected and not process.is_alive()


def _ignore_missing_cleanup_entry(_function, _path, error):
    if not isinstance(error[1], FileNotFoundError):
        raise error[1]


def _caller_business_db_url() -> str:
    """URL of the caller's customer session. Empty when it cannot be read."""
    from sqlalchemy.exc import SQLAlchemyError

    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        from app.application.customer_app_service import get_customers_session

        session = get_customers_session()
    except RECOVERABLE_ERRORS:
        return ""
    try:
        bind = session.get_bind()
        return str(bind.url.render_as_string(hide_password=False) or "")
    except RECOVERABLE_ERRORS + (SQLAlchemyError, AttributeError):
        return ""
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


def _bind_worker_business_db(url: str, *, bind_workflow_db: bool = False) -> bool:
    """Restore customer, sales and reporting sessions against the caller's database."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
            poolclass=NullPool,
        )
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        def open_session():
            return factory()

        @contextmanager
        def sessions():
            with factory.begin() as db:
                yield db

        import app.application.customer_app_service as customers
        import app.application.sales_app_service as sales
        import app.domain.shared_services.report_service as reports

        customers.get_customers_session = open_session
        sales.get_db = sessions
        reports.get_db = sessions
        if bind_workflow_db:
            import app.db.session as db_session

            db_session.SessionLocal = factory
    except RECOVERABLE_ERRORS + (SQLAlchemyError,):
        return False
    return True


def _worker_acknowledged(
    control, process, marker: bytes, deadline: float, *, renew=None, memory_guard=None
) -> tuple[bool, bool]:
    """Wake on an acknowledgement or worker exit without reaping the process."""
    sentinel = process.sentinel
    while True:
        if memory_guard is not None:
            memory_guard.check()
        remaining = max(0, deadline - time.monotonic())
        readable = wait(
            (control, sentinel),
            timeout=min(remaining, _RESOURCE_POLL_SECONDS) if memory_guard else remaining,
        )
        if not readable and memory_guard and time.monotonic() < deadline:
            continue
        exited = sentinel in readable
        # A receipt can already be buffered when the sentinel becomes readable.
        if control not in readable and not (exited and control.poll()):
            return False, exited
        try:
            frame = control.recv_bytes(1)
        except EOFError:
            # The child's control endpoint can close just before its sentinel fires.
            while not exited and time.monotonic() < deadline:
                if memory_guard is not None:
                    memory_guard.check()
                remaining = max(0, deadline - time.monotonic())
                exited = bool(wait((sentinel,), timeout=min(remaining, _RESOURCE_POLL_SECONDS)))
            return False, exited
        if frame == marker:
            if memory_guard is not None:
                memory_guard.check()
            return True, exited
        deadline = renew(frame) if renew is not None else 0.0
        if not deadline:
            return False, exited


def execute_isolated(executor, step, context, deadline: float) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_timeouts import (
        ELT_FILE_WATCHDOG_SECONDS,
        uses_elt_file_deadlines,
    )
    from app.infrastructure.chat_stream_lifetime import current_lifetime
    from app.infrastructure.llm.client import capture_worker_llm_scope, record_worker_route_metadata

    try:
        payload = json.dumps(
            {
                "step": step.to_dict(),
                "context": context,
                "business_db_url": _caller_business_db_url(),
            },
            allow_nan=False,
        )
    except (ValueError, TypeError):
        return {
            "success": False,
            "error_code": "tool_context_not_serializable",
            "retryable": False,
        }
    if getattr(executor, "_tool_cleanup_failed", False):
        return {"success": False, "error_code": "tool_cleanup_unresolved", "retryable": False}
    if not _process_namespace_matches():
        return {
            "success": False,
            "error_code": "tool_process_namespace_unverified",
            "retryable": False,
        }
    from app.application.agent_orchestrator.business_write_guard import (
        capture_elt_worker_claim,
        capture_worker_claim,
    )
    from app.application.agent_orchestrator.catalog_product_worker import (
        capture_catalog_worker_profile,
    )

    catalog_profile = capture_catalog_worker_profile(step)
    catalog_claim = capture_worker_claim() if catalog_profile is not None else None
    elt_claim = capture_elt_worker_claim(step, context)
    surface_claim = capture_worker_claim() if step.tool_id in {"browser", "aiopen"} else None
    memory_limit = (
        _limit_from_env("XCAGI_TOOL_MEMORY_MB", 2048) * 1024 * 1024
        if step.tool_id == "browser" and _sandbox_enabled()
        else None
    )
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    control_in, control_out = ctx.Pipe(duplex=False)
    lifetime = current_lifetime.get()
    receiver, sender = ctx.Pipe(duplex=False) if lifetime is not None else (None, None)
    drained, failed, stopped = (threading.Event() for _ in range(3))
    relay = None
    folder = tempfile.mkdtemp(prefix="xcagi-tool-")
    llm_scope = capture_worker_llm_scope(context)
    process = ctx.Process(
        target=_worker,
        args=(
            type(executor),
            payload,
            folder,
            control_out,
            start,
            deadline,
            llm_scope,
            catalog_profile,
            catalog_claim,
            sender,
            elt_claim,
            surface_claim,
            memory_limit is not None,
        ),
    )
    armed = False
    early_exit = False
    clean = True
    result = {}
    resource_error = None
    supervisor = _WorkerProcessSupervisor(process, memory_limit_bytes=memory_limit)

    def renew_file_deadline(marker: bytes) -> float:
        nonlocal deadline
        if (seconds := ELT_FILE_WATCHDOG_SECONDS.get(marker)) is None:
            return 0.0
        deadline = time.monotonic() + seconds
        return deadline

    file_deadlines = uses_elt_file_deadlines(step.tool_id, step.action, step.params or {})
    try:
        supervisor.start()
        control_out.close()
        if sender is not None and lifetime is not None:
            sender.close()  # Only the spawned child may keep the write endpoint alive.
            lifetime.worker_started()
            relay = threading.Thread(
                target=copy_context().run,
                args=(_relay_stream, receiver, lifetime, drained, failed, stopped),
                daemon=True,
                name="tool-stream-relay",
            )
            try:
                relay.start()
            except RuntimeError:
                relay = None
                lifetime.worker_finished()
                raise
        ready, exited = supervisor.wait_ack(control_in, b"r", deadline)
        if ready and not exited and time.monotonic() < deadline:
            supervisor.check()
            supervisor.release(start)
            armed = True
            done, exited = supervisor.wait_ack(
                control_in,
                b"d",
                deadline,
                renew=renew_file_deadline if file_deadlines else None,
            )
            early_exit = not done and exited and time.monotonic() < deadline
            if done:
                result = json.loads(Path(folder, "result").read_text(encoding="utf-8"))
                if (
                    relay is not None and not supervisor.wait_event(drained, deadline)
                ) or failed.is_set():
                    result["output"] = {
                        "outcome": "unknown",
                        "error_code": "tool_stream_receipt_failed",
                        "retryable": False,
                        "reconciliation_evidence": result["output"],
                    }
                supervisor.check()
    except _WorkerResourceError as exc:
        resource_error = {
            "success": False,
            "error_code": exc.code,
            "outcome": "unknown" if armed else "not_started",
            "execution_status": "unknown" if armed else "not_started",
            "retryable": False,
            "reconciliation_required": armed,
            "memory_limit_bytes": exc.limit_bytes,
            "observed_rss_bytes": exc.rss_bytes,
        }
    except (OSError, RuntimeError, ValueError) as exc:
        logging.getLogger(__name__).warning("tool worker boundary failed: %s", type(exc).__name__)
    finally:
        stopped.set()
        control_in.close()
        control_out.close()
        if sender is not None:
            sender.close()
        if receiver is not None and relay is None:
            receiver.close()
        supervisor.close()
        clean = supervisor.clean
        if clean:
            try:
                shutil.rmtree(folder, onerror=_ignore_missing_cleanup_entry)
            except OSError:
                clean = False
        if not clean:
            executor._tool_cleanup_failed = True
    if result:
        record_worker_route_metadata(result.get("llm_route_metadata"), llm_scope)
    if not clean and not early_exit:
        return {"outcome": "unknown", "error_code": "tool_cleanup_failed", "retryable": False}
    if resource_error is not None:
        return resource_error
    if result:
        from app.application.tool_execution_deadline import invocation_deadline

        with invocation_deadline(deadline) as budget:
            budget.uncertain.extend(result["uncertain"])
        return cast(dict[str, Any], result["output"])
    if not armed:
        return {"success": False, "error_code": "tool_worker_not_started", "retryable": False}
    if elt_claim is not None and early_exit and clean:
        from app.application.agent_orchestrator.elt_checkpoint_recovery import (
            EltCheckpointWorkerExited,
        )
        from app.domain.task_lifecycle.machine import DEFAULT_MAX_ATTEMPTS

        if elt_claim[2] < DEFAULT_MAX_ATTEMPTS:
            raise EltCheckpointWorkerExited
    return {
        "outcome": "unknown",
        "error_code": "tool_worker_exited" if early_exit else "tool_worker_incomplete",
        "retryable": False,
        **({"cleanup_unresolved": True} if not clean else {}),
    }
