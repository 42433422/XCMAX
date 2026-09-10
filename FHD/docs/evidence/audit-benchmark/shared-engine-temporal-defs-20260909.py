# Temporal 基准被测定义（workflow/activity 放独立可导入模块，满足 sandbox 重导入要求）
import asyncio

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from datetime import timedelta

TASK_QUEUE = "r22-tq"
side_effects: list = []
attempts = {"activity": 0}


@activity.defn
async def compose(a: str, b: str) -> str:
    return a + "|" + b


@activity.defn
async def flaky(x: int) -> int:
    attempts["activity"] += 1
    if attempts["activity"] < 3:
        raise RuntimeError("transient")
    side_effects.append(x)
    return x * 2


@workflow.defn
class EngineWorkflow:
    def __init__(self):
        self._done: list = []

    @workflow.run
    async def run(self, words: list) -> list:
        for w in words:
            r = await workflow.execute_activity(
                compose, args=[w, "X"], start_to_close_timeout=timedelta(seconds=10)
            )
            self._done.append(r)
        return self._done

    @workflow.query
    def progress(self) -> list:
        return list(self._done)


@workflow.defn
class RetryWorkflow:
    @workflow.run
    async def run(self, x: int) -> int:
        return await workflow.execute_activity(
            flaky, x, start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                maximum_attempts=5,
                initial_interval=timedelta(milliseconds=100),
                backoff_coefficient=1.0,
            ),
        )
