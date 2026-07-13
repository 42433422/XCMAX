from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Barrier

from sqlalchemy.orm import sessionmaker

import app.db as db_mod
import app.infrastructure.session.session_manager as session_manager_module
from app.db.base import Base
from app.db.models import User, UserSession
from app.infrastructure.session.session_manager import SessionManager


def test_desktop_file_sqlite_supports_concurrent_session_validation(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    db_path = tmp_path / "desktop-session-concurrency.db"
    engine = db_mod._create_engine_for_url(f"sqlite:///{db_path}")
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    with factory() as db:
        user = User(
            username="concurrent-user",
            password="test-only",
            display_name="Concurrent User",
            role="user",
            tier="enterprise",
            industry_id="考勤",
        )
        db.add(user)
        db.flush()
        user_id = int(user.id)
        db.add(
            UserSession(
                session_id="concurrent-session",
                user_id=user_id,
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(days=1),
            )
        )
        db.commit()

    @contextmanager
    def _isolated_host_db():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(session_manager_module, "get_host_db", _isolated_host_db)
    manager = SessionManager()
    worker_count = 24
    start = Barrier(worker_count)

    def _validate_repeatedly(_worker: int) -> list[int]:
        start.wait(timeout=10)
        resolved_ids: list[int] = []
        for _ in range(12):
            resolved = manager.validate_session("concurrent-session")
            assert resolved is not None
            resolved_ids.append(int(resolved.id))
        return resolved_ids

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            batches = list(executor.map(_validate_repeatedly, range(worker_count)))
        assert [user_id] * (worker_count * 12) == [
            resolved_id for batch in batches for resolved_id in batch
        ]
    finally:
        engine.dispose()
