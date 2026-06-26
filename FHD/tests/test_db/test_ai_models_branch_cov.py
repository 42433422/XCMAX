"""Branch-coverage tests for app.db.models.ai.

Focuses on UserMemory helper properties, update_from_dict branching,
to_dict, and cleanup_old_records.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.db.models.ai import UserMemory

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory() -> UserMemory:
    """Fresh UserMemory instance with defaults."""
    return UserMemory(
        user_id="u1",
        ttl_days=90,
        max_preferences=50,
        max_actions=30,
        max_contexts=100,
        max_feedback=50,
    )


# ---------------------------------------------------------------------------
# preferences_dict
# ---------------------------------------------------------------------------


class TestPreferencesDict:
    def test_empty_when_none(self, memory: UserMemory) -> None:
        memory.preferences = None
        assert memory.preferences_dict == {}

    def test_empty_when_unset(self, memory: UserMemory) -> None:
        # Mapped column default is None until set
        memory.preferences = None
        assert memory.preferences_dict == {}

    def test_returns_parsed_dict(self, memory: UserMemory) -> None:
        memory.preferences = json.dumps({"theme": "dark", "lang": "zh"})
        result = memory.preferences_dict
        assert result == {"theme": "dark", "lang": "zh"}


# ---------------------------------------------------------------------------
# frequent_actions_list
# ---------------------------------------------------------------------------


class TestFrequentActionsList:
    def test_empty_when_none(self, memory: UserMemory) -> None:
        memory.frequent_actions = None
        assert memory.frequent_actions_list == []

    def test_returns_parsed_list(self, memory: UserMemory) -> None:
        memory.frequent_actions = json.dumps([{"action": "click", "count": 3}])
        result = memory.frequent_actions_list
        assert isinstance(result, list)
        assert result[0]["action"] == "click"


# ---------------------------------------------------------------------------
# historical_contexts_list
# ---------------------------------------------------------------------------


class TestHistoricalContextsList:
    def test_empty_when_none(self, memory: UserMemory) -> None:
        memory.historical_contexts = None
        assert memory.historical_contexts_list == []

    def test_returns_parsed_list(self, memory: UserMemory) -> None:
        memory.historical_contexts = json.dumps([{"ctx": "abc"}])
        result = memory.historical_contexts_list
        assert isinstance(result, list)
        assert result[0]["ctx"] == "abc"


# ---------------------------------------------------------------------------
# feedback_history_list
# ---------------------------------------------------------------------------


class TestFeedbackHistoryList:
    def test_empty_when_none(self, memory: UserMemory) -> None:
        memory.feedback_history = None
        assert memory.feedback_history_list == []

    def test_returns_parsed_list(self, memory: UserMemory) -> None:
        memory.feedback_history = json.dumps([{"rating": 5}])
        result = memory.feedback_history_list
        assert isinstance(result, list)
        assert result[0]["rating"] == 5


# ---------------------------------------------------------------------------
# update_from_dict - preferences
# ---------------------------------------------------------------------------


class TestUpdateFromDictPreferences:
    def test_preferences_dict_within_limit(self, memory: UserMemory) -> None:
        memory.update_from_dict({"preferences": {"a": 1}})
        assert json.loads(memory.preferences) == {"a": 1}

    def test_preferences_dict_exceeds_limit_truncates(self, memory: UserMemory) -> None:
        memory.max_preferences = 2
        prefs = {"a": 1, "b": 2, "c": 3}
        memory.update_from_dict({"preferences": prefs})
        result = json.loads(memory.preferences)
        assert len(result) == 2

    def test_preferences_dict_exceeds_limit_with_none_max(self, memory: UserMemory) -> None:
        memory.max_preferences = None
        prefs = {f"k{i}": i for i in range(60)}
        memory.update_from_dict({"preferences": prefs})
        result = json.loads(memory.preferences)
        # Falls back to 50 when max_preferences is None
        assert len(result) == 50

    def test_preferences_non_dict_stored_as_is(self, memory: UserMemory) -> None:
        memory.update_from_dict({"preferences": "not-a-dict"})
        assert json.loads(memory.preferences) == "not-a-dict"

    def test_preferences_not_in_data_skipped(self, memory: UserMemory) -> None:
        memory.preferences = '{"existing": true}'
        memory.update_from_dict({"frequent_actions": []})
        # preferences should remain unchanged
        assert json.loads(memory.preferences) == {"existing": True}


# ---------------------------------------------------------------------------
# update_from_dict - frequent_actions
# ---------------------------------------------------------------------------


class TestUpdateFromDictFrequentActions:
    def test_actions_list_sorted_by_count_desc(self, memory: UserMemory) -> None:
        actions = [
            {"action": "low", "count": 1},
            {"action": "high", "count": 10},
            {"action": "mid", "count": 5},
        ]
        memory.update_from_dict({"frequent_actions": actions})
        result = json.loads(memory.frequent_actions)
        assert result[0]["action"] == "high"
        assert result[1]["action"] == "mid"
        assert result[2]["action"] == "low"

    def test_actions_list_truncated_to_max(self, memory: UserMemory) -> None:
        memory.max_actions = 2
        actions = [{"action": f"a{i}", "count": i} for i in range(5, 0, -1)]
        memory.update_from_dict({"frequent_actions": actions})
        result = json.loads(memory.frequent_actions)
        assert len(result) == 2

    def test_actions_list_truncated_with_none_max(self, memory: UserMemory) -> None:
        memory.max_actions = None
        actions = [{"action": f"a{i}", "count": i} for i in range(35, 0, -1)]
        memory.update_from_dict({"frequent_actions": actions})
        result = json.loads(memory.frequent_actions)
        # Falls back to 30
        assert len(result) == 30

    def test_actions_with_non_dict_items(self, memory: UserMemory) -> None:
        # Items without 'count' key use 0
        actions = ["plain_string", 42, {"action": "real", "count": 5}]
        memory.update_from_dict({"frequent_actions": actions})
        result = json.loads(memory.frequent_actions)
        # All should be preserved (sorted with count=0 for non-dict)
        assert len(result) == 3

    def test_actions_non_list_stored_as_is(self, memory: UserMemory) -> None:
        memory.update_from_dict({"frequent_actions": "not-a-list"})
        assert json.loads(memory.frequent_actions) == "not-a-list"

    def test_actions_not_in_data_skipped(self, memory: UserMemory) -> None:
        memory.frequent_actions = '[{"existing": true}]'
        memory.update_from_dict({"preferences": {}})
        assert memory.frequent_actions == '[{"existing": true}]'


# ---------------------------------------------------------------------------
# update_from_dict - historical_contexts
# ---------------------------------------------------------------------------


class TestUpdateFromDictHistoricalContexts:
    def test_contexts_list_truncated_to_max(self, memory: UserMemory) -> None:
        memory.max_contexts = 2
        contexts = [{"ctx": f"c{i}"} for i in range(5)]
        memory.update_from_dict({"historical_contexts": contexts})
        result = json.loads(memory.historical_contexts)
        assert len(result) == 2

    def test_contexts_list_truncated_with_none_max(self, memory: UserMemory) -> None:
        memory.max_contexts = None
        contexts = [{"ctx": f"c{i}"} for i in range(105)]
        memory.update_from_dict({"historical_contexts": contexts})
        result = json.loads(memory.historical_contexts)
        # Falls back to 100
        assert len(result) == 100

    def test_contexts_non_list_stored_as_is(self, memory: UserMemory) -> None:
        memory.update_from_dict({"historical_contexts": "not-a-list"})
        assert json.loads(memory.historical_contexts) == "not-a-list"

    def test_contexts_not_in_data_skipped(self, memory: UserMemory) -> None:
        memory.historical_contexts = '[{"existing": true}]'
        memory.update_from_dict({"preferences": {}})
        assert memory.historical_contexts == '[{"existing": true}]'


# ---------------------------------------------------------------------------
# update_from_dict - feedback_history
# ---------------------------------------------------------------------------


class TestUpdateFromDictFeedbackHistory:
    def test_feedback_list_truncated_to_max(self, memory: UserMemory) -> None:
        memory.max_feedback = 2
        feedback = [{"rating": i} for i in range(5)]
        memory.update_from_dict({"feedback_history": feedback})
        result = json.loads(memory.feedback_history)
        assert len(result) == 2

    def test_feedback_list_truncated_with_none_max(self, memory: UserMemory) -> None:
        memory.max_feedback = None
        feedback = [{"rating": i} for i in range(55)]
        memory.update_from_dict({"feedback_history": feedback})
        result = json.loads(memory.feedback_history)
        # Falls back to 50
        assert len(result) == 50

    def test_feedback_non_list_stored_as_is(self, memory: UserMemory) -> None:
        memory.update_from_dict({"feedback_history": "not-a-list"})
        assert json.loads(memory.feedback_history) == "not-a-list"

    def test_feedback_not_in_data_skipped(self, memory: UserMemory) -> None:
        memory.feedback_history = '[{"existing": true}]'
        memory.update_from_dict({"preferences": {}})
        assert memory.feedback_history == '[{"existing": true}]'


# ---------------------------------------------------------------------------
# update_from_dict - updated_at
# ---------------------------------------------------------------------------


class TestUpdateFromDictUpdatedAt:
    def test_updated_at_is_set(self, memory: UserMemory) -> None:
        before = datetime.now()
        memory.update_from_dict({"preferences": {}})
        assert memory.updated_at is not None
        assert memory.updated_at >= before


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_with_updated_at(self, memory: UserMemory) -> None:
        memory.updated_at = datetime(2026, 1, 15, 10, 30, 0)
        memory.preferences = json.dumps({"k": "v"})
        memory.frequent_actions = json.dumps([{"a": 1}])
        memory.historical_contexts = json.dumps([{"c": 1}])
        memory.feedback_history = json.dumps([{"f": 1}])
        result = memory.to_dict()
        assert result["user_id"] == "u1"
        assert result["preferences"] == {"k": "v"}
        assert result["frequent_actions"] == [{"a": 1}]
        assert result["historical_contexts"] == [{"c": 1}]
        assert result["feedback_history"] == [{"f": 1}]
        assert result["updated_at"] == "2026-01-15T10:30:00"
        assert result["ttl_days"] == 90

    def test_without_updated_at(self, memory: UserMemory) -> None:
        memory.updated_at = None
        result = memory.to_dict()
        assert result["updated_at"] is None

    def test_with_empty_fields(self, memory: UserMemory) -> None:
        memory.updated_at = None
        memory.preferences = None
        memory.frequent_actions = None
        memory.historical_contexts = None
        memory.feedback_history = None
        result = memory.to_dict()
        assert result["preferences"] == {}
        assert result["frequent_actions"] == []
        assert result["historical_contexts"] == []
        assert result["feedback_history"] == []


# ---------------------------------------------------------------------------
# cleanup_old_records
# ---------------------------------------------------------------------------


class TestCleanupOldRecords:
    def test_deletes_old_records(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.db.base import Base

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            old = UserMemory(
                user_id="old",
                updated_at=datetime.now() - timedelta(days=100),
            )
            recent = UserMemory(
                user_id="recent",
                updated_at=datetime.now(),
            )
            db.add(old)
            db.add(recent)
            db.commit()

            deleted = UserMemory.cleanup_old_records(db, days=90)
            assert deleted == 1

            remaining = db.query(UserMemory).all()
            assert len(remaining) == 1
            assert remaining[0].user_id == "recent"
        finally:
            db.close()
            Base.metadata.drop_all(engine)
            engine.dispose()

    def test_no_old_records(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.db.base import Base

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            recent = UserMemory(
                user_id="recent",
                updated_at=datetime.now(),
            )
            db.add(recent)
            db.commit()

            deleted = UserMemory.cleanup_old_records(db, days=90)
            assert deleted == 0
        finally:
            db.close()
            Base.metadata.drop_all(engine)
            engine.dispose()

    def test_commit_called(self) -> None:
        """Verify commit is called on the session."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.delete.return_value = 5
        mock_query.filter.return_value = mock_filter
        mock_session.query.return_value = mock_query

        result = UserMemory.cleanup_old_records(mock_session, days=30)
        assert result == 5
        mock_session.commit.assert_called_once()
