# -*- coding: utf-8 -*-
"""AI 员工领域值对象单元测试（capability / collaboration_graph / events /
memory_scope / perception_spec / trigger_binding）。

纯逻辑值对象，无外部依赖；覆盖 happy / 空值 / None / 边界 / 各分支（铁律3、铁律6）。
"""

from __future__ import annotations

import pytest

from app.domain.employee.capability import (
    EmployeeCapability,
    _coerce,
    parse_capabilities,
)
from app.domain.employee.collaboration_graph import CollaborationGraph
from app.domain.employee.events import (
    ALL_EMPLOYEE_EVENT_TYPES,
    EVENT_COVERAGE_MISSED,
    EVENT_QUALITY_FAILED,
    EVENT_TASK_FAILED,
    event_types_for_triggers,
)
from app.domain.employee.memory_scope import MemoryScope
from app.domain.employee.perception_spec import (
    PERCEPTION_AUDIO,
    PERCEPTION_DOCUMENT,
    PERCEPTION_IMAGE,
    PERCEPTION_TEXT,
    PerceptionSpec,
)
from app.domain.employee.trigger_binding import TriggerBinding


class TestEmployeeCapability:
    def test_key_normalizes_label(self):
        cap = EmployeeCapability(label="  Data Analysis  ")
        assert cap.key == "data_analysis"

    def test_frozen_dataclass_is_immutable(self):
        cap = EmployeeCapability(label="x")
        with pytest.raises(Exception):
            cap.label = "y"  # type: ignore[misc]

    def test_coerce_from_nonempty_str(self):
        cap = _coerce("  Sales  ")
        assert cap is not None
        assert cap.label == "Sales"

    def test_coerce_blank_str_returns_none(self):
        assert _coerce("   ") is None

    def test_coerce_dict_with_label(self):
        cap = _coerce({"label": "Audit", "description": "查账"})
        assert cap == EmployeeCapability(label="Audit", description="查账")

    def test_coerce_dict_name_fallback(self):
        cap = _coerce({"name": "OCR"})
        assert cap is not None and cap.label == "OCR"

    def test_coerce_dict_without_label_returns_none(self):
        assert _coerce({"foo": "bar"}) is None

    def test_coerce_other_types_return_none(self):
        assert _coerce(123) is None
        assert _coerce(None) is None

    def test_parse_capabilities_none_returns_empty(self):
        assert parse_capabilities(None) == []

    def test_parse_capabilities_non_dict_returns_empty(self):
        assert parse_capabilities("not a dict") == []  # type: ignore[arg-type]

    def test_parse_capabilities_from_employee_block(self):
        caps = parse_capabilities({"employee": {"capabilities": ["a", "b"]}})
        assert [c.label for c in caps] == ["a", "b"]

    def test_parse_capabilities_dedup_by_key(self):
        caps = parse_capabilities({"employee": {"capabilities": ["Data Sync", "data sync", "DATA SYNC"]}})
        assert len(caps) == 1

    def test_parse_capabilities_merges_v2_cognition_skills(self):
        manifest = {
            "employee": {"capabilities": ["base"]},
            "employee_config_v2": {
                "cognition": {"skills": [{"name": "skill1", "brief": "b1"}, "skill2"]}
            },
        }
        caps = parse_capabilities(manifest)
        labels = [c.label for c in caps]
        assert "base" in labels and "skill1" in labels and "skill2" in labels

    def test_parse_capabilities_v2_skill_without_name_skipped(self):
        manifest = {"employee_config_v2": {"cognition": {"skills": [{"brief": "no name"}]}}}
        assert parse_capabilities(manifest) == []

    def test_parse_capabilities_employee_not_dict(self):
        assert parse_capabilities({"employee": "x"}) == []


