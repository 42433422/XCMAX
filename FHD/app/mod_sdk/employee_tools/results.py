"""Shared employee tool result envelopes."""

from __future__ import annotations

from typing import Any

from .ports import Payload


def _ok(summary: str, **extra: Any) -> Payload:
    out: Payload = {"ok": True, "summary": summary[:4000]}
    out.update(extra)
    return out


def _err(error: str, **extra: Any) -> Payload:
    out: Payload = {"ok": False, "error": error[:1000]}
    out.update(extra)
    return out


def _command_result(
    label: str, result: Payload, *, stdout_limit: int | None = None, stderr_limit: int | None = None
) -> Payload:
    stdout, stderr = result["stdout"], result["stderr"]
    return _ok(
        f"{label} exit={result['returncode']}",
        returncode=result["returncode"],
        stdout=stdout if stdout_limit is None else stdout[-stdout_limit:],
        stderr=stderr if stderr_limit is None else stderr[-stderr_limit:],
        passed=result["ok"],
    )
