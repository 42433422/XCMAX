"""release_train orchestrator 骨架冒烟。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import modstore_server.models as models

pytestmark = pytest.mark.release_gate


def test_orchestrator_installer_day_plan(tmp_path: Path, monkeypatch) -> None:
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "orch.sqlite"))
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(tmp_path / "rt.json"))
    monkeypatch.setenv("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE", "shadow")
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_REQUIRE_PHASE_A", "0")
    models.init_db()

    from modstore_server.daily_release_train_orchestrator_job import (
        run_daily_release_train_orchestrator_job,
    )
    from modstore_server.models import DailyDigestRecord, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        row = DailyDigestRecord(
            day="2026-06-04",
            subject="test",
            release_train_before="1.0.0.9",
            release_train_after="1.0.1.0",
            release_kind="installer",
        )
        session.add(row)
        session.commit()
        rid = int(row.id)

    (tmp_path / "rt.json").write_text(
        json.dumps({"current": "1.0.1.0", "day_index": 10}), encoding="utf-8"
    )

    out = run_daily_release_train_orchestrator_job(record_id=rid)
    assert out["ok"] is True
    assert out["release_kind"] == "installer"
    assert out["push_installer"] is True
    assert out["installer_plan"]["steps"]
    assert out.get("phase_b", {}).get("lines") == ["P-W", "S-R"]
    assert out.get("phase_c", {}).get("employee_chain")
    assert out.get("phase_c_pipeline", {}).get("planned_steps")

    with sf() as session:
        row2 = session.get(DailyDigestRecord, rid)
        meta = json.loads(row2.vibe_prep_meta_json or "{}")
    audit = meta.get("orchestrator_audit") or {}
    assert audit.get("orchestrator_mode") == "shadow"
    assert audit.get("shadow") is True

    models._engine = None
    models._SessionFactory = None