class TestCollaborationGraph:
    def test_add_and_edges(self):
        g = CollaborationGraph()
        g.add("a", ["b", "c"])
        assert g.edges["a"] == ["b", "c"]

    def test_add_blank_id_ignored(self):
        g = CollaborationGraph()
        g.add("  ", ["b"])
        assert g.edges == {}

    def test_add_filters_self_dependency_and_blanks(self):
        g = CollaborationGraph()
        g.add("a", ["a", " ", "b"])
        assert g.edges["a"] == ["b"]

    def test_add_dedup_deps(self):
        g = CollaborationGraph()
        g.add("a", ["b", "b", "c"])
        assert g.edges["a"] == ["b", "c"]

    def test_add_none_deps(self):
        g = CollaborationGraph()
        g.add("a", None)  # type: ignore[arg-type]
        assert g.edges["a"] == []

    def test_detect_cycle_none_when_acyclic(self):
        g = CollaborationGraph()
        g.add("a", ["b"])
        g.add("b", ["c"])
        assert g.detect_cycle() is None

    def test_detect_cycle_finds_cycle(self):
        g = CollaborationGraph()
        g.add("a", ["b"])
        g.add("b", ["a"])
        cycle = g.detect_cycle()
        assert cycle is not None
        assert cycle[0] == cycle[-1]

    def test_detect_cycle_self_loop_via_unknown_dep(self):
        g = CollaborationGraph()
        g.add("a", ["b"])  # b not declared as node
        assert g.detect_cycle() is None

    def test_execution_order_deps_first_root_last(self):
        g = CollaborationGraph()
        g.add("root", ["dep1", "dep2"])
        g.add("dep1", ["leaf"])
        order = g.execution_order("root")
        assert order[-1] == "root"
        assert order.index("leaf") < order.index("dep1")
        assert order.index("dep1") < order.index("root")

    def test_execution_order_empty_root(self):
        assert CollaborationGraph().execution_order("") == []
        assert CollaborationGraph().execution_order("   ") == []

    def test_execution_order_cycle_safe(self):
        g = CollaborationGraph()
        g.add("a", ["b"])
        g.add("b", ["a"])
        order = g.execution_order("a")
        assert "a" in order and "b" in order
        assert len(order) == 2

    def test_detect_cycle_diamond_acyclic_revisits_black_node(self):
        # 菱形：a->b, a->c, b->d, c->d；访问 d（经 b）置 BLACK，再经 c->d 命中已 BLACK 分支
        g = CollaborationGraph()
        g.add("a", ["b", "c"])
        g.add("b", ["d"])
        g.add("c", ["d"])
        g.add("d", [])
        assert g.detect_cycle() is None


class TestEmployeeEvents:
    def test_event_types_none_returns_empty(self):
        assert event_types_for_triggers(None) == []

    def test_event_types_non_dict_returns_empty(self):
        assert event_types_for_triggers([1, 2]) == []  # type: ignore[arg-type]

    def test_event_types_bool_true(self):
        out = event_types_for_triggers({"on_error": True, "on_quality_fail": True})
        assert EVENT_TASK_FAILED in out and EVENT_QUALITY_FAILED in out

    def test_event_types_string_truthy(self):
        out = event_types_for_triggers({"on_coverage_miss": "yes"})
        assert out == [EVENT_COVERAGE_MISSED]

    def test_event_types_falsey_excluded(self):
        out = event_types_for_triggers({"on_error": False, "on_quality_fail": "no", "on_coverage_miss": 0})
        assert out == []

    def test_all_event_types_constant(self):
        assert EVENT_TASK_FAILED in ALL_EMPLOYEE_EVENT_TYPES
        assert len(ALL_EMPLOYEE_EVENT_TYPES) == 4


class TestMemoryScope:
    def test_long_term_index_default(self):
        scope = MemoryScope(employee_id="emp1")
        assert scope.long_term_index() == "emp:emp1"

    def test_long_term_index_user_scoped(self):
        scope = MemoryScope(employee_id="emp1", user_scoped=True)
        assert scope.long_term_index("u9") == "emp:emp1:usr:u9"

    def test_long_term_index_user_scoped_but_no_uid(self):
        scope = MemoryScope(employee_id="emp1", user_scoped=True)
        assert scope.long_term_index("  ") == "emp:emp1"

    def test_long_term_index_not_user_scoped_ignores_uid(self):
        scope = MemoryScope(employee_id="emp1", user_scoped=False)
        assert scope.long_term_index("u9") == "emp:emp1"

    def test_from_config_none_defaults_enabled(self):
        scope = MemoryScope.from_config("e", None)
        assert scope.short_term_enabled and scope.long_term_enabled

    @pytest.mark.parametrize("mem_type", ["none", "stateless", "off"])
    def test_from_config_disabled_types(self, mem_type):
        scope = MemoryScope.from_config("e", {"memory": {"type": mem_type}})
        assert not scope.short_term_enabled and not scope.long_term_enabled

    def test_from_config_empty_type_defaults_to_session_enabled(self):
        # type="" → `"" or "session"` → "session"（"" 在 disabled 集里实为不可达）
        scope = MemoryScope.from_config("e", {"memory": {"type": ""}})
        assert scope.short_term_enabled and scope.long_term_enabled

    def test_from_config_long_term_explicit_false(self):
        scope = MemoryScope.from_config("e", {"memory": {"type": "session", "long_term": "false"}})
        assert scope.short_term_enabled and not scope.long_term_enabled

    def test_from_config_long_term_bool_true(self):
        scope = MemoryScope.from_config("e", {"memory": {"type": "session", "long_term": True}})
        assert scope.long_term_enabled

    def test_from_config_long_term_zero_is_disabled(self):
        scope = MemoryScope.from_config("e", {"memory": {"type": "session", "long_term": 0}})
        assert not scope.long_term_enabled

    def test_from_config_user_scope(self):
        scope = MemoryScope.from_config("e", {"memory": {"type": "session", "scope": "per_user"}})
        assert scope.user_scoped

    def test_from_config_memory_not_dict(self):
        scope = MemoryScope.from_config("e", {"memory": "x"})
        assert scope.long_term_enabled


