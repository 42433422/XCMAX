"""Task lifecycle migrations must retain durable replay and side-effect guards."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import Session

from alembic import command
from app.domain.task_lifecycle.control import SessionBook, TaskLifecycleError

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PREVIOUS_REVISION = "2026_10_29_etl_archive"
_REVISION = "2026_11_06_task_lifecycle"


def test_downgrade_and_reupgrade_preserve_task_replay_guards(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'lifecycle-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(_PROJECT_ROOT / "alembic.ini"))
    # These ledgers have no external foreign keys. Start at the previous schema
    # version to exercise this revision without the current ORM-built baseline.
    command.stamp(config, _PREVIOUS_REVISION)
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, _REVISION)
        effects = [{"effect_id": "posted-order", "status": "completed"}]
        with Session(engine) as db, db.begin():
            book = SessionBook(db)
            assert (
                book.claim_key("agent", "tenant-a", "request-a", "payload-a", "run-original") == ""
            )
            book.put("agent", "tenant-a", "run-original", {"effects": effects})

        for target in (_PREVIOUS_REVISION, _PREVIOUS_REVISION, _REVISION, _REVISION):
            if target == _PREVIOUS_REVISION:
                command.downgrade(config, target)
            else:
                command.upgrade(config, target)
            with Session(engine) as db, db.begin():
                book = SessionBook(db)
                assert (
                    book.claim_key("agent", "tenant-a", "request-a", "payload-a", "run-new")
                    == "run-original"
                )
                assert book.get("agent", "tenant-a", "run-original")["effects"] == effects
                with pytest.raises(TaskLifecycleError, match="幂等键与已有任务内容冲突"):
                    book.claim_key("agent", "tenant-a", "request-a", "changed-payload", "run-new")
    finally:
        engine.dispose()
