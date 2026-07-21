from __future__ import annotations

import json
from pathlib import Path

from modstore_server.public_company_hall import (
    DEPARTMENT_ORDER,
    build_public_company_hall,
    write_public_company_hall,
)


def test_build_company_hall_has_six_departments_and_presence_model(monkeypatch):
    monkeypatch.setenv("MODSTORE_ACTION_ITEMS_KEEP_LOW_SIGNAL", "1")
    from sqlalchemy import text

    from modstore_server.digest_action_items import ensure_table, parse_and_store_action_items
    from modstore_server.models import get_engine

    ensure_table()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM daily_action_items"))

    parse_and_store_action_items(
        day="2026-07-22",
        record_id=9201,
        patches_markdown="""
## [task-router-officer] 任务派发员 · v1
- **P0** 修复公开公司大厅状态投影：工作中须来自真实行动条目
""",
        updates_markdown="",
        rt_version="1.0.0.0",
    )
    hall = build_public_company_hall(day="2026-07-22")
    assert hall["schema"] == "xcagi.public_company_hall/v1"
    assert len(hall["departments"]) == 6
    assert [d["id"] for d in hall["departments"]] == list(DEPARTMENT_ORDER)
    assert hall["counts"]["roster"] >= 40
    assert hall["counts"]["working"] + hall["counts"]["alert"] + hall["counts"]["idle"] == hall[
        "counts"
    ]["roster"]
    # at least the patch owner should be working or alert (P0)
    workers = [e for e in hall["employees"] if e["employee_id"] == "task-router-officer"]
    assert workers
    assert workers[0]["presence"] in {"working", "alert"}
    assert "presence_model" in hall
    assert isinstance(hall.get("feed"), list)


def test_write_public_company_hall(tmp_path, monkeypatch):
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path))
    corp = tmp_path / "成都修茈科技有限公司"
    corp.mkdir(parents=True)
    out = write_public_company_hall(day=None)
    assert out["ok"] is True
    target = corp / "download-company-hall.json"
    assert target.is_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema"] == "xcagi.public_company_hall/v1"
