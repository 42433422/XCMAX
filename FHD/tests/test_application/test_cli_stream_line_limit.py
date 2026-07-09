"""CLI stream readline limit regression: oversize stream-json lines must not abort SSE."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.application.super_employee_service import TRAE_PROFILE, SuperEmployeeService


@pytest.mark.asyncio
async def test_run_cli_streaming_accepts_oversize_stream_json_line(tmp_path: Path) -> None:
    svc = SuperEmployeeService(TRAE_PROFILE)
    huge = "x" * (100 * 1024)
    script = (
        "import json,sys\n"
        f"print(json.dumps({{'type':'assistant','message':{{'content':[{{'type':'text','text':{huge!r}}}]}}}}, ensure_ascii=False))\n"
        "print(json.dumps({'type':'result','result':'done'}, ensure_ascii=False))\n"
        "sys.stdout.flush()\n"
    )
    py = tmp_path / "emit.py"
    py.write_text(script, encoding="utf-8")

    fake_profile = SimpleNamespace(
        tool_name="trae",
        display_tool="Trae",
        cli_stream_json=True,
        cli_command_builder=lambda *_a, **_k: ["python3", str(py)],
    )
    svc._p = fake_profile  # type: ignore[assignment]

    with (
        patch.object(svc, "_apply_scope_to_cmd", side_effect=lambda cmd: cmd),
        patch.object(svc, "_cli_subprocess_env", return_value=None),
        patch.object(svc, "_cli_idle_timeout_seconds", return_value=30.0),
        patch.object(svc, "_cli_hard_cap_seconds", return_value=60.0),
    ):
        events = []
        async for event in svc._run_cli_streaming("python3", "ping", str(tmp_path)):
            events.append(event)

    assert any(e.get("type") in {"token", "done"} for e in events)
    assert not any(e.get("type") == "error" for e in events)
