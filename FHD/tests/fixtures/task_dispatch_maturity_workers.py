"""Small spawn target: independent SQL clients without importing HTTP fixtures."""

import time


def native_queue_client(url, options, mode, index, ready, start, results):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.task_execution_models import TaskQueueCapacityError
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )

    engine = create_engine(url, connect_args=options)
    queue = SQLAlchemyTaskExecutionRepository(
        session_factory=sessionmaker(bind=engine),
        auto_create=False,
    )
    ready.put(index)
    if not start.wait(45):
        raise RuntimeError("native admission barrier timed out")
    # PostgreSQL refuses contention before dispatch rather than blocking while
    # the caller might own a different run row. Only that safe refusal retries.
    for _attempt in range(100):
        try:
            if mode.startswith("admit"):
                tenant = "shared" if mode == "admit-tenant" else str(index)
                run = AgentRun(user_id="owner-" + tenant, message=f"admission-{index}")
                run.metadata["runtime_context"] = {"tenant_id": tenant}
                result = queue.enqueue(run)
            else:
                result = queue.claim(f"native-{index}", lease_seconds=120)
            results.put(result.tenant_id if result is not None else None)
            break
        except TaskQueueCapacityError as exc:
            if exc.scope != "coordinator_busy":
                results.put(None)
                break
            time.sleep(0.01)
    else:
        raise RuntimeError("native coordinator stayed busy")
    engine.dispose()
