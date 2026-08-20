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

    from modstore_server.digest_action_items import (
        ensure_table,
        parse_and_store_action_items,
    )
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
    assert "FHD/" not in blob
    assert board["readonly"] is True
    assert board["breakpoints"]["summary"]["total"] >= 1
    assert board["goals"]["summary"]["total"] >= 1
    assert all("title" in it for it in board["breakpoints"]["items"])
    # 岗位 employee_id 可公开（用于公司大厅映射），但仍禁止路径类内部字段
    assert all(it.get("employee_id") for it in board["breakpoints"]["items"])
    traj = board.get("trajectory") or []
    assert len(traj) >= 1
    assert all("ts" in x and "text" in x and "href" in x for x in traj)


def test_build_trajectory_empty_when_no_items():
    traj = build_trajectory([], [])
    assert traj == []


def test_verified_strategic_goal_is_visible_with_loop_linkage(monkeypatch):
    from modstore_server import public_action_board

    monkeypatch.setattr(public_action_board, "_calendar_today", lambda: "2026-07-29")
    monkeypatch.setattr(
        public_action_board,
        "verified_strategic_goal_items",
        lambda limit=100: [
            {
                "title": "实现创始人退出日常运营",
                "priority": "P1",
                "status": "in_progress",
                "status_label": "进行中",
                "line": "P-S",
                "line_label": "软件线",
                "owner": "Para · 变更评审员",
                "employee_id": "change-request-auditor",
                "kind": "update",
                "day": "2026-07-29",
                "updated_at": "2026-07-29T06:00:00+00:00",
                "ts": "06:00",
                "source": "verified_strategic_council",
                "goal_id": "goal-founder-autonomy",
                "loop_run_id": "loop-founder-autonomy",
                "para_task_id": "para-founder-autonomy",
                "receipt_id": "council-founder-autonomy",
            }
        ],
    )

    board = build_public_action_board()

    assert board["day"] == "2026-07-29"
    assert board["day_stale"] is False
    assert board["goals"]["summary"]["total"] >= 1
    goal = next(
        item for item in board["goals"]["items"] if item.get("goal_id") == "goal-founder-autonomy"
    )
    assert goal["loop_run_id"] == "loop-founder-autonomy"
    assert goal["para_task_id"] == "para-founder-autonomy"
    trajectory = next(
        item for item in board["trajectory"] if item.get("goal_id") == "goal-founder-autonomy"
    )
    assert trajectory["source"] == "verified_strategic_council"


def test_write_public_action_board_corp_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path))
    corp = tmp_path / "成都修茈科技有限公司"
    monkeypatch.setenv("MODSTORE_PUBLIC_OUTPUT_ROOT", str(corp))
    corp.mkdir(parents=True)
    out = write_public_action_board(day=None)
    assert out["ok"] is True
    target = corp / "download-action-board.json"
    assert target.is_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema"] == "xcagi.public_action_board/v1"
    assert isinstance(data.get("trajectory"), list)


def test_public_visuals_prefer_live_action_board_api():
    company_root = Path(__file__).resolve().parents[2]
    for name in ("download-action-board.js", "world-will-ticker.js", "world-will.js"):
        script = (company_root / name).read_text(encoding="utf-8")
        assert script.index("fetchBoard('/api/public/action-board'") < script.index(
            "fetchBoard('/download-action-board.json'"
        )
        assert "payload.data" in script
