"""Real Excel, SQLite, workflow, employee, and audit evidence for B47–B56."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.db_base import Base
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def acceptance_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'business.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    with factory() as db:
        yield db, tmp_path / "workspace", audit_path
    engine.dispose()


def test_cross_module_business_chain_s01_through_s04(acceptance_db):
    from app.application.agent_orchestrator.cross_module_chain import (
        run_cross_module_acceptance,
    )

    db, workspace, audit_path = acceptance_db
    with tenant_scope(1):
        report = run_cross_module_acceptance(
            db=db,
            workspace=workspace,
            user_id="7",
            tenant_id="1",
            session_id="session-b47",
        )
    evidence_dir = Path("docs/evidence/e2e/cross-module-b47-b56")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "verdict": report["verdict"],
        "scenarios": report["scenarios"],
        "failed": report["failed"],
        "ids": report["ids"],
        "verification": report["verification"],
        "s02": report["s02"],
        "audit_count": report["audit_count"],
        "checks": report["checks"],
        "evidence": report["evidence"],
    }
    (evidence_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    for name in ("upload-shipment.xlsx", "result.xlsx", "result-anomalies.csv"):
        source = workspace / name
        if source.is_file():
            (evidence_dir / name).write_bytes(source.read_bytes())
    assert audit_path.is_file()
    assert report["scenarios"]["S04"] == "PASS", report["failed"]
    assert report["verdict"] == "PASS", report["failed"]
    assert report["ids"]["task_id"]
    assert report["ids"]["trace_id"]
    assert report["verification"]["stored_count"] == 2
    assert report["verification"]["status"] == "partial"
