"""Shared SQL request journal and account fixtures for model billing tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

KEY = "a" * 32


@pytest.fixture
def db():
    from modstore_server.models import Base, User

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            User(id=7, username="ledger-user-7", password_hash="test-only"),
            User(id=8, username="ledger-user-8", password_hash="test-only"),
        ]
    )
    session.commit()
    yield session
    session.close()
