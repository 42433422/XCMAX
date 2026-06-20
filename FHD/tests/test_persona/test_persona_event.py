# FHD/tests/test_persona/test_persona_event.py
"""Persona 领域事件测试。"""

from __future__ import annotations

from app.domain.persona.value_objects import PersonaAxes
from app.neuro_bus.events.persona_event import PersonaUpdated


class TestPersonaUpdated:
    """PersonaUpdated 事件测试。"""

    def test_create_event_returns_all_fields(self):
        axes = PersonaAxes(warmth=0.7, detail=0.4, proactivity=0.6, structure=0.8)
        event = PersonaUpdated(
            user_id="user-1",
            axes=axes,
            rapport=0.5,
            identity="考勤管家",
            source="l1",
            trace_id="trace-123",
        )
        assert event.user_id == "user-1"
        assert event.axes.warmth == 0.7
        assert event.rapport == 0.5
        assert event.identity == "考勤管家"
        assert event.source == "l1"
        assert event.trace_id == "trace-123"

    def test_event_type_is_correct(self):
        event = PersonaUpdated(
            user_id="user-1",
            axes=PersonaAxes(),
            rapport=0.3,
            identity="业务管家",
            source="fusion",
            trace_id="t-1",
        )
        assert event.event_type == "persona.updated"

    def test_to_dict_returns_serializable(self):
        event = PersonaUpdated(
            user_id="user-1",
            axes=PersonaAxes(warmth=0.7),
            rapport=0.5,
            identity="考勤管家",
            source="l1",
            trace_id="t-1",
        )
        d = event.to_dict()
        assert d["user_id"] == "user-1"
        assert d["axes"]["warmth"] == 0.7
        assert d["rapport"] == 0.5
