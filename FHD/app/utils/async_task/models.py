"""Data models and environment defaults for asynchronous task execution."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

DEFAULT_TASK_TIMEOUT = int(os.environ.get("XCAGI_TASK_DEFAULT_TIMEOUT", "300"))
MAX_RETRIES = int(os.environ.get("XCAGI_TASK_MAX_RETRIES", "3"))
RETRY_DELAY = int(os.environ.get("XCAGI_TASK_RETRY_DELAY", "5"))


class TaskStatus(str, Enum):
    """Task lifecycle state."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRYING = "retrying"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """Observable result and progress for one task execution."""

    task_id: str
    status: TaskStatus
    result: Any | None = None
    error: str | None = None
    progress: int = 0
    total: int | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    retries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0

    @property
    def is_success(self) -> bool:
        return self.status == TaskStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        return self.status in (TaskStatus.FAILURE, TaskStatus.TIMEOUT)


@dataclass
class AsyncTaskConfig:
    """Task registration and retry configuration."""

    name: str
    queue: str = "normal"
    timeout: int = DEFAULT_TASK_TIMEOUT
    max_retries: int = MAX_RETRIES
    retry_delay: int = RETRY_DELAY
    soft_time_limit: int = 240
    priority: int = 5
    cache_result: bool = True
    cache_ttl: int = 3600
    on_success: Callable | None = None
    on_failure: Callable | None = None
    on_progress: Callable[[int, int], None] | None = None


def register_default_tasks(manager: Any) -> None:
    """Register the built-in desktop task queues and timeout policies."""
    default_tasks = [
        AsyncTaskConfig(name="shipment_tasks.generate_shipment_order", queue="urgent", timeout=120),
        AsyncTaskConfig(
            name="shipment_tasks.export_shipment_records_task", queue="normal", timeout=300
        ),
        AsyncTaskConfig(
            name="shipment_tasks.import_products_batch_task", queue="normal", timeout=600
        ),
        AsyncTaskConfig(name="wechat_tasks.scan_wechat_messages", queue="wechat", timeout=60),
        AsyncTaskConfig(name="kitten_report.generate_report", queue="heavy", timeout=900),
    ]
    for config in default_tasks:
        manager.register_task(config)
