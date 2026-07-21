from __future__ import annotations

import json
from pathlib import Path

from modstore_server.public_action_board import (
    _clean_public_text,
    build_public_action_board,
    build_trajectory,
    write_public_action_board,
)


def test_clean_public_text_strips_paths_and_priority():
    raw = "**P0** 修复 `FHD/app/foo.py` 标题契约"
    out = _clean_public_text(raw)
    assert "P0" not in out
    assert "FHD/" not in out
    assert "修复" in out


def test_build_public_board_has_no_internal_fields(monkeypatch):
    monkeypatch.setenv("MODSTORE_ACTION_ITEMS_KEEP_LOW_SIGNAL", "1")
    from sqlalchemy import text

    from modstore_server.digest_action_items import ensure_table, parse_and_store_action_items
    from modstore_server.models import get_engine

    ensure_table()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM daily_action_items"))

    parse_and_store_action_items(
        day="2026-07-21",
        record_id=9101,
        patches_markdown="""
## [worker-a] Worker A · v1
- scope：`FHD/secret/path.py`
- **P0** 修复公开看板脱敏回归：不得泄露路径
""",
        updates_markdown="""
## [worker-a] Worker A · v1
- **P1** 推进官网工作目标公开只读展示
""",
        rt_version="1.0.0.0",
    )
    board = build_public_action_board(day="2026-07-21")
    blob = json.dumps(board, ensure_ascii=False)
    assert "scope_path" not in blob
    assert "employee_id" not in blob
    assert "FHD/" not in blob
    assert board["readonly"] is True
    assert board["breakpoints"]["summary"]["total"] >= 1
    assert board["goals"]["summary"]["total"] >= 1
    assert all("title" in it for it in board["breakpoints"]["items"])
    traj = board.get("trajectory") or []
    assert len(traj) >= 1
    assert all("ts" in x and "text" in x and "href" in x for x in traj)


def test_build_trajectory_empty_when_no_items():
    traj = build_trajectory([], [])
    assert traj == []


def test_write_public_action_board_corp_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path))
    corp = tmp_path / "成都修茈科技有限公司"
    corp.mkdir(parents=True)
    out = write_public_action_board(day=None)
    assert out["ok"] is True
    target = corp / "download-action-board.json"
    assert target.is_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema"] == "xcagi.public_action_board/v1"
    assert isinstance(data.get("trajectory"), list)
