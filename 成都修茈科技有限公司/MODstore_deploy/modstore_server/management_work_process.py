"""Isolated child entrypoint for one management-employee runtime call."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def _write_response(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 2:
        return 64
    request_path = Path(args[0])
    response_path = Path(args[1])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
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
        _write_response(response_path, {"ok": True, "result": result})
        return 0
    except BaseException as exc:  # noqa: BLE001 - child must always report failure
        _write_response(
            response_path,
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:4000],
                "traceback": traceback.format_exc(limit=30)[-12_000:],
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
