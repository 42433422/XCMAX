"""Isolated child entrypoint for one management-employee runtime call."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def _response_stream() -> Any:
    """Reserve original stdout for the protocol and redirect worker output."""

    response_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    return os.fdopen(response_fd, "w", encoding="utf-8", closefd=True)


def _write_response(stream: Any, payload: dict[str, Any]) -> None:
    json.dump(payload, stream, ensure_ascii=False, default=str)
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if args:
        return 64
    response_stream = _response_stream()
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("management execution request must be an object")
        from modstore_server.employee_orchestrator import plan_and_dispatch

        result = plan_and_dispatch(
            str(request.get("task") or ""),
            (request.get("input_data") if isinstance(request.get("input_data"), dict) else {}),
            target_employee_id=str(request.get("target_employee_id") or ""),
            created_by_user_id=int(request.get("created_by_user_id") or 0),
            include_dependencies=bool(request.get("include_dependencies", False)),
            max_concurrency=max(1, min(int(request.get("max_concurrency") or 1), 8)),
            allow_high_risk_real_run=bool(request.get("allow_high_risk_real_run", False)),
        )
        _write_response(response_stream, {"ok": True, "result": result})
        return 0
    except BaseException:  # noqa: BLE001 - child must always report failure
        _write_response(
            response_stream,
            {
                "ok": False,
                "error_code": "management_worker_failed",
            },
        )
        return 1
    finally:
        response_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
