"""Spawn-only tool boundary; never inherit a request transaction or live cookie jar."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import shutil
import tempfile
import time
from contextlib import contextmanager, nullcontext
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import psutil

from app.utils.operational_errors import BOUNDARY_ERRORS


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


def _worker(
    executor_type,
    payload,
    folder,
    ready,
    start,
    done,
    deadline,
    llm_scope=None,
    catalog_profile=None,
    catalog_claim=None,
):
    from app.application.agent_orchestrator.run_models import agent_step_from_dict
    from app.application.tool_execution_deadline import invocation_deadline
    from app.infrastructure.llm.client import (
        llm_client_factory_scope,
        restore_worker_llm_client,
        scoped_route_metadata,
    )

    if os.name != "nt":
        os.setsid()
    ready.set()
    if not start.wait(max(0, deadline - time.monotonic())):
        return
    route_metadata: dict[str, str | int] = {}
    worker_client: tuple[Any, str] | None = None

    def restore_llm_scope():
        nonlocal worker_client
        if worker_client is None:
            worker_client = restore_worker_llm_client(llm_scope)
        return worker_client

    try:
        data = json.loads(payload)
        business_db_url = str(data.get("business_db_url") or "")
        office_stage = (data["step"].get("tool_id"), data["step"].get("action")) == (
            "excel_import",
            "office_stage",
        )
        if office_stage and not business_db_url:
            raise RuntimeError("office approval database is unavailable")
        if business_db_url and not _bind_worker_business_db(
            business_db_url, bind_workflow_db=office_stage
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
            done.set()
            return
        from app.application.agent_orchestrator.catalog_product_worker import (
            restore_catalog_claim,
            restore_catalog_worker_profile,
        )

        restore_catalog_worker_profile(catalog_profile)
        with (
            restore_catalog_claim(catalog_claim),
            invocation_deadline(deadline) as budget,
            llm_client_factory_scope(restore_llm_scope) if llm_scope is not None else nullcontext(),
        ):
            try:
                output = executor_type().execute(
                    agent_step_from_dict(data["step"]), runtime_context=data["context"]
                )
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
        done.set()
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
                        "exception_hint": (
                            str(exc.args[0])[:120]
                            if exc.args and isinstance(exc.args[0], str)
                            else ""
                        ),
                        "retryable": False,
                    },
                    "uncertain": [],
                    "llm_route_metadata": route_metadata,
                }
            ),
            encoding="utf-8",
        )
        done.set()
    finally:
        # Keep ancestry intact until the parent has reaped tool-created children.
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


def _reap(process) -> bool:
    children = []
    tree_collected = False
    try:
        if not _process_namespace_matches():
            # Only this owned child handle is trustworthy. Its descendants are
            # unverified, so killing it cannot establish successful cleanup.
            process.kill()
            return False
        root = psutil.Process(process.pid)
        root.suspend()
        # Freeze parents before collecting descendants to stop ordinary spawn races.
        for _ in range(2):
            for child in root.children(recursive=True):
                if child not in children:
                    children.append(child)
                    try:
                        child.suspend()
                    except psutil.NoSuchProcess:
                        pass
        tree_collected = True
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        root.kill()
    except psutil.NoSuchProcess:
        if not tree_collected:
            process.kill()
    except psutil.Error:
        process.kill()
        return False
    finally:
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
    return tree_collected and not process.is_alive()


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


def execute_isolated(executor, step, context, deadline) -> dict[str, Any]:
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
    from app.application.agent_orchestrator.business_write_guard import capture_worker_claim
    from app.application.agent_orchestrator.catalog_product_worker import (
        capture_catalog_worker_profile,
    )

    catalog_profile = capture_catalog_worker_profile(step)
    catalog_claim = capture_worker_claim() if catalog_profile is not None else None
    ctx = multiprocessing.get_context("spawn")
    ready, start, done = (ctx.Event() for _ in range(3))
    folder = tempfile.mkdtemp(prefix="xcagi-tool-")
    llm_scope = capture_worker_llm_scope(context)
    process = ctx.Process(
        target=_worker,
        args=(
            type(executor),
            payload,
            folder,
            ready,
            start,
            done,
            deadline,
            llm_scope,
            catalog_profile,
            catalog_claim,
        ),
    )
    armed = False
    clean = True
    result = {}
    try:
        process.start()
        if ready.wait(max(0, deadline - time.monotonic())) and time.monotonic() < deadline:
            armed = True
            start.set()
            if done.wait(max(0, deadline - time.monotonic())):
                result = json.loads(Path(folder, "result").read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError) as exc:
        logging.getLogger(__name__).warning("tool worker boundary failed: %s", type(exc).__name__)
    finally:
        if process.pid is not None:
            try:
                clean = _reap(process)
                if clean:
                    process.close()
            except OSError:
                clean = False
        if clean:
            try:
                shutil.rmtree(folder, onerror=_ignore_missing_cleanup_entry)
            except OSError:
                clean = False
        if not clean:
            executor._tool_cleanup_failed = True
    if result:
        record_worker_route_metadata(result.get("llm_route_metadata"), llm_scope)
    if not clean:
        return {"outcome": "unknown", "error_code": "tool_cleanup_failed", "retryable": False}
    if result:
        from app.application.tool_execution_deadline import invocation_deadline

        with invocation_deadline(deadline) as budget:
            budget.uncertain.extend(result["uncertain"])
        return cast(dict[str, Any], result["output"])
    if not armed:
        return {"success": False, "error_code": "tool_worker_not_started", "retryable": False}
    return {"outcome": "unknown", "error_code": "tool_worker_incomplete", "retryable": False}
