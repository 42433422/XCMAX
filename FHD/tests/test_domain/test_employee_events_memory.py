"""员工领域值对象：events / trigger_binding / memory_scope。"""

from __future__ import annotations

from app.domain.employee.events import (
    EVENT_COVERAGE_MISSED,
    EVENT_QUALITY_FAILED,
    EVENT_TASK_FAILED,
    event_types_for_triggers,
)
from app.domain.employee.memory_scope import MemoryScope
from app.domain.employee.trigger_binding import TriggerBinding


class TestEmployeeEvents:
    def test_event_types_for_triggers_empty(self):
        assert event_types_for_triggers(None) == []
        assert event_types_for_triggers({}) == []

    def test_event_types_for_triggers_flags(self):
        triggers = {
            "on_error": True,
            "on_quality_fail": "yes",
            "on_coverage_miss": 0,
        }
        types = event_types_for_triggers(triggers)
        assert EVENT_TASK_FAILED in types
        assert EVENT_QUALITY_FAILED in types
        assert EVENT_COVERAGE_MISSED not in types


class TestTriggerBinding:
    def test_from_manifest_top_level(self):
        manifest = {
            "triggers": {"on_error": True, "max_patch_steps": 3},
            "sla": {"escalate_to_human": True},
        }
        b = TriggerBinding.from_manifest("emp-a", manifest)
        assert b.employee_id == "emp-a"
        assert b.active is True
        assert EVENT_TASK_FAILED in b.event_types
        assert b.max_patch_steps == 3
        assert b.escalate_to_human is True

    def test_from_manifest_v2_fallback(self):
        manifest = {"employee_config_v2": {"triggers": {"on_coverage_miss": "on"}}}
        b = TriggerBinding.from_manifest("emp-b", manifest)
        assert EVENT_COVERAGE_MISSED in b.event_types

    def test_inactive_when_no_triggers(self):
        b = TriggerBinding.from_manifest("emp-c", {})
        assert b.active is False


class TestMemoryScope:
    def test_long_term_index_default(self):
        scope = MemoryScope(employee_id="pdf-gen")
        assert scope.long_term_index() == "emp:pdf-gen"

    def test_long_term_index_user_scoped(self):
        scope = MemoryScope(employee_id="e1", user_scoped=True)
        assert scope.long_term_index("42") == "emp:e1:usr:42"

    def test_from_config_disabled_types(self):
        for t in ("none", "stateless", "off"):
            scope = MemoryScope.from_config("e", {"memory": {"type": t}})
            assert scope.short_term_enabled is False
            assert scope.long_term_enabled is False

    def test_from_config_long_term_off(self):
        scope = MemoryScope.from_config("e", {"memory": {"type": "session", "long_term": False}})
        assert scope.short_term_enabled is True
        assert scope.long_term_enabled is False

    def test_from_config_user_scope_aliases(self):
        scope = MemoryScope.from_config("e", {"memory": {"scope": "per_user"}})
        assert scope.user_scoped is True
