"""release_train 四段进位与 installer/major 判定。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate


def test_parse_quad_and_bump_daily_boundaries() -> None:
    from modstore_server.release_train import bump_daily, bump_quad, parse_quad

    assert parse_quad("1.0.0.0") == (1, 0, 0, 0)
    assert bump_quad("1.0.0.9") == "1.0.1.0"
    assert bump_quad("1.0.9.9") == "1.1.0.0"

    after, kind = bump_daily("1.0.0.9", day_index=9)
    assert after == "1.0.1.0"
    assert kind == "installer"

    after2, kind2 = bump_daily("1.0.9.9", day_index=99)
    assert after2 == "1.1.0.0"
    assert kind2 == "major"


def test_is_installer_and_major_day() -> None:
    from modstore_server.release_train import (
        decennial_generation,
        decennial_generation_label,
        is_installer_day,
        is_major_day,
        next_decennial_anchor,
    )

    assert not is_installer_day("1.0.0.0", day_index=0)
    assert is_installer_day("1.0.1.0", day_index=10)
    assert not is_major_day(99)
    assert is_major_day(100)
    assert is_major_day(200)
    assert decennial_generation("1.0.0.0") == 1
    assert decennial_generation("1.0.0.9") == 1
    assert decennial_generation("1.0.1.0") == 2
    assert decennial_generation("1.0.2.0") == 3
    assert decennial_generation_label("1.0.1.0") == "G2"
    assert next_decennial_anchor("1.0.0.5") == "1.0.1.0"
    assert next_decennial_anchor("1.0.1.0") == "1.0.2.0"


def test_bump_release_train_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server.release_train import bump_release_train, load_state

    ssot = tmp_path / "release_train.json"
    ssot.write_text(
        json.dumps(
            {
                "epoch": "1.0.0.0",
                "current": "1.0.0.0",
                "started_at": "2026-06-04",
                "day_index": 0,
                "last_bump_at": None,
                "last_installer_push_at": None,
                "last_major_push_at": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_REQUIRE_TIMELINE_CLOSURE", "0")

    out = bump_release_train(digest_day="2026-06-04")
    assert out["ok"] is True
    assert out["before"] == "1.0.0.0"
    assert out["after"] == "1.0.0.1"
    assert out["kind"] == "daily"

    st = load_state(path=ssot)
    assert st["current"] == "1.0.0.1"
    assert st["day_index"] == 1


def test_bump_requires_timeline_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modstore_server.release_train import bump_release_train, load_state
    from modstore_server.time_rail_runtime import record_node_run

    ssot = tmp_path / "release_train.json"
    ssot.write_text(
        json.dumps({"epoch": "1.0.0.0", "current": "1.0.0.0", "day_index": 0}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_REQUIRE_TIMELINE_CLOSURE", "1")
    monkeypatch.setenv("MODSTORE_TIME_RAIL_RUNTIME_JSON", str(tmp_path / "nodes.json"))

    blocked = bump_release_train(digest_day="2026-06-04")
    assert blocked["skipped"] is True
    assert blocked["reason"] == "timeline_not_closed"
    assert load_state(path=ssot)["current"] == "1.0.0.0"

    from modstore_server.release_train_merged import TIMELINE_NODES

    for node_id in TIMELINE_NODES:
        record_node_run(
            node_id,
            ok=True,
            source="test",
            meta={"last_run": "2026-06-04T00:30:00+00:00"},
        )
    runtime = tmp_path / "nodes.json"
    doc = json.loads(runtime.read_text(encoding="utf-8"))
    for row in doc["nodes"].values():
        row["last_run"] = "2026-06-04T00:30:00+00:00"
    runtime.write_text(json.dumps(doc), encoding="utf-8")

    out = bump_release_train(digest_day="2026-06-04")
    assert out["skipped"] is False
    assert out["after"] == "1.0.0.1"


def test_bump_installer_day_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server.release_train import bump_release_train

    ssot = tmp_path / "release_train.json"
    ssot.write_text(
        json.dumps(
            {
                "epoch": "1.0.0.0",
                "current": "1.0.0.9",
                "started_at": "2026-06-04",
                "day_index": 9,
                "last_bump_at": None,
                "last_installer_push_at": None,
                "last_major_push_at": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_REQUIRE_TIMELINE_CLOSURE", "0")

    out = bump_release_train()
    assert out["after"] == "1.0.1.0"
    assert out["kind"] == "installer"
    assert out["push_installer"] is True
