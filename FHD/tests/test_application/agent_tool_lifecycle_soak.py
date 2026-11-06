"""AP08 soak: continuous register, update, and discovery. Not a pytest module."""

from __future__ import annotations

import json
import os
import time
import tracemalloc
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.application import agent_tool_lifecycle as service
from app.application.agent_tool_lifecycle import Actor
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS

SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {"name": {"type": "string"}, "note": {"type": "string", "default": "n"}},
}


def _rss_kb() -> int:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        return 0
    return 0


def main() -> None:
    seconds = float(os.environ.get("AP08_SECONDS", "3600"))
    out = Path(os.environ.get("AP08_OUT", "/opt/cursor/artifacts/ap08-soak.jsonl"))
    db = Path(os.environ.get("AP08_DB", "/tmp/ap08-agent-tools.sqlite3"))
    out.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    service.reset_for_tests(str(db))
    actor = Actor("soak-admin", "admin", None, 1)
    employee = Actor("soak-emp", "employee", "soak-emp", 1)
    tracemalloc.start()
    started = time.time()
    rss0 = _rss_kb()
    ops = 0
    errors = 0
    last_report = started
    tool_id = ""
    version = 0
    with tenant_scope(1):
        service.register_principal(actor, {"principal_id": "soak-emp", "role": "employee"})
        while time.time() - started < seconds:
            try:
                if not tool_id or ops % 25 == 0:
                    created = service.create_tool(
                        actor,
                        {
                            "tool_key": f"soak_{ops}",
                            "name": "soak",
                            "description": "soak tool",
                            "input_schema": SCHEMA,
                        },
                    )
                    published = service.publish_tool(actor, created["id"], {"scope": "tenant"})
                    tool_id = published["id"]
                    version = int(published["version_no"])
                else:
                    updated = service.update_tool(
                        actor,
                        tool_id,
                        {"expected_version": version, "description": f"soak {ops}"},
                    )
                    version = int(updated["version_no"])
                service.discovery(employee)
                ops += 1
            except BOUNDARY_ERRORS as exc:
                errors += 1
                ops += 1
                tool_id = ""
                if errors < 5 or errors % 100 == 0:
                    _append(
                        out, {"event": "error", "error": f"{type(exc).__name__}: {exc}", "ops": ops}
                    )
            now = time.time()
            if now - last_report >= 30:
                current, peak = tracemalloc.get_traced_memory()
                _append(
                    out,
                    {
                        "at_shanghai": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
                        "elapsed_seconds": round(now - started, 1),
                        "ops": ops,
                        "errors": errors,
                        "rss_kb": _rss_kb(),
                        "rss_start_kb": rss0,
                        "tracemalloc_current": current,
                        "tracemalloc_peak": peak,
                        "db_bytes": db.stat().st_size if db.exists() else 0,
                    },
                )
                last_report = now
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.time() - started
    _append(
        out,
        {
            "event": "finished",
            "at_shanghai": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            "elapsed_seconds": round(elapsed, 1),
            "ops": ops,
            "errors": errors,
            "rss_kb": _rss_kb(),
            "rss_start_kb": rss0,
            "tracemalloc_current": current,
            "tracemalloc_peak": peak,
            "passed_hour": elapsed >= 3600 and errors == 0,
        },
    )


def _append(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
