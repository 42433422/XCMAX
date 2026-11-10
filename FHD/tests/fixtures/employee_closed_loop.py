"""Isolated business database, evidence, and strict employee acceptance judgments."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import BrokenBarrierError
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.models.customer import Customer
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.utils.operational_errors import RECOVERABLE_ERRORS

_SH = ZoneInfo("Asia/Shanghai")


_HISTORY = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evidence"
    / "e2e"
    / "ai-employee-closed-loop-20261106"
    / "acceptance.json"
)


_ITEMS = [f"E{index:02d}" for index in range(1, 31)]


_SESSION_ERRORS = RECOVERABLE_ERRORS + (SQLAlchemyError,)


_PROTECTED_RETESTS = frozenset(
    {
        "ai-employee-closed-loop-retest-202611062130",
        "ai-employee-closed-loop-retest-20261106214643",
        "ai-employee-closed-loop-retest-20261106220105",
        "ai-employee-closed-loop-retest-202611062206",
        "ai-employee-closed-loop-retest-202611062226",
    }
)


def _now() -> str:
    return datetime.now(_SH).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _session_factory(engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @contextmanager
    def sessions():
        db = factory()
        try:
            yield db
            db.commit()
        except _SESSION_ERRORS:
            db.rollback()
            raise
        finally:
            db.close()

    def open_session():
        return factory()

    return sessions, open_session


def _bind(monkeypatch, engine):
    sessions, open_session = _session_factory(engine)
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", open_session)
    monkeypatch.setattr("app.application.sales_app_service.get_db", sessions)
    return sessions


def _read_all(engine, model):
    with Session(engine) as db:
        return list(
            db.execute(select(model).execution_options(skip_tenant_filter=True)).scalars().all()
        )


def _units(engine) -> list[dict]:
    with Session(engine) as db:
        rows = list(
            db.execute(
                select(PurchaseUnit)
                .execution_options(skip_tenant_filter=True)
                .order_by(PurchaseUnit.id)
            ).scalars()
        )
        return [
            {
                "id": row.id,
                "customer_name": row.unit_name,
                "contact_person": row.contact_person or "",
                "contact_phone": row.contact_phone or "",
                "contact_address": row.address or "",
                "tenant_id": row.tenant_id,
                "is_active": bool(row.is_active),
            }
            for row in rows
        ]


def _orders(engine) -> list[dict]:
    with Session(engine) as db:
        rows = list(
            db.execute(
                select(SalesOrder)
                .execution_options(skip_tenant_filter=True)
                .order_by(SalesOrder.id)
            ).scalars()
        )
        return [
            {
                "id": row.id,
                "customer_id": row.customer_id,
                "status": row.status,
                "tenant_id": row.tenant_id,
                "total_amount": float(row.total_amount or 0),
            }
            for row in rows
        ]


class Acceptance:
    def __init__(self, engine, tmp: Path) -> None:
        self.engine = engine
        self.tmp = tmp
        self.executor = AgentToolExecutor()
        self.actor_context: dict = {}
        self.chain: list[dict] = []
        self.items: dict[str, dict] = {}
        self.evidence_path: Path | None = None

    def context(self, task_id: str, **extra) -> dict:
        body = {
            **self.actor_context,
            "tenant_id": "11",
            "user_id": "11",
            "employee_id": "employee-a",
            "task_id": task_id,
        }
        body.update(extra)
        return body

    def call(self, tool_id: str, action: str, params: dict, context: dict) -> dict:
        before_units = _units(self.engine)
        before_orders = _orders(self.engine)
        step = AgentStep(
            node_id=f"{tool_id}-{action}", tool_id=tool_id, action=action, params=params
        )
        result = self.executor.execute(step, runtime_context=context)
        after_units = _units(self.engine)
        after_orders = _orders(self.engine)
        artifact = ""
        file_path = ""
        if isinstance(result, dict):
            file_path = str(result.get("file_path") or "")
            nested = result.get("data")
            if not file_path and isinstance(nested, dict):
                file_path = str(nested.get("file_path") or "")
        if file_path and Path(file_path).is_file():
            artifact = _sha256(Path(file_path))
        self.chain.append(
            {
                "at": _now(),
                "task_id": str(context.get("task_id") or ""),
                "parent_task_id": str(context.get("parent_task_id") or ""),
                "child_task_id": str(context.get("child_task_id") or ""),
                "tool_call_id": step.step_id,
                "employee_id": str(context.get("employee_id") or ""),
                "tool_id": tool_id,
                "tool_version": "2",
                "action": action,
                "tenant_id": str(context.get("tenant_id") or ""),
                "idempotency_key": str(
                    params.get("idempotency_key") or context.get("idempotency_key") or ""
                ),
                "approval_id": str(context.get("approval_id") or ""),
                "request": params,
                "response": result,
                "execution_status": (
                    result.get("execution_status")
                    or result.get("outcome")
                    or ("succeeded" if result.get("success") is True else "failed")
                ),
                "database_before": {"customers": before_units, "orders": before_orders},
                "database_after": {"customers": after_units, "orders": after_orders},
                "artifact_hash": artifact,
                "audit_log": result.get("audit") if isinstance(result, dict) else None,
            }
        )
        return result

    def settle(self, item: str, verdict: str, summary: str, **proof) -> None:
        self.items[item] = {"id": item, "verdict": verdict, "summary": summary, **proof}


def _seed_order(engine, **kwargs) -> int:
    with Session(engine) as db:
        row = SalesOrder(
            order_no=kwargs["order_no"],
            customer_id=kwargs["customer_id"],
            customer_name=kwargs.get("customer_name") or "",
            state=kwargs.get("state") or "confirmed",
            status=kwargs.get("status") or "confirmed",
            invoice_status="not_invoiced",
            payment_state=kwargs.get("payment_state") or "unpaid",
            total_amount=kwargs.get("total_amount") or 10,
            paid_amount=0,
            currency="CNY",
            tenant_id=kwargs.get("tenant_id"),
            created_at=kwargs.get("created_at") or datetime.now(),
        )
        db.add(row)
        db.commit()
        return int(
            db.execute(
                select(SalesOrder.id)
                .where(SalesOrder.order_no == kwargs["order_no"])
                .execution_options(skip_tenant_filter=True)
            ).scalar_one()
        )


def _seed_sales_customer(engine, customer_id: int, name: str, address: str, tenant_id: int) -> None:
    with Session(engine) as db:
        db.add(
            Customer(
                id=customer_id,
                customer_name=name,
                contact_address=address,
                tenant_id=tenant_id,
            )
        )
        db.commit()


def _retest_evidence_path() -> Path:
    stamp = datetime.now(_SH).strftime("%Y%m%d%H%M%S")
    path = _HISTORY.parents[1] / f"ai-employee-closed-loop-retest-{stamp}" / "acceptance.json"
    if path.parent.name in _PROTECTED_RETESTS or path.exists():
        raise RuntimeError("refusing to overwrite an existing retest evidence file")
    return path


def judge_async_export(entries: list[dict], *, phases: set[str], file_ready: bool) -> str:
    """A synchronous file is not an async completed export."""
    async_entries = [str(item.get("name") or "") for item in entries if item.get("async") is True]
    if not async_entries:
        return "NOT-IMPLEMENTED"
    if {"queued", "running", "completed"} <= phases and file_ready:
        return "PASS"
    return "FAIL"


def judge_tool_timeout(
    *,
    process_started: bool,
    process_exited: bool,
    resources_released: bool,
    task_state: str,
) -> str:
    """A deadline that expires before the tool process is running is not a pass."""
    if not process_started or not process_exited or not resources_released:
        return "FAIL"
    if task_state not in {"timed_out", "timeout"}:
        return "FAIL"
    return "PASS"


def judge_cancel(
    *,
    task_id: str,
    task_state: str,
    db_row: dict | None,
    receipt_customer_id: object,
) -> str:
    """Verification is the cancelled task id plus an independent row id, not a name search."""
    if not str(task_id or "").strip() or task_state != "cancelled":
        return "FAIL"
    if not isinstance(db_row, dict) or type(db_row.get("id")) is not int:
        return "FAIL"
    if type(receipt_customer_id) is not int or receipt_customer_id != db_row["id"]:
        return "FAIL"
    return "PASS"


def judge_restart(
    *,
    repository_kind: str,
    restored_state: str | None,
    tool_status: str | None,
    replayed: bool,
) -> str:
    """A fresh in-memory queue is not scheduler restore. Restore must not replay."""
    if repository_kind != "sql":
        return "FAIL"
    if restored_state not in {"running", "recovering"}:
        return "FAIL"
    if tool_status not in {"running", "recovering"}:
        return "FAIL"
    if replayed:
        return "FAIL"
    return "PASS"


def resolve_retry_task_id(*, invoked: str, scope_key: str) -> str:
    parts = scope_key.split(":")
    recorded = parts[1] if len(parts) >= 5 else ""
    if recorded:
        return recorded
    return invoked


def _grade(items: dict[str, dict]) -> dict:
    passed = [key for key in _ITEMS if items.get(key, {}).get("verdict") == "PASS"]
    special = len(passed) == 30
    level = "L0"
    if items.get("E01", {}).get("verdict") == "PASS":
        level = "L1"
    if level == "L1" and all(
        items.get(key, {}).get("verdict") == "PASS" for key in ("E09", "E10", "E25")
    ):
        level = "L2"
    if special:
        level = "L3"
    return {
        "grade": level,
        "special_acceptance": "PASS" if special else "FAIL",
        "passed": len(passed),
        "total": 30,
    }


def _bind_worker(db_path: str, idem_path: str):
    os.environ["XCAGI_TOOL_IDEMPOTENCY_PATH"] = idem_path
    os.environ["PYTEST_CURRENT_TEST"] = ""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def open_session():
        return factory()

    import app.application.customer_app_service as customers

    customers.get_customers_session = open_session
    return engine


def _e23_worker(db_path: str, idem_path: str, key: str) -> None:
    _bind_worker(db_path, idem_path)
    from app.application.agent_orchestrator import tool_permission as worker_permissions
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    worker_permissions.drop_process_idempotency_memory()

    def finish_and_die(_claim_key: str, _output: dict) -> None:
        os._exit(23)

    worker_permissions.finish_idempotent_replay = finish_and_die
    AgentToolExecutor().execute(
        AgentStep(
            node_id="e23",
            tool_id="customers",
            action="create",
            params={
                "unit_name": "闭环丢失回执客户",
                "idempotency_key": key,
                "contact_phone": "13800000023",
            },
        ),
        runtime_context={
            "tenant_id": "11",
            "user_id": "11",
            "task_id": "e23",
            "employee_id": "employee-a",
            "idempotency_key": key,
        },
    )


def _e24_worker(db_path: str, idem_path: str, key: str) -> None:
    _bind_worker(db_path, idem_path)
    from app.application.agent_orchestrator import tool_permission as worker_permissions
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    worker_permissions.drop_process_idempotency_memory()

    def die_before_commit(*_args, **_kwargs):
        os._exit(24)

    import app.application.customer_app_service as customers

    customers.CustomerApplicationService.create = die_before_commit
    AgentToolExecutor().execute(
        AgentStep(
            node_id="e24",
            tool_id="customers",
            action="create",
            params={"unit_name": "闭环提交前崩溃", "idempotency_key": key},
        ),
        runtime_context={
            "tenant_id": "11",
            "user_id": "11",
            "task_id": "e24",
            "employee_id": "employee-a",
            "idempotency_key": key,
        },
    )


def _e21_worker(db_path: str, idem_path: str, key: str, name: str, sender) -> None:
    from app.application.agent_orchestrator import tool_permission as worker_permissions
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    _bind_worker(db_path, idem_path)
    worker_permissions.drop_process_idempotency_memory()
    result = AgentToolExecutor().execute(
        AgentStep(
            node_id="e21",
            tool_id="customers",
            action="create",
            params={
                "unit_name": name,
                "idempotency_key": key,
                "contact_phone": "13900000021",
            },
        ),
        runtime_context={
            "tenant_id": "11",
            "user_id": "11",
            "task_id": "e21",
            "employee_id": "employee-a",
            "idempotency_key": key,
        },
    )
    sender.send(
        {
            "success": result.get("success"),
            "error_code": result.get("error_code"),
            "pid": os.getpid(),
        }
    )
    sender.close()


def _e22_worker(
    db_path: str, idem_path: str, unit_id: int, phone: str, key: str, barrier, sender
) -> None:
    from app.application.agent_orchestrator import tool_permission as worker_permissions
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    try:
        engine = _bind_worker(db_path, idem_path)
        worker_permissions.drop_process_idempotency_memory()
        seen = _customer_version(engine, unit_id)
        barrier.wait(timeout=30)
        result = AgentToolExecutor().execute(
            AgentStep(
                node_id=key,
                tool_id="customers",
                action="update",
                params={
                    "id": unit_id,
                    "contact_phone": phone,
                    "idempotency_key": key,
                    "expected_version": seen,
                },
            ),
            runtime_context={
                "tenant_id": "11",
                "user_id": "11",
                "task_id": key,
                "employee_id": "employee-a",
                "idempotency_key": key,
            },
        )
        sender.send(
            {
                "success": result.get("success"),
                "error_code": result.get("error_code"),
                "pid": os.getpid(),
                "version": seen,
            }
        )
    except BrokenBarrierError:
        sender.send({"success": False, "error_code": "barrier_broken", "pid": os.getpid()})
    finally:
        sender.close()


class ClosedLoopRun:
    """One engine, temp directory, and idempotency file for the whole module."""

    def __init__(self) -> None:
        self.closed = False
        self.book: Acceptance | None = None
        self.engine = None
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._restore: list[tuple[object, str, object]] = []
        self._env: dict[str, str | None] = {}

    def open_resources(self) -> Acceptance:
        if self.closed:
            raise RuntimeError("closed-loop live run used after fixture teardown")
        tmp = tempfile.TemporaryDirectory(prefix="closed-loop-")
        self._tmpdir = tmp
        root = Path(tmp.name)
        self._setenv("XCAGI_DATA_DIR", str(root))
        self._setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(root / "idempotency.sqlite"))
        self._setenv("AUDIT_LOG_PATH", str(root / "audit.jsonl"))
        self._setenv("SECRET_KEY", "closed-loop-acceptance-secret-32bytes")
        self._setenv("XCAGI_PRODUCT_SKU", "enterprise")
        permissions.clear_idempotent_replay_for_tests()
        engine = create_engine(
            f"sqlite:///{root / 'business.sqlite'}",
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=StaticPool,
        )
        self.engine = engine
        import app.db as host_db
        import app.db.session as db_session
        from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
        from tests.fixtures.employee_test_identity import seed_employee_identity

        factory = seed_employee_identity(
            engine, session_id="employee-acceptance-session", username="employee-acceptance"
        )
        self._patch(host_db, "HostSessionLocal", factory)
        self._patch(db_session, "SessionLocal", factory)
        self._setenv("DATABASE_URL", str(engine.url))
        binding = bind_agent_actor_scope(session_id="employee-acceptance-session", user_id="11")
        sessions, open_session = _session_factory(engine)
        import app.application.customer_app_service as customers
        import app.application.sales_app_service as sales
        import app.utils.path_io.path_utils as path_utils

        self._patch(customers, "get_customers_session", open_session)
        self._patch(sales, "get_db", sessions)
        self._patch(path_utils, "get_data_dir", lambda: str(root / "data"))
        self.book = Acceptance(engine, root)
        self.book.actor_context = {"actor_id": "11", "_actor_authorization": binding}
        return self.book

    def require(self) -> Acceptance:
        if self.closed or self.book is None or self.engine is None:
            raise RuntimeError("closed-loop live run used after fixture teardown")
        return self.book

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        permissions.clear_idempotent_replay_for_tests()
        for obj, name, old in reversed(self._restore):
            setattr(obj, name, old)
        for key, old in self._env.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        if self.engine is not None:
            self.engine.dispose()
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None

    def _setenv(self, key: str, value: str) -> None:
        self._env[key] = os.environ.get(key)
        os.environ[key] = value

    def _patch(self, obj: object, name: str, value: object) -> None:
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)


def _idempotency_scope(path: Path, expected: str, client_key: str) -> str:
    if not path.is_file():
        return ""
    conn = sqlite3.connect(path)
    try:
        exact = conn.execute(
            "select scope_key from tool_idempotency where scope_key = ?",
            (expected,),
        ).fetchone()
        if exact is not None:
            return str(exact[0])
        found = conn.execute(
            "select scope_key from tool_idempotency where scope_key like ?",
            (f"%:customers:create:{client_key}",),
        ).fetchall()
        if len(found) == 1:
            return str(found[0][0])
        return ""
    except sqlite3.Error:
        return ""
    finally:
        conn.close()


def _customer_version(engine, unit_id: int) -> int:
    with Session(engine) as db:
        value = db.execute(
            select(PurchaseUnit.version)
            .where(PurchaseUnit.id == unit_id)
            .execution_options(skip_tenant_filter=True)
        ).scalar_one()
    return int(value)


def _customer_row(engine, name: str) -> dict | None:
    with Session(engine) as db:
        row = db.execute(
            select(PurchaseUnit)
            .where(PurchaseUnit.unit_name == name, PurchaseUnit.tenant_id == 11)
            .execution_options(skip_tenant_filter=True)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"id": int(row.id), "customer_name": row.unit_name}


def _note_runtime(loop: Acceptance, result: dict, *, task_id: str, action: str) -> None:
    handoff = result.get("handoff") if isinstance(result.get("handoff"), dict) else {}
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    children = task.get("child_task_ids") if isinstance(task.get("child_task_ids"), list) else []
    loop.chain.append(
        {
            "at": _now(),
            "task_id": task_id,
            "parent_task_id": str(task.get("parent_task_id") or ""),
            "child_task_id": str(children[-1]) if children else "",
            "tool_call_id": str(handoff.get("handoff_id") or ""),
            "employee_id": str(handoff.get("target_employee") or ""),
            "tool_id": action,
            "tool_version": "",
            "action": action,
            "tenant_id": str(task.get("tenant_id") or ""),
            "idempotency_key": str(handoff.get("idempotency_key") or ""),
            "approval_id": "",
            "request": {"action": action},
            "response": {
                "success": result.get("success"),
                "business_success": result.get("business_success"),
                "error_code": result.get("error_code") or handoff.get("error_code") or "",
            },
            "execution_status": str(handoff.get("status") or result.get("error_code") or ""),
            "database_before": {},
            "database_after": {},
            "artifact_hash": "",
            "audit_log": None,
        }
    )
