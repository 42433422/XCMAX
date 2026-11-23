"""Real isolated proposal storage for route-only code-editor tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.db_base import Base
from app.db.models.local_file import CodeEditProposal
from app.db.models.user import User


@pytest.fixture
def editor_database(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'route-editor.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[User.__table__, CodeEditProposal.__table__])
    with Session(engine) as db:
        db.add(User(id=1, username="editor-route-fixture", password="test-only", tenant_id=10))
        db.commit()
    try:
        yield engine
    finally:
        engine.dispose()
