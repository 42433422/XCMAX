from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.task_models import AgentTask, task_from_run
from app.application.agent_orchestrator.task_progress import task_progress_snapshot


def _step(name: str, status: str) -> AgentStep:
    return AgentStep(
        node_id=name,
        tool_id="customers",
        action="query",
        description=f"步骤 {name}",
        status=status,  # type: ignore[arg-type]
    )


def test_progress_is_derived_from_durable_steps_and_current_stage() -> None:
    run = AgentRun(
        user_id="owner",
        message="统一进度",
        status="running",
        steps=[_step("one", "completed"), _step("two", "running"), _step("three", "pending")],
    )
    run.metadata["task_context"] = {"attempt": 2}

    progress = task_progress_snapshot(run)

    assert progress == {
        "percent": 33,
        "completed_units": 1,
        "settled_units": 1,
        "total_units": 3,
        "current_unit": 2,
        "stage": "执行中",
        "detail": "步骤 two",
        "status": "running",
        "attempt": 2,
        "indeterminate": False,
        "basis": "steps",
        "updated_at": run.updated_at,
    }


def test_progress_preserves_control_stage_and_never_marks_cancelled_as_complete() -> None:
    run = AgentRun(
        user_id="owner",
        message="取消任务",
        status="cancelled",
        steps=[_step("one", "completed"), _step("two", "skipped")],
    )
    run.metadata["control_request"] = {"action": "cancel", "status": "requested"}

    progress = task_progress_snapshot(run)

    assert progress["percent"] == 99
    assert progress["completed_units"] == 1
    assert progress["settled_units"] == 2
    assert progress["stage"] == "正在请求取消"


def test_completed_and_legacy_tasks_have_complete_progress_contract() -> None:
    completed = AgentRun(user_id="owner", message="完成", status="completed")
    completed_progress = task_progress_snapshot(completed)
    assert completed_progress["percent"] == 100
    assert completed_progress["basis"] == "status"
    assert completed_progress["indeterminate"] is False

    legacy = AgentTask(task_id="legacy", user_id="owner", title="旧任务", status="running")
    legacy_progress = legacy.to_dict()["progress"]
    assert legacy_progress["percent"] == 0
    assert legacy_progress["stage"] == "执行中"
    assert legacy_progress["indeterminate"] is True

    inconsistent = AgentRun(
        user_id="owner",
        message="历史不一致任务",
        status="completed",
        steps=[_step("one", "completed"), _step("two", "running")],
    )
    assert task_progress_snapshot(inconsistent)["percent"] == 50


def test_task_from_run_persists_progress_for_lightweight_stream_snapshots() -> None:
    run = AgentRun(
        user_id="owner",
        message="流式进度",
        status="running",
        steps=[_step("one", "completed"), _step("two", "pending")],
    )
    run.metadata["task_context"] = {"task_id": "task-progress", "attempt": 1}

    task = task_from_run(run)

    assert task.metadata["progress"]["percent"] == 50
    assert task.to_dict()["progress"]["detail"] == "步骤 two"


@pytest.fixture
def elt_progress_engine():
    from app.db.db_base import Base
    from app.db.models.elt import EltRun, EltTemplate, EltTemplateVersion, EltUpload

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[model.__table__ for model in (EltUpload, EltTemplate, EltTemplateVersion, EltRun)],
    )
    yield engine
    engine.dispose()


