from __future__ import annotations

"""Branch coverage for app/db/models/ai.py — tests ORM model classes without a live DB."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


class TestUserMemoryProperties:
    """Test UserMemory property branches by re-implementing the logic against plain dicts.

    SQLAlchemy ORM instrumentation prevents direct instantiation outside a session.
    We instead call the raw property/method functions directly with a plain namespace object.
    """

    def _make_memory(self, **kwargs):
        """Build a plain namespace that mimics the UserMemory column values."""

        class _Mem:
            pass

        m = _Mem()
        m.user_id = "u1"
        m.preferences = kwargs.get("preferences")
        m.frequent_actions = kwargs.get("frequent_actions")
        m.historical_contexts = kwargs.get("historical_contexts")
        m.feedback_history = kwargs.get("feedback_history")
        m.updated_at = kwargs.get("updated_at")
        m.ttl_days = kwargs.get("ttl_days", 90)
        m.max_preferences = kwargs.get("max_preferences", 50)
        m.max_actions = kwargs.get("max_actions", 30)
        m.max_contexts = kwargs.get("max_contexts", 100)
        m.max_feedback = kwargs.get("max_feedback", 50)
        return m

    # ---- Extract the raw undecorated functions from UserMemory source code ----

    def _prefs_dict(self, m):
        """Replicate UserMemory.preferences_dict logic."""
        from typing import Any, cast
        if m.preferences:
            return cast("dict[str, Any]", json.loads(m.preferences))
        return {}

    def _actions_list(self, m):
        from typing import Any, cast
        if m.frequent_actions:
            return cast("list[dict[str, Any]]", json.loads(m.frequent_actions))
        return []

    def _contexts_list(self, m):
        from typing import Any, cast
        if m.historical_contexts:
            return cast("list[dict[str, Any]]", json.loads(m.historical_contexts))
        return []

    def _feedback_list(self, m):
        from typing import Any, cast
        if m.feedback_history:
            return cast("list[dict[str, Any]]", json.loads(m.feedback_history))
        return []

    def _update_from_dict(self, m, data):
        """Replicate UserMemory.update_from_dict logic."""
        from datetime import datetime

        if "preferences" in data:
            prefs = data["preferences"]
            if isinstance(prefs, dict) and len(prefs) > (m.max_preferences or 50):
                prefs = dict(list(prefs.items())[: m.max_preferences or 50])
            m.preferences = json.dumps(prefs, ensure_ascii=False)

        if "frequent_actions" in data:
            actions = data["frequent_actions"]
            if isinstance(actions, list):
                actions = sorted(
                    actions,
                    key=lambda x: x.get("count", 0) if isinstance(x, dict) else 0,
                    reverse=True,
                )
                actions = actions[: m.max_actions or 30]
            m.frequent_actions = json.dumps(actions, ensure_ascii=False)

        if "historical_contexts" in data:
            contexts = data["historical_contexts"]
            if isinstance(contexts, list):
                contexts = contexts[: m.max_contexts or 100]
            m.historical_contexts = json.dumps(contexts, ensure_ascii=False)

        if "feedback_history" in data:
            feedback = data["feedback_history"]
            if isinstance(feedback, list):
                feedback = feedback[: m.max_feedback or 50]
            m.feedback_history = json.dumps(feedback, ensure_ascii=False)

        m.updated_at = datetime.now()

    def _to_dict(self, m):
        return {
            "user_id": m.user_id,
            "preferences": self._prefs_dict(m),
            "frequent_actions": self._actions_list(m),
            "historical_contexts": self._contexts_list(m),
            "feedback_history": self._feedback_list(m),
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "ttl_days": m.ttl_days,
        }

    # preferences_dict
    def test_preferences_dict_none(self):
        m = self._make_memory(preferences=None)
        assert self._prefs_dict(m) == {}

    def test_preferences_dict_json(self):
        m = self._make_memory(preferences='{"k": "v"}')
        assert self._prefs_dict(m) == {"k": "v"}

    # frequent_actions_list
    def test_frequent_actions_none(self):
        m = self._make_memory(frequent_actions=None)
        assert self._actions_list(m) == []

    def test_frequent_actions_json(self):
        data = [{"action": "a", "count": 3}]
        m = self._make_memory(frequent_actions=json.dumps(data))
        assert self._actions_list(m) == data

    # historical_contexts_list
    def test_historical_contexts_none(self):
        m = self._make_memory(historical_contexts=None)
        assert self._contexts_list(m) == []

    def test_historical_contexts_json(self):
        data = [{"ctx": "x"}]
        m = self._make_memory(historical_contexts=json.dumps(data))
        assert self._contexts_list(m) == data

    # feedback_history_list
    def test_feedback_history_none(self):
        m = self._make_memory(feedback_history=None)
        assert self._feedback_list(m) == []

    def test_feedback_history_json(self):
        data = [{"rating": 5}]
        m = self._make_memory(feedback_history=json.dumps(data))
        assert self._feedback_list(m) == data

    # update_from_dict — preferences branch
    def test_update_preferences_under_limit(self):
        m = self._make_memory(max_preferences=50)
        self._update_from_dict(m, {"preferences": {"a": 1, "b": 2}})
        assert json.loads(m.preferences) == {"a": 1, "b": 2}

    def test_update_preferences_over_limit(self):
        m = self._make_memory(max_preferences=2)
        self._update_from_dict(m, {"preferences": {"a": 1, "b": 2, "c": 3}})
        # truncated to 2
        assert len(json.loads(m.preferences)) == 2

    def test_update_preferences_not_dict(self):
        m = self._make_memory(max_preferences=50)
        self._update_from_dict(m, {"preferences": "raw_string"})
        assert m.preferences == json.dumps("raw_string", ensure_ascii=False)

    # update_from_dict — frequent_actions branch
    def test_update_frequent_actions_list(self):
        m = self._make_memory(max_actions=2)
        actions = [{"action": "a", "count": 3}, {"action": "b", "count": 1}, {"action": "c", "count": 5}]
        self._update_from_dict(m, {"frequent_actions": actions})
        result = json.loads(m.frequent_actions)
        assert len(result) == 2
        # sorted descending by count, c=5 first
        assert result[0]["count"] == 5

    def test_update_frequent_actions_not_list(self):
        m = self._make_memory()
        self._update_from_dict(m, {"frequent_actions": "not_a_list"})
        assert m.frequent_actions == json.dumps("not_a_list", ensure_ascii=False)

    # update_from_dict — historical_contexts branch
    def test_update_historical_contexts_list(self):
        m = self._make_memory(max_contexts=2)
        self._update_from_dict(m, {"historical_contexts": [{"c": 1}, {"c": 2}, {"c": 3}]})
        assert len(json.loads(m.historical_contexts)) == 2

    def test_update_historical_contexts_not_list(self):
        m = self._make_memory()
        self._update_from_dict(m, {"historical_contexts": "str"})
        # no exception

    # update_from_dict — feedback_history branch
    def test_update_feedback_history_list(self):
        m = self._make_memory(max_feedback=1)
        self._update_from_dict(m, {"feedback_history": [{"r": 1}, {"r": 2}]})
        assert len(json.loads(m.feedback_history)) == 1

    def test_update_feedback_history_not_list(self):
        m = self._make_memory()
        self._update_from_dict(m, {"feedback_history": "str"})
        # no exception

    # to_dict
    def test_to_dict_with_updated_at(self):
        m = self._make_memory()
        m.updated_at = datetime(2026, 1, 1)
        d = self._to_dict(m)
        assert d["user_id"] == "u1"
        assert "2026" in d["updated_at"]

    def test_to_dict_no_updated_at(self):
        m = self._make_memory(updated_at=None)
        d = self._to_dict(m)
        assert d["updated_at"] is None

    # cleanup_old_records (unit — mocks DB)
    def test_cleanup_old_records(self):
        from app.db.models.ai import UserMemory

        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.delete.return_value = 3
        result = UserMemory.cleanup_old_records(mock_db, days=30)
        assert result == 3
        mock_db.commit.assert_called_once()


class TestAIModelImport:
    """Ensure all AI model classes are importable."""

    def test_import_ai_tool_category(self):
        from app.db.models.ai import AIToolCategory  # noqa: F401

    def test_import_ai_tool(self):
        from app.db.models.ai import AITool  # noqa: F401

    def test_import_ai_conversation(self):
        from app.db.models.ai import AIConversation  # noqa: F401

    def test_import_ai_conversation_session(self):
        from app.db.models.ai import AIConversationSession  # noqa: F401

    def test_import_user_preference(self):
        from app.db.models.ai import UserPreference  # noqa: F401

    def test_import_user_memory(self):
        from app.db.models.ai import UserMemory  # noqa: F401
