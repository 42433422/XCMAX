"""Spawn-only tool boundary; never inherit a request transaction or live cookie jar."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import shutil
import tempfile
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import psutil

from app.application.tool_execution_deadline import invocation_deadline
from app.utils.operational_errors import BOUNDARY_ERRORS


def _json_scalar(value):
    # Match API numeric/date encoding; never stringify arbitrary service objects.
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        return int(value) if isinstance(exponent, int) and exponent >= 0 else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError("unsupported tool result value")


def _worker(executor_type, payload, folder, ready, start, done, deadline):
    from app.application.agent_orchestrator.run_models import agent_step_from_dict

    if os.name != "nt":
        os.setsid()
    ready.set()
    if not start.wait(max(0, deadline - time.monotonic())):
        return
    try:
        data = json.loads(payload)
        with invocation_deadline(deadline) as budget:
            output = executor_type().execute(
                agent_step_from_dict(data["step"]), runtime_context=data["context"]
            )
        encoded = json.dumps(
            {"output": output, "uncertain": budget.uncertain},
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
                        "retryable": False,
                    },
                    "uncertain": [],
                }
            ),
            encoding="utf-8",
        )
        done.set()
    finally:
        # Keep ancestry intact until the parent has reaped tool-created children.
        start.clear()
        start.wait()


def _reap(process) -> bool:
    children = []
    try:
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
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        root.kill()
    except psutil.NoSuchProcess:
        pass
    except psutil.Error:
        process.kill()
        return False
    finally:
        process.join(timeout=1)
    _, alive = psutil.wait_procs(children, timeout=1)
    for child in alive:
        try:
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            pass
    return not process.is_alive()


def execute_isolated(executor, step, context, deadline) -> dict[str, Any]:
    try:
        payload = json.dumps({"step": step.to_dict(), "context": context}, allow_nan=False)
    except (ValueError, TypeError):
        return {
            "success": False,
            "error_code": "tool_context_not_serializable",
            "retryable": False,
        }
    if getattr(executor, "_tool_cleanup_failed", False):
        return {"success": False, "error_code": "tool_cleanup_unresolved", "retryable": False}
    ctx = multiprocessing.get_context("spawn")
    ready, start, done = (ctx.Event() for _ in range(3))
    folder = tempfile.mkdtemp(prefix="xcagi-tool-")
    process = ctx.Process(
        target=_worker, args=(type(executor), payload, folder, ready, start, done, deadline)
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
            clean = _reap(process)
            if clean:
                process.close()
        if clean:
            shutil.rmtree(folder)
        else:
            executor._tool_cleanup_failed = True
    if not clean:
        return {"outcome": "unknown", "error_code": "tool_cleanup_failed", "retryable": False}
    if result:
        with invocation_deadline(deadline) as budget:
            budget.uncertain.extend(result["uncertain"])
        return cast(dict[str, Any], result["output"])
    if not armed:
        return {"success": False, "error_code": "tool_worker_not_started", "retryable": False}
    return {"outcome": "unknown", "error_code": "tool_worker_incomplete", "retryable": False}