@pytest.mark.parametrize("child_status", ["previewing", "executing"])
def test_durable_file_progress_reads_only_exact_owned_file_and_companion_slots(
    monkeypatch,
    child_status,
    elt_progress_engine,
):
    from app import db
    from app.application.elt.service_support import dump_json
    from app.db.models.elt import EltRun, EltUpload
    from app.domain.shared_services.tools_workflow_elt import durable_elt_checkpoint_ids
    from app.infrastructure.auth.agent_principal import AgentPrincipal
    from app.request_active_mod_ctx import get_request_active_mod_id

    paths = [str(UUID(int=i)) for i in range(1, 4)]
    step = AgentStep(
        node_id="elt",
        tool_id="elt_import",
        action="execute",
        status="running",
        params={"file_paths": paths},
    )
    run = AgentRun(user_id="2", message="导入", status="running", steps=[step])
    run.metadata.update(
        runtime_context={"tenant_id": 3, "_mod_authorization": {"mod_id": "coating-industry"}},
        plan={"metadata": {"durable_elt_batch": True}},
    )
    slots = durable_elt_checkpoint_ids(run.run_id, step.step_id, paths)
    engine = elt_progress_engine
    factory = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    completed_id, active_id = slots[paths[0]], slots[paths[1]]
    upload_defaults = {
        "tenant_id": 3,
        "suffix": ".xlsx",
        "size_bytes": 1,
        "sha256": "source",
        "storage_path": "",
    }
    row_defaults = {"owner_user_id": 2, "tenant_id": 3, "file_sha256": "source"}
    receipt = {"run_id": completed_id, "target_type": "products", "executed_rows": 3}
    with factory.begin() as tx:
        tx.add_all(
            [
                EltUpload(**upload_defaults, id=paths[0], owner_user_id=2, file_name="完成.xlsx"),
                EltUpload(**upload_defaults, id=paths[1], owner_user_id=2, file_name="附表.xlsx"),
                EltUpload(
                    **upload_defaults,
                    id=paths[2],
                    owner_user_id=99,
                    file_name="另一个账号的文件.xlsx",
                ),
            ]
        )
        tx.flush()
        tx.add_all(
            [
                EltRun(
                    **row_defaults,
                    id=completed_id,
                    upload_id=paths[0],
                    target_type="products",
                    status="completed",
                    executed_rows=3,
                    confirmed_at=now,
                    executed_at=now,
                    receipt_json=dump_json(receipt),
                ),
                EltRun(
                    **row_defaults,
                    id=active_id,
                    upload_id=paths[1],
                    target_type="shipment_records",
                    status="preview_ready",
                    summary_json=dump_json(
                        {"linked_customer_products_preview": {"run_id": "companion"}}
                    ),
                ),
                EltRun(
                    **row_defaults,
                    id="companion",
                    upload_id=paths[1],
                    target_type="customer_products",
                    status=child_status,
                    stage="parsing" if child_status == "previewing" else "persisting",
                    confirmed_at=now if child_status == "executing" else None,
                    operation_lease_until=now
                    + timedelta(seconds=30 if child_status == "previewing" else -30),
                    summary_json=dump_json({"linked_from_shipment_preview": active_id}),
                ),
            ]
        )

    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def scoped_session():
        assert get_request_active_mod_id() == "coating-industry"
        return factory()

    event.listen(engine, "before_cursor_execute", capture)
    monkeypatch.setattr(db, "SessionLocal", scoped_session)
    viewer = AgentPrincipal(
        user_id="2", tenant_id="3", mod_authorization={"mod_id": "coating-industry"}
    )
    progress = task_progress_snapshot(run, viewer=viewer)
    assert progress["basis"] == "files" and progress["percent"] == 33
    assert progress["current_unit"] == 2 and progress["completed_units"] == 1
    first, second, third = progress["files"]
    assert first["name"] == "完成.xlsx" and first["executed_rows"] == 3
    assert second["status"] == ("previewing" if child_status == "previewing" else "unknown")
    assert (
        second["companion"]["run_id"] == "companion"
        and second["primary"]["status"] == "preview_ready"
    )
    assert third["name"] == "附件 3" and third["status"] == "pending"
    assert get_request_active_mod_id() == ""
    assert statements and all(statement.lstrip().startswith("SELECT") for statement in statements)
    reads = len(statements)
    assert task_progress_snapshot(run)["basis"] == "steps"
    for wrong in (
        replace(viewer, user_id="99"),
        replace(viewer, tenant_id="4"),
        replace(viewer, mod_authorization=None),
    ):
        assert "files" not in task_progress_snapshot(run, viewer=wrong)
    assert len(statements) == reads


