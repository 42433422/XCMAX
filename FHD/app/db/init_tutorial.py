"""Runtime initialization for Tutorial V2 control-plane tables."""

from typing import cast

from sqlalchemy import Table
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.db.models.tutorial import TutorialRun, TutorialStepEvidence, TutorialWorkspace


def init_tutorial_v2_tables(engine: Engine) -> None:
    """Create tutorial tables for fresh desktop/Web databases."""
    Base.metadata.create_all(
        engine,
        tables=[
            cast("Table", TutorialWorkspace.__table__),
            cast("Table", TutorialRun.__table__),
            cast("Table", TutorialStepEvidence.__table__),
        ],
        checkfirst=True,
    )
