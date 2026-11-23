"""Bounded supervision of ETL workers; EltRun remains the durable task authority."""

from __future__ import annotations

import logging
import multiprocessing
import os
import time
from contextlib import nullcontext
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.engine import make_url

from app.application.elt.errors import EltConflict, EltError
from app.application.elt.operation_owner import (
    OperationOwner,
    claim_operation,
    fail_operation,
    freeze_background_operation,
)
from app.application.elt.service_support import (
    EXECUTOR_WORKERS,
    SUBMITTED,
    SUBMITTED_LOCK,
    dump_json,
    load_json,
)
from app.db.models.elt import EltRun
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)


@dataclass
class BackgroundJob:
    owner: OperationOwner
    kind: str
    database_url: str = field(repr=False)
    options: dict[str, Any] = field(default_factory=dict, repr=False)
    host_database_url: str = field(default="", repr=False)
    llm_scope: dict[str, Any] | None = field(default=None, repr=False)
    model_session_id: str | None = field(default=None, repr=False)
    active_mod_id: str = ""


# Only resource accounting, never a second queue or a source of execution rights.
_ADMITTED: dict[str, BackgroundJob] = {}


def _limit(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.environ.get(name) or default)))
    except ValueError:
        return default


def _admit(job: BackgroundJob) -> None:
    total = _limit("ELT_MAX_IN_FLIGHT", EXECUTOR_WORKERS, 2, EXECUTOR_WORKERS)
    per_tenant = _limit("ELT_TENANT_MAX_IN_FLIGHT", min(4, total - 1), 1, total - 1)
    reserved = _limit("ELT_EXECUTION_RESERVED", max(1, total // 4), 1, total - 1)
    with SUBMITTED_LOCK:
        active = tuple(_ADMITTED.values())
        if (
            job.owner.run_id in _ADMITTED
            or len(active) >= total
            or sum(item.owner.tenant_id == job.owner.tenant_id for item in active) >= per_tenant
            or (
                job.kind != "execute"
                and sum(item.kind != "execute" for item in active) >= total - reserved
            )
        ):
            raise EltError(
                "ELT_BACKGROUND_NOT_STARTED",
                "后台处理容量已满，任务未开始，请稍后重试",
                status_code=503,
            )
        _ADMITTED[job.owner.run_id] = job
        SUBMITTED.add(job.owner.run_id)


def _release(job: BackgroundJob) -> None:
    with SUBMITTED_LOCK:
        # An old completion callback must never release a replacement's slot.
        if _ADMITTED.get(job.owner.run_id) is job:
            del _ADMITTED[job.owner.run_id]
            SUBMITTED.discard(job.owner.run_id)


def _failure(job: BackgroundJob, session_factory, *, started: bool, clean: bool) -> None:
    with tenant_scope(job.owner.tenant_id), session_factory() as db:
        run = (
            db.query(EltRun)
            .filter_by(
                id=job.owner.run_id,
                tenant_id=job.owner.tenant_id,
                owner_user_id=job.owner.owner_user_id,
                operation_token=job.owner.token,
            )
            .one_or_none()
        )
        if run is None or run.status == "outcome_unknown":
            return  # A durable terminal transaction is stronger than a lost process receipt.
        unknown = (started and job.kind == "execute") or not clean
        fail_operation(
            db,
            replace(job.owner, kind=run.operation_kind or job.owner.kind),
            code="ELT_BACKGROUND_INTERRUPTED" if started else "ELT_BACKGROUND_NOT_STARTED",
            message="后台处理已中断，请重新预演" if started else "后台任务未开始，请稍后重试",
            outcome_unknown=unknown,
            not_started=not started and clean,
        )


def submit_background(
    service,
    *,
    kind: str,
    run_id: str,
    tenant_id: int,
    owner_user_id: int,
    operation_token: str | None,
    options: dict[str, Any] | None,
    executor,
    session_factory,
) -> None:
    """Freeze the existing DB token before bounded, nonblocking admission."""
    with SUBMITTED_LOCK:
        existing = _ADMITTED.get(run_id)
        if (
            existing is not None
            and existing.owner.tenant_id == tenant_id
            and existing.owner.owner_user_id == owner_user_id
            and (operation_token is None or operation_token == existing.owner.token)
        ):
            return
    queued_kind = "execute_queue" if kind == "execute" else "preview_queue"
    allowed_statuses = {
        "execute": {"executing"},
        "revalidate": {"previewing", "preview_ready"},
        "preview": {"queued", "previewing"},
    }[kind]
    with tenant_scope(tenant_id), session_factory() as db:
        run = service._owned_run(db, run_id, owner_user_id)
        if run.tenant_id != tenant_id:
            raise EltConflict("ELT_RUN_BUSY", "任务所属企业已改变")
        owner = (
            OperationOwner(run_id, owner_user_id, tenant_id, queued_kind, operation_token)
            if operation_token is not None
            else claim_operation(
                db,
                run,
                queued_kind,
                allowed_statuses=allowed_statuses,
                require_unrolled_back=True,
            )
        )
        owner = freeze_background_operation(db, owner)
        database_url = db.get_bind().url.render_as_string(hide_password=False)
        db.commit()
    job = BackgroundJob(owner, kind, database_url)
    try:
        _admit(job)
        parsed = make_url(database_url)
        if parsed.get_backend_name() == "sqlite" and parsed.database in {None, "", ":memory:"}:
            raise EltError("ELT_BACKGROUND_NOT_STARTED", "后台处理需要可由工作进程访问的持久数据库")
        from app.application.elt_login_authorization import current_model_session_id
        from app.db import HostSessionLocal
        from app.infrastructure.llm.client import capture_worker_llm_scope
        from app.request_active_mod_ctx import get_request_active_mod_id

        with HostSessionLocal() as host_db:
            job.host_database_url = host_db.get_bind().url.render_as_string(hide_password=False)
        job.options = load_json(dump_json(options or {}), {})
        job.llm_scope = capture_worker_llm_scope({"local_user_id": owner_user_id})
        job.model_session_id = current_model_session_id(owner_user_id)
        job.active_mod_id = get_request_active_mod_id()
        future = executor.submit(copy_context().run, _supervise, job, session_factory)
        # Executor shutdown(cancel_futures=True) must not leave a frozen queued run.
        future.add_done_callback(
            lambda done: _cancelled(job, session_factory) if done.cancelled() else None
        )
    except BOUNDARY_ERRORS:
        try:
            _failure(job, session_factory, started=False, clean=True)
        finally:
            _release(job)
        raise


def _cancelled(job: BackgroundJob, session_factory) -> None:
    try:
        _failure(job, session_factory, started=False, clean=True)
    finally:
        _release(job)


def _supervise(job: BackgroundJob, session_factory) -> None:
    supervisor = None
    reader = writer = None
    started = False
    clean = True
    try:
        from app.application.agent_orchestrator.tool_process import (
            _OwnedWorker,
            _process_namespace_matches,
            _WorkerProcessSupervisor,
        )
        from app.application.elt.service import EltService

        if not _process_namespace_matches():
            raise RuntimeError("worker process identities cannot be verified")
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        reader, writer = context.Pipe(duplex=False)
        deadline = time.monotonic() + _limit("ELT_BACKGROUND_TIMEOUT_SECONDS", 900, 1, 3600)
        process = _OwnedWorker(
            context, _worker, EltService, (job, writer, start, deadline), (writer,)
        )
        supervisor = _WorkerProcessSupervisor(
            process,
            memory_limit_bytes=_limit("ELT_WORKER_MEMORY_MB", 2048, 128, 8192) * 1024 * 1024,
        )
        supervisor.start()
        writer.close()
        ready, exited = (
            supervisor.wait_ack(reader, b"r", deadline)
            if process.wait_ready(deadline, check=supervisor.check)
            else (False, False)
        )
        if ready and not exited and time.monotonic() < deadline:
            # From this point a lost receipt cannot prove that execution did not start.
            started = True
            supervisor.release(start)
            supervisor.wait_ack(reader, b"d", deadline)
    except BOUNDARY_ERRORS as exc:
        logger.warning(
            "ETL worker supervision interrupted for %s: %s", job.owner.run_id, type(exc).__name__
        )
    finally:
        if supervisor is not None:
            clean = False
            try:
                supervisor.close()
                clean = supervisor.clean
            except BOUNDARY_ERRORS:
                logger.exception("ETL worker cleanup unverified for %s", job.owner.run_id)
        for connection in (reader, writer):
            if connection is not None:
                connection.close()
        try:
            _failure(job, session_factory, started=started, clean=clean)
        except BOUNDARY_ERRORS:
            logger.exception("Unable to persist ETL worker outcome for %s", job.owner.run_id)
        finally:
            if clean:
                _release(job)
            else:
                # Retain the bounded admission; killing only the supervisor is not proof.
                logger.error("ETL worker slot quarantined for %s", job.owner.run_id)


def _worker(service_type, job: BackgroundJob, control, start, deadline: float) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from app import db as runtime_db
    from app.application.agent_orchestrator.tool_process import (
        _bind_worker_business_db,
        _worker_start,
    )
    from app.application.elt import service as service_module
    from app.application.elt_login_authorization import _ModelSession, bind_model_session
    from app.db import session as db_session
    from app.infrastructure.llm.client import llm_client_factory_scope, restore_worker_llm_client
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    if not _worker_start(control, start, deadline, monitored_memory=True):
        return
    if not _bind_worker_business_db(job.database_url, bind_workflow_db=True):
        raise RuntimeError("unable to restore the original business database")
    # Restore storage, not authority: each original worker still activates the
    # exact tenant/owner/token and rechecks the approved preview before effects.
    runtime_db.SessionLocal = service_module.SessionLocal = db_session.SessionLocal
    host_engine = create_engine(job.host_database_url, poolclass=NullPool)
    runtime_db.HostSessionLocal = sessionmaker(
        bind=host_engine, autoflush=False, expire_on_commit=False
    )
    model_session = (
        bind_model_session(
            _ModelSession(job.model_session_id, job.owner.tenant_id, job.owner.owner_user_id)
        )
        if job.model_session_id is not None
        else nullcontext()
    )
    mod_token = set_request_active_mod_id(job.active_mod_id)
    try:
        with (
            tenant_scope(job.owner.tenant_id),
            model_session,
            llm_client_factory_scope(lambda: restore_worker_llm_client(job.llm_scope))
            if job.llm_scope is not None
            else nullcontext(),
        ):
            service = service_type()
            _dispatch(service, job)
        control.send_bytes(b"d")
    finally:
        reset_request_active_mod_id(mod_token)
        host_engine.dispose()
        control.close()


def _dispatch(service, job: BackgroundJob) -> None:
    args = (job.owner.run_id, job.owner.owner_user_id)
    if job.kind == "execute":
        service._execute_worker(
            *args,
            bool(job.options.get("valid_rows_only")),
            operation_token=job.owner.token,
            owned_background=True,
        )
    elif job.kind == "revalidate":
        service._revalidation_worker(
            *args, job.options.get("overrides"), operation_token=job.owner.token
        )
    elif job.kind == "preview":
        service._preview_worker(*args, operation_token=job.owner.token)
    else:
        raise ValueError("unknown ETL background operation")
