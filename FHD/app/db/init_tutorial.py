"""Runtime initialization for Tutorial V2 control-plane tables."""

from sqlalchemy.engine import Engine

from app.db.base import Base
from app.db.models.tutorial import TutorialRun, TutorialStepEvidence, TutorialWorkspace


def init_tutorial_v2_tables(engine: Engine) -> None:
    """Create tutorial tables for fresh desktop/Web databases."""
    Base.metadata.create_all(
        engine,
        tables=[
            TutorialWorkspace.__table__,
            TutorialRun.__table__,
            TutorialStepEvidence.__table__,
        ],
        checkfirst=True,
    )
