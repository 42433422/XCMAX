"""In-memory :class:`SandboxDriver` for tests.

The real subprocess / Docker / cloud drivers all spawn external
processes, which makes them clumsy to drive from tests that just want
to verify that *the calling code* did the right thing. ``MockDriver``
records every job it receives and returns whatever you scripted, so
unit tests can assert on flow without paying spawn-startup costs.

Two configuration knobs:

- ``response`` — a static :class:`SandboxResult` returned for every job.
- ``handler`` — a callable ``(job, policy) -> SandboxResult`` that takes
  precedence over ``response`` when set. Useful when the test needs to
  branch on the job's command / function name.

Convenience helpers:

- :meth:`assert_called_with_command` — fail the test if no recorded job
  matches a given prefix.
- :meth:`reset` — clear the call log between scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .driver import SandboxJob, SandboxPolicy, SandboxResult

JobHandler = Callable[[SandboxJob, SandboxPolicy], SandboxResult]


@dataclass(slots=True)
class _CallRecord:
    job: SandboxJob
    policy: SandboxPolicy


@dataclass
class MockSandboxDriver:
    """In-memory driver that returns scripted results."""

    response: SandboxResult = field(
        default_factory=lambda: SandboxResult(success=True, driver="mock")
    )
    handler: JobHandler | None = None
    available: bool = True
    name: str = "mock"
    calls: list[_CallRecord] = field(default_factory=list)

    def is_available(self) -> bool:
        return bool(self.available)

    def execute(
        self,
        job: SandboxJob,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult:
        pol = policy or SandboxPolicy()
        self.calls.append(_CallRecord(job=job, policy=pol))
        if self.handler is not None:
            res = self.handler(job, pol)
        else:
            res = SandboxResult(**self.response.to_dict())
        # Force the driver name field so consumers don't have to set it
        # in every scripted response.
        res.driver = self.name
        return res

    # ----------------------------------------------------------------- assertions

    def assert_called_with_command(self, *prefix: str) -> None:
        for record in self.calls:
            if record.job.kind != "command":
                continue
            if list(record.job.command)[: len(prefix)] == list(prefix):
                return
        commands = [list(c.job.command) for c in self.calls if c.job.kind == "command"]
        raise AssertionError(
            f"no recorded command starts with {list(prefix)}; saw {commands}"
        )

    def assert_called_with_function(self, function_name: str) -> None:
        for record in self.calls:
            if record.job.kind == "function" and record.job.function_name == function_name:
                return
        raise AssertionError(
            f"no recorded function call to {function_name!r}; "
            f"saw {[c.job.function_name for c in self.calls if c.job.kind == 'function']}"
        )

    def reset(self) -> None:
        self.calls.clear()

    # ----------------------------------------------------------------- factories

    @classmethod
    def passing(cls, *, stdout: str = "", stderr: str = "", output: dict[str, Any] | None = None) -> "MockSandboxDriver":
        return cls(
            response=SandboxResult(
                success=True,
                driver="mock",
                stdout=stdout,
                stderr=stderr,
                output=dict(output or {}),
                exit_code=0,
            )
        )

    @classmethod
    def failing(cls, *, stderr: str = "boom", exit_code: int = 1) -> "MockSandboxDriver":
        return cls(
            response=SandboxResult(
                success=False,
                driver="mock",
                stderr=stderr,
                exit_code=exit_code,
                error_type="MockFailure",
                error_message=stderr,
            )
        )


__all__ = ["JobHandler", "MockSandboxDriver"]