@pytest.mark.parametrize("with_continuation", [False, True])
def test_legacy_blocked_import_shows_only_original_native_receipts(
    monkeypatch, elt_progress_engine, with_continuation
):
    from app import db
    from app.application.agent_orchestrator import run_repository
    from app.application.elt.service_support import dump_json
    from app.db.models.elt import EltRun, EltUpload
    from app.domain.shared_services.tools_workflow_elt import durable_elt_checkpoint_ids
    from app.infrastructure.auth.agent_principal import AgentPrincipal

    names = [f"文件{i}.xlsx" for i in range(1, 23)]
    upload_ids = [str(UUID(int=i)) for i in range(1, 23)]
    step = AgentStep(
        node_id="elt",
        tool_id="elt_import",
        action="execute",
        status="failed",
        params={"file_paths": names},
        output={
            "error_code": "tool_worker_exited",
            "outcome": "unknown",
            "reconciliation_required": True,
        },
    )
    run = AgentRun(user_id="2", message="导入", status="blocked", steps=[step])
    run.metadata["runtime_context"] = {
        "tenant_id": 3,
        "_mod_authorization": {"mod_id": "coating-industry"},
        "turn_id": "turn-legacy",
        "conversation_id": "conversation-legacy",
    }
    origin = {
        "run_id": run.run_id,
        "step_id": step.step_id,
        "turn_id": "turn-legacy",
        "conversation_id": "conversation-legacy",
        "mod_id": "coating-industry",
    }
    factory = sessionmaker(bind=elt_progress_engine)
    now = datetime.now(UTC)

    def receipt_row(run_id, upload_id, target, rows, summary):
        receipt = {"run_id": run_id, "target_type": target, "executed_rows": rows}
        return EltRun(
            id=run_id,
            owner_user_id=2,
            tenant_id=3,
            upload_id=upload_id,
            target_type=target,
            file_sha256="sha",
            status="completed",
            stage="completed",
            executed_rows=rows,
            confirmed_at=now,
            executed_at=now,
            summary_json=dump_json(summary),
            receipt_json=dump_json(receipt),
        )

    with factory.begin() as tx:
        tx.add_all(
            EltUpload(
                id=upload_ids[i],
                owner_user_id=2,
                tenant_id=3,
                file_name=name,
                suffix=".xlsx",
                size_bytes=1,
                sha256="sha",
                storage_path="",
            )
            for i, name in enumerate(names)
        )
        tx.flush()
        tx.add(receipt_row("first", upload_ids[0], "abnormal", 0, {"chat_import_origin": origin}))
        for i in range(1, 13):
            parent, child = f"parent{i}", f"child{i}"
            tx.add(
                receipt_row(
                    parent,
                    upload_ids[i],
                    "shipment_records",
                    4 if i == 1 else 5,
                    {
                        "chat_import_origin": origin,
                        "linked_customer_products_preview": {"run_id": child},
                    },
                )
            )
            tx.add(
                receipt_row(
                    child,
                    upload_ids[i],
                    "customer_products",
                    5 if i == 1 else 7,
                    {"linked_from_shipment_preview": parent},
                )
            )
        if not with_continuation:
            for i, field in enumerate(origin, start=13):
                tx.add(
                    receipt_row(
                        f"wrong{i}",
                        upload_ids[i],
                        "products",
                        40,
                        {"chat_import_origin": {**origin, field: "other"}},
                    )
                )
            unverified = receipt_row(
                "unverified", upload_ids[18], "products", 40, {"chat_import_origin": origin}
            )
            unverified.receipt_json = "{}"
            tx.add(unverified)

    monkeypatch.setattr(db, "SessionLocal", factory)
    viewer = AgentPrincipal(
        user_id="2", tenant_id="3", mod_authorization={"mod_id": "coating-industry"}
    )
    progress = task_progress_snapshot(run, viewer=viewer)
    assert (progress["completed_units"], progress["total_units"], progress["executed_rows"]) == (
        13,
        22,
        141,
    )
    assert progress["stage"] == "结果待核对" and progress["status"] == "blocked"
    assert progress["detail"] == "13/22 份已完成 · 已确认写入 141 行"
    assert progress["percent"] == 59 and progress["current_unit"] == 14
    assert all(file["status"] == "unknown" for file in progress["files"][13:])
    assert progress["files"][13]["stage"] == "unverified"

    if not with_continuation:
        return
    repo = run_repository.InMemoryAgentRunRepository()
    repo.save(run)
    monkeypatch.setattr(run_repository, "get_agent_run_repository", lambda: repo)
    tail_ids = upload_ids[13:]
    tail_step = AgentStep(
        node_id="import_remaining",
        tool_id="elt_import",
        action="execute",
        status="running",
        params={"file_paths": tail_ids},
    )
    continuation = AgentRun(
        user_id="2",
        message="继续",
        status="running",
        steps=[tail_step],
        plan_id=f"continue-{run.run_id}",
    )
    continuation.metadata.update(
        runtime_context={**run.metadata["runtime_context"], "turn_id": "tail-turn"},
        task_context={
            "task_id": run.run_id,
            "root_run_id": run.run_id,
            "parent_run_id": run.run_id,
            "conversation_id": "conversation-legacy",
            "attempt": 2,
        },
        plan={
            "metadata": {
                "durable_elt_batch": True,
                "legacy_elt_tail_recheck": True,
                "source": "elt_batch_continuation",
                "continued_from_run_id": run.run_id,
            }
        },
    )
    before = task_progress_snapshot(continuation, viewer=viewer)
    assert (before["completed_units"], before["total_units"], before["executed_rows"]) == (
        13,
        22,
        141,
    )
    assert before["files"][13]["status"] == "pending"

    checkpoint = durable_elt_checkpoint_ids(continuation.run_id, tail_step.step_id, tail_ids)[
        tail_ids[0]
    ]
    with factory.begin() as tx:
        tx.add(receipt_row(checkpoint, tail_ids[0], "products", 4, {}))
    after = task_progress_snapshot(continuation, viewer=viewer)
    assert (after["completed_units"], after["total_units"], after["executed_rows"]) == (14, 22, 145)
    assert after["current_unit"] == 15
    assert [file["name"] for file in after["files"]] == names

    continuation.metadata["task_context"]["parent_run_id"] = "other"
    unlinked = task_progress_snapshot(continuation, viewer=viewer)
    assert (unlinked["completed_units"], unlinked["total_units"], unlinked["executed_rows"]) == (
        1,
        9,
        4,
    )