class TestPerceptionSpec:
    def test_has_modality(self):
        spec = PerceptionSpec(modalities=(PERCEPTION_TEXT, PERCEPTION_IMAGE))
        assert spec.has(PERCEPTION_IMAGE)
        assert not spec.has(PERCEPTION_AUDIO)

    def test_from_config_none_defaults_text(self):
        spec = PerceptionSpec.from_config(None)
        assert spec.type == PERCEPTION_TEXT
        assert spec.modalities == (PERCEPTION_TEXT,)

    def test_from_config_document_vision_audio(self):
        spec = PerceptionSpec.from_config(
            {
                "perception": {
                    "document": {"enabled": True},
                    "vision": {"enabled": True},
                    "audio": {"enabled": True},
                }
            }
        )
        assert spec.has(PERCEPTION_DOCUMENT)
        assert spec.has(PERCEPTION_IMAGE)
        assert spec.has(PERCEPTION_AUDIO)
        assert spec.has(PERCEPTION_TEXT)
        assert spec.type == PERCEPTION_DOCUMENT

    def test_from_config_explicit_type(self):
        spec = PerceptionSpec.from_config({"perception": {"type": "image"}})
        assert spec.type == PERCEPTION_IMAGE
        assert spec.has(PERCEPTION_IMAGE)

    def test_from_config_disabled_modalities_text_only(self):
        spec = PerceptionSpec.from_config({"perception": {"document": {"enabled": False}}})
        assert spec.type == PERCEPTION_TEXT
        assert spec.modalities == (PERCEPTION_TEXT,)

    def test_from_config_invalid_type_falls_back_to_modalities(self):
        spec = PerceptionSpec.from_config(
            {"perception": {"type": "garbage", "vision": {"enabled": True}}}
        )
        assert spec.type == PERCEPTION_IMAGE

    def test_from_config_explicit_type_already_in_modalities(self):
        # type=document 且 document enabled → explicit 已在 modalities，跳过 insert 分支
        spec = PerceptionSpec.from_config(
            {"perception": {"type": "document", "document": {"enabled": True}}}
        )
        assert spec.type == PERCEPTION_DOCUMENT
        assert spec.modalities.count(PERCEPTION_DOCUMENT) == 1

    def test_from_config_explicit_text_skips_append(self):
        # type=text → 先 insert text，line 56 处 TEXT 已在 modalities，跳过 append 分支
        spec = PerceptionSpec.from_config({"perception": {"type": "text"}})
        assert spec.type == PERCEPTION_TEXT
        assert spec.modalities == (PERCEPTION_TEXT,)

    def test_from_config_perception_not_dict(self):
        spec = PerceptionSpec.from_config({"perception": "x"})
        assert spec.type == PERCEPTION_TEXT


class TestTriggerBinding:
    def test_active_false_when_no_events(self):
        tb = TriggerBinding(employee_id="e")
        assert not tb.active

    def test_from_manifest_none(self):
        tb = TriggerBinding.from_manifest("e", None)
        assert tb.employee_id == "e"
        assert not tb.active

    def test_from_manifest_top_level_triggers(self):
        tb = TriggerBinding.from_manifest(
            "e",
            {"triggers": {"on_error": True, "max_patch_steps": 5, "max_patch_budget_tokens": 100}},
        )
        assert tb.active
        assert EVENT_TASK_FAILED in tb.event_types
        assert tb.max_patch_steps == 5
        assert tb.max_patch_budget_tokens == 100

    def test_from_manifest_v2_triggers_fallback(self):
        tb = TriggerBinding.from_manifest(
            "e", {"employee_config_v2": {"triggers": {"on_quality_fail": True}}}
        )
        assert EVENT_QUALITY_FAILED in tb.event_types

    def test_from_manifest_sla_escalate(self):
        tb = TriggerBinding.from_manifest("e", {"sla": {"escalate_to_human": True}})
        assert tb.escalate_to_human

    def test_from_manifest_v2_sla_fallback(self):
        tb = TriggerBinding.from_manifest(
            "e", {"employee_config_v2": {"sla": {"escalate_to_human": True}}}
        )
        assert tb.escalate_to_human

    def test_from_manifest_strips_employee_id(self):
        tb = TriggerBinding.from_manifest("  e9  ", {})
        assert tb.employee_id == "e9"
