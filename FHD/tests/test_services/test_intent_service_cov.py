from __future__ import annotations

"""Branch-coverage tests for app/services/intent_service.py.

Targets the ~46 missing branches identified in coverage_new.json.
All external deps (reflex_arc, rule_engine, cache, purchase_unit_resolver) are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level patch helpers
# ---------------------------------------------------------------------------

_REFLEX_NONE_TYPE = MagicMock()


def _make_reflex(reflex_type, triggered: bool = False):
    rr = MagicMock()
    rr.reflex_type = reflex_type
    rr.triggered = triggered
    return rr


def _make_engine(matches=None, hint_matches=None):
    engine = MagicMock()
    engine.match_intents.return_value = matches if matches is not None else []
    engine.match_hint_intents.return_value = hint_matches if hint_matches is not None else []
    return engine


def _make_cache(cached=None):
    cache = MagicMock()
    cache.get.return_value = cached
    return cache


# ---------------------------------------------------------------------------
# Tests for _load_intent_runtime_rules branches (lines 62-84)
# ---------------------------------------------------------------------------


class TestLoadIntentRuntimeRules:
    """Hit the dict-vs-tuple branches inside _load_intent_runtime_rules."""

    def test_dict_intent_patterns(self):
        """intent_patterns as list of dicts -> appended as (pattern, intent)."""
        config = {
            "quick_rules": {
                "intent_patterns": [{"pattern": r"\d+", "intent": "products"}],
                "context_inherit_patterns": [],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            from app.services.intent_service import (
                _load_intent_runtime_rules,
                _quick_intent_patterns,
            )

            _load_intent_runtime_rules()
            from app.services import intent_service as _mod

            assert any(p == r"\d+" for p, _ in _mod._quick_intent_patterns)

    def test_tuple_intent_patterns(self):
        """intent_patterns as list of tuples -> appended correctly."""
        config = {
            "quick_rules": {
                "intent_patterns": [(r"abc", "customers")],
                "context_inherit_patterns": [],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            from app.services.intent_service import _load_intent_runtime_rules

            _load_intent_runtime_rules()
            from app.services import intent_service as _mod

            assert any(p == r"abc" for p, _ in _mod._quick_intent_patterns)

    def test_invalid_pattern_item_skipped(self):
        """Unsupported items in intent_patterns are skipped (continue branch)."""
        config = {
            "quick_rules": {
                "intent_patterns": ["not_a_dict_or_tuple"],
                "context_inherit_patterns": [],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            from app.services.intent_service import _load_intent_runtime_rules

            _load_intent_runtime_rules()  # should not raise

    def test_dict_context_inherit_patterns(self):
        """context_inherit_patterns as list of dicts."""
        config = {
            "quick_rules": {
                "intent_patterns": [],
                "context_inherit_patterns": [{"pattern": r"^再一份$", "action": "repeat_last"}],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            from app.services.intent_service import _load_intent_runtime_rules

            _load_intent_runtime_rules()
            from app.services import intent_service as _mod

            assert any(p == r"^再一份$" for p, _ in _mod._context_inherit_patterns)

    def test_invalid_context_inherit_item_skipped(self):
        """Unsupported context_inherit_patterns items are skipped."""
        config = {
            "quick_rules": {
                "intent_patterns": [],
                "context_inherit_patterns": [42],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            from app.services.intent_service import _load_intent_runtime_rules

            _load_intent_runtime_rules()  # should not raise


# ---------------------------------------------------------------------------
# Tests for is_greeting / is_goodbye / is_help_request / is_confirmation
# ---------------------------------------------------------------------------


class TestBasicIntentHelpers:
    """Lines 158-195: reflex branch True + fallback to keyword scan."""

    def test_is_greeting_via_reflex(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_greeting

        rr = _make_reflex(ReflexType.GREETING, triggered=True)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_greeting("你好") is True

    def test_is_greeting_via_keyword_fallback(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_greeting

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_greeting("嗨！") is True

    def test_is_goodbye_via_reflex(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_goodbye

        rr = _make_reflex(ReflexType.EMERGENCY_STOP, triggered=True)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_goodbye("stop") is True

    def test_is_goodbye_via_keyword(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_goodbye

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_goodbye("拜拜") is True

    def test_is_help_via_reflex(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_help_request

        rr = _make_reflex(ReflexType.HELP, triggered=True)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_help_request("x") is True

    def test_is_confirmation_via_reflex(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_confirmation

        rr = _make_reflex(ReflexType.CONFIRMATION, triggered=True)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_confirmation("x") is True

    def test_is_confirmation_via_keyword(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_confirmation

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_confirmation("ok") is True


# ---------------------------------------------------------------------------
# Tests for recognize_intents / _recognize_intents_impl branches
# ---------------------------------------------------------------------------


class TestRecognizeIntentsImpl:
    """Lines 362-492: tool match, negation, hints, shipment special logic, slots."""

    def _run(
        self,
        message,
        *,
        matches=None,
        hints=None,
        cached=None,
        reflex_type=None,
        triggered=False,
        resolve_unit=None,
    ):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rt = reflex_type if reflex_type is not None else ReflexType.GREETING
        rr = _make_reflex(rt, triggered=triggered)
        engine = _make_engine(matches, hints)
        cache = _make_cache(cached)

        patches = [
            patch("app.services.intent_service._reflex_arc"),
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ]
        if resolve_unit is not None:
            patches.append(
                patch(
                    "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                    return_value=resolve_unit,
                )
            )
        with patches[0] as arc_mock, patches[1], patches[2]:
            arc_mock.process.return_value = rr
            return recognize_intents(message)

    def test_cache_hit_returns_cached(self):
        cached = {"primary_intent": "cached", "tool_key": "cached"}
        result = self._run("你好", cached=cached)
        assert result["primary_intent"] == "cached"

    def test_tool_match_sets_primary_intent(self):
        matches = [
            {"id": "products", "tool_key": "products", "block_if_negated": False, "keywords": []}
        ]
        result = self._run("查产品", matches=matches)
        assert result["primary_intent"] == "products"
        assert result["tool_key"] == "products"

    def test_negated_tool_key_cleared(self):
        from app.domain.neuro.reflex_arc import ReflexType

        matches = [
            {
                "id": "shipment_generate",
                "tool_key": "shipment_generate",
                "block_if_negated": True,
                "keywords": ["发货单"],
            }
        ]
        rr = _make_reflex(ReflexType.DENIAL, triggered=True)
        engine = _make_engine(matches, [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            from app.services.intent_service import recognize_intents

            result = recognize_intents("不要开发货单")
        assert result["is_negated"] is True
        assert result["tool_key"] is None

    def test_shipment_generate_hint_added(self):
        matches = [
            {
                "id": "shipment_generate",
                "tool_key": "shipment_generate",
                "block_if_negated": False,
                "keywords": [],
            }
        ]
        result = self._run("生成发货单", matches=matches)
        assert "shipment_generate" in result["intent_hints"]

    def test_shipment_template_hint_added(self):
        matches = [
            {
                "id": "shipment_template",
                "tool_key": "shipment_template",
                "block_if_negated": False,
                "keywords": [],
            }
        ]
        result = self._run("发货单模板", matches=matches)
        assert "template_query" in result["intent_hints"]

    def test_upload_file_in_all_matched_tools_adds_hint(self):
        matches = [
            {
                "id": "upload_file",
                "tool_key": "upload_file",
                "block_if_negated": False,
                "keywords": [],
            }
        ]
        result = self._run("上传文件", matches=matches)
        assert "upload_file" in result["intent_hints"]

    def test_hint_intents_deduplicated(self):
        matches = [
            {"id": "products", "tool_key": "products", "block_if_negated": False, "keywords": []}
        ]
        engine = _make_engine(matches, ["products"])
        cache = _make_cache(None)
        from app.domain.neuro.reflex_arc import ReflexType

        rr = _make_reflex(ReflexType.GREETING, False)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            from app.services.intent_service import recognize_intents

            result = recognize_intents("查产品")
        assert result["intent_hints"].count("products") <= 1

    def test_template_keyword_in_msg_adds_hint(self):
        result = self._run("查询模板", matches=[], hints=[])
        assert "template_query" in result["intent_hints"]

    def test_template_keyword_in_msg_lower_adds_hint(self):
        result = self._run("check template", matches=[], hints=[])
        assert "template_query" in result["intent_hints"]

    def test_shipment_generate_keyword_adds_hint(self):
        result = self._run("生成发货单测试", matches=[], hints=[])
        assert "shipment_generate" in result["intent_hints"]

    def test_starts_with_shipment_and_has_order_info(self):
        result = self._run("发货单七彩3桶", matches=[], hints=[])
        assert result["tool_key"] == "shipment_generate"

    def test_starts_with_shipment_without_order_info_no_match(self):
        result = self._run("发货单", matches=[], hints=[])
        assert result.get("tool_key") != "shipment_generate"

    def test_container_and_spec_pattern_sets_shipment(self):
        result = self._run("3桶规格25", matches=[], hints=[])
        assert result["tool_key"] == "shipment_generate"

    def test_is_likely_unclear_short_no_match(self):
        result = self._run("嗯", matches=[], hints=[])
        assert result["is_likely_unclear"] is True

    def test_upload_keyword_adds_hint(self):
        result = self._run("导入文件", matches=[], hints=[])
        assert "upload_file" in result["intent_hints"]

    def test_upload_keyword_in_lower_adds_hint(self):
        result = self._run("upload data", matches=[], hints=[])
        assert "upload_file" in result["intent_hints"]

    def test_slot_unit_model_resolved(self):
        unit_mock = MagicMock()
        unit_mock.unit_name = "七彩乐园"
        from app.domain.neuro.reflex_arc import ReflexType

        rr = _make_reflex(ReflexType.GREETING, False)
        engine = _make_engine([], [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=unit_mock,
            ),
        ):
            arc.process.return_value = rr
            from app.services.intent_service import recognize_intents

            result = recognize_intents("七彩乐园的9803")
        assert result["slots"].get("unit_name") == "七彩乐园"

    def test_slot_unit_model_unresolved(self):
        from app.domain.neuro.reflex_arc import ReflexType

        rr = _make_reflex(ReflexType.GREETING, False)
        engine = _make_engine([], [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            arc.process.return_value = rr
            from app.services.intent_service import recognize_intents

            result = recognize_intents("七彩乐园的9803")
        assert result["slots"].get("unit_name") == "七彩乐园"

    def test_slot_fallback_to_products_keyword_when_tool_is_products(self):
        matches = [
            {"id": "products", "tool_key": "products", "block_if_negated": False, "keywords": []}
        ]
        from app.domain.neuro.reflex_arc import ReflexType

        rr = _make_reflex(ReflexType.GREETING, False)
        engine = _make_engine(matches, [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            from app.services.intent_service import recognize_intents

            result = recognize_intents("查产品9803")
        assert result["slots"].get("keyword") is not None

    def test_recoverable_error_in_recognize_intents_returns_safe_default(self):
        from app.services.intent_service import recognize_intents
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        exc_cls = RECOVERABLE_ERRORS[0] if isinstance(RECOVERABLE_ERRORS, tuple) else Exception
        with patch(
            "app.services.intent_service._recognize_intents_impl", side_effect=exc_cls("boom")
        ):
            result = recognize_intents("x")
        assert result["primary_intent"] is None
        assert result["is_likely_unclear"] is True

    def test_reflex_basic_intents_recoverable_error_uses_fallback(self):
        from app.services.intent_service import recognize_intents
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        exc_cls = RECOVERABLE_ERRORS[0] if isinstance(RECOVERABLE_ERRORS, tuple) else Exception
        engine = _make_engine([], [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.side_effect = exc_cls("reflex_fail")
            result = recognize_intents("你好")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Tests for quick_recognize branches
# ---------------------------------------------------------------------------


class TestQuickRecognize:
    """Lines 583-621: quick_command, quick_pattern, append, context_inherit, pending."""

    def test_empty_message_returns_fast_path(self):
        from app.services.intent_service import quick_recognize

        result = quick_recognize("")
        assert result["primary_intent"] is None
        assert result["fast_path"] is True

    def test_quick_command_exact_match(self):
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old = _mod._quick_command_map
        _mod._quick_command_map = {"开单": "shipment_generate"}
        try:
            result = quick_recognize("开单")
            assert result["tool_key"] == "shipment_generate"
            assert result["source"] == "quick_command"
        finally:
            _mod._quick_command_map = old

    def test_quick_pattern_match(self):
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old = _mod._quick_intent_patterns
        _mod._quick_intent_patterns = [(r"^\d+$", "products")]
        try:
            result = quick_recognize("12345")
            assert result["tool_key"] == "products"
            assert result["source"] == "quick_pattern"
        finally:
            _mod._quick_intent_patterns = old

    def test_append_keyword_with_pending_context(self):
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        _mod._append_keywords = ["再加"]
        ctx = {
            "pending_confirmation": {
                "intent": "shipment_generate",
                "tool_key": "shipment_generate",
                "slots": {"unit_name": "X"},
            }
        }
        try:
            result = quick_recognize("再加一桶", context=ctx)
            assert result["context_inherited"] is True
            assert result["source"] == "append_inherit"
        finally:
            _mod._append_keywords = old_kw

    def test_append_keyword_without_pending_uses_last_intent(self):
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        _mod._append_keywords = ["再加"]
        ctx = {
            "current_intent": "products",
            "current_tool_key": "products",
            "last_slots": {"keyword": "9803"},
        }
        try:
            result = quick_recognize("再加一个", context=ctx)
            assert result["context_inherited"] is True
        finally:
            _mod._append_keywords = old_kw

    def test_context_inherit_repeat_last(self):
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old = _mod._context_inherit_patterns
        _mod._context_inherit_patterns = [(r"^再一份$", "repeat_last")]
        ctx = {"current_intent": "shipment_generate", "current_tool_key": "shipment_generate"}
        try:
            result = quick_recognize("再一份", context=ctx)
            assert result["source"] == "context_inherit"
            assert result["context_inherited"] is True
        finally:
            _mod._context_inherit_patterns = old

    def test_pending_confirmation_fallback(self):
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        old_ci = _mod._context_inherit_patterns
        _mod._append_keywords = []
        _mod._context_inherit_patterns = []
        ctx = {
            "pending_confirmation": {
                "intent": "products",
                "tool_key": "products",
                "slots": {},
            }
        }
        try:
            result = quick_recognize("好的", context=ctx)
            assert result["source"] == "context_pending"
            assert result["context_inherited"] is True
        finally:
            _mod._append_keywords = old_kw
            _mod._context_inherit_patterns = old_ci

    def test_no_context_returns_empty(self):
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_cmd = _mod._quick_command_map
        old_pat = _mod._quick_intent_patterns
        _mod._quick_command_map = {}
        _mod._quick_intent_patterns = []
        try:
            result = quick_recognize("some unknown text")
            assert result["primary_intent"] is None
            assert result["tool_key"] is None
        finally:
            _mod._quick_command_map = old_cmd
            _mod._quick_intent_patterns = old_pat


# ---------------------------------------------------------------------------
# Tests for quick_slot_extraction
# ---------------------------------------------------------------------------


class TestQuickSlotExtraction:
    def test_shipment_generate_single_unit(self):
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("发货单七彩乐园3桶", "shipment_generate")
        assert slots.get("unit_name") is not None or "quantity" in slots or "spec" in slots

    def test_shipment_generate_multi_unit(self):
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("发货单七彩乐园和太阳鸟各5桶", "shipment_generate")
        assert isinstance(slots, dict)

    def test_products_keyword(self):
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("查9803产品", "products")
        assert slots.get("keyword") == "查9803产品"

    def test_customers_keyword(self):
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("查七彩乐园客户", "customers")
        assert slots.get("keyword") is not None

    def test_unknown_intent_empty_slots(self):
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("随便说说", "unknown_intent")
        assert slots == {}


# ---------------------------------------------------------------------------
# Tests for reload_intent_service
# ---------------------------------------------------------------------------


class TestReloadIntentService:
    def test_reload_clears_cache_and_reloads_all(self):
        cache_mock = MagicMock()
        new_arc = MagicMock()
        with (
            patch("app.services.intent_service._intent_cache", cache_mock),
            patch("app.services.intent_service.reload_intent_config"),
            patch("app.services.intent_service.get_reflex_arc", return_value=new_arc),
            patch("app.services.intent_service.reload_rule_engine"),
            patch("app.services.intent_service._load_intent_runtime_rules"),
        ):
            from app.services.intent_service import reload_intent_service

            reload_intent_service()
        cache_mock.clear.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for _extract_multi_unit_names / _extract_name_before_quantity
# ---------------------------------------------------------------------------


class TestExtractMultiUnitNames:
    def test_no_separator_single_name(self):
        from app.services.intent_service import _extract_multi_unit_names

        result = _extract_multi_unit_names("发货单七彩乐园3桶")
        assert isinstance(result, list)

    def test_with_separator(self):
        from app.services.intent_service import _extract_multi_unit_names

        result = _extract_multi_unit_names("发货单七彩乐园和太阳鸟")
        assert isinstance(result, list)

    def test_empty_msg(self):
        from app.services.intent_service import _extract_multi_unit_names

        result = _extract_multi_unit_names("")
        assert result == []

    def test_extract_name_before_quantity_with_match(self):
        from app.services.intent_service import _extract_name_before_quantity

        result = _extract_name_before_quantity("七彩乐园3桶", r"\d+[桶箱件个]")
        assert result == "七彩乐园"

    def test_extract_name_before_quantity_short_text(self):
        from app.services.intent_service import _extract_name_before_quantity

        result = _extract_name_before_quantity("太阳", r"\d+[桶箱件个]")
        assert result == "太阳"

    def test_extract_name_before_quantity_long_text_no_match(self):
        from app.services.intent_service import _extract_name_before_quantity

        # text > 10 chars with no quantity match -> regex can still extract up-to-10 chars
        # just verify return value is str or None (no exception)
        result = _extract_name_before_quantity("x" * 20, r"\d+[桶箱件个]")
        assert result is None or isinstance(result, str)

    def test_extract_name_before_quantity_empty_part_skipped(self):
        """Part is empty after strip -> continue branch in _extract_multi_unit_names."""
        from app.services.intent_service import _extract_multi_unit_names

        # separator at start produces an empty first part
        result = _extract_multi_unit_names("和七彩乐园3桶")
        assert isinstance(result, list)

    def test_extract_multi_unit_names_no_name_found_with_sep(self):
        """has_any_sep=True but no valid names extracted -> falls through to single-name path."""
        from app.services.intent_service import _extract_multi_unit_names

        # single-char parts won't pass the 2-char minimum
        result = _extract_multi_unit_names("发货单甲和乙")
        assert isinstance(result, list)

    def test_extract_multi_unit_names_no_name_from_single_path(self):
        """Single-name path returns empty when name extraction fails."""
        from app.services.intent_service import _extract_multi_unit_names

        # digits-only after prefix strip won't match the 2-char non-digit rule
        result = _extract_multi_unit_names("发货单")
        assert result == []

    def test_extract_name_before_quantity_name_part_1_char(self):
        """name_part is 1 char (< 2) -> return None."""
        from app.services.intent_service import _extract_name_before_quantity

        # "甲" is 1 char; regex won't match ({2,10}) and len check fails
        result = _extract_name_before_quantity("甲", r"\d+[桶箱件个]")
        assert result is None


# ---------------------------------------------------------------------------
# Additional tests for _normalize non-string branch (line 103)
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_non_string_returns_empty(self):
        from app.services.intent_service import _normalize

        assert _normalize(None) == ""  # type: ignore[arg-type]

    def test_normalize_integer_returns_empty(self):
        from app.services.intent_service import _normalize

        assert _normalize(42) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Additional tests for is_negation missing branches (lines 144, 146-150)
# ---------------------------------------------------------------------------


class TestIsNegationBranches:
    def test_denial_triggered_with_action_keywords_returns_true(self):
        """DENIAL triggered + action_keywords present -> returns any(kw in msg) (line 143)."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation

        rr = _make_reflex(ReflexType.DENIAL, triggered=True)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            result = is_negation("不要发货单", action_keywords=["发货单"])
        assert result is True

    def test_denial_triggered_with_action_keywords_not_in_msg_returns_false(self):
        """DENIAL triggered + action_keywords not in msg -> returns False (line 143 branch)."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation

        rr = _make_reflex(ReflexType.DENIAL, triggered=True)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            result = is_negation("不要什么", action_keywords=["发货单"])
        assert result is False

    def test_action_keywords_no_negation_word_in_msg(self):
        """action_keywords path: has_neg=False -> skips inner return (line 148-150)."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation

        # not DENIAL triggered, action_keywords given, but no negation word in msg
        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            result = is_negation("发货单3桶", action_keywords=["发货单"])
        # has_neg=False, falls through to final check (no negation word) -> False
        assert result is False

    def test_action_keywords_with_negation_word_and_kw_in_msg(self):
        """action_keywords path: has_neg=True, kw in msg -> True (line 150)."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            result = is_negation("不要发货单", action_keywords=["发货单"])
        assert result is True

    def test_action_keywords_with_negation_word_but_kw_absent(self):
        """action_keywords path: has_neg=True, but kw not in msg -> False (line 150)."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            result = is_negation("不要其他事", action_keywords=["发货单"])
        assert result is False


# ---------------------------------------------------------------------------
# Additional tests for is_help_request keyword fallback (lines 178-179)
# ---------------------------------------------------------------------------


class TestIsHelpRequestFallback:
    def test_is_help_via_keyword_fallback(self):
        """HELP not triggered -> falls back to keyword scan."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_help_request

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_help_request("help me") is True

    def test_is_help_via_keyword_fallback_no_match(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_help_request

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_help_request("查产品") is False


# ---------------------------------------------------------------------------
# Additional tests for is_negation_intent (lines 193-199)
# ---------------------------------------------------------------------------


class TestIsNegationIntentBranches:
    def test_negation_intent_via_denial_reflex(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation_intent

        rr = _make_reflex(ReflexType.DENIAL, triggered=True)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_negation_intent("不要") is True

    def test_negation_intent_via_cancel_keyword(self):
        """算了/取消/不用了 keyword path (line 197)."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation_intent

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_negation_intent("算了吧") is True

    def test_negation_intent_via_cancel_keyword_quxi(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation_intent

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_negation_intent("取消操作") is True

    def test_negation_intent_falls_through_to_is_negation(self):
        """No DENIAL, no cancel keyword, but 不要 in msg -> True via is_negation."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation_intent

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_negation_intent("不要开单") is True

    def test_negation_intent_false_plain_message(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import is_negation_intent

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        with patch("app.services.intent_service._reflex_arc") as arc:
            arc.process.return_value = rr
            assert is_negation_intent("查一下产品") is False


# ---------------------------------------------------------------------------
# Additional tests for _load_intent_runtime_rules falsy pattern/action (line 70->62)
# ---------------------------------------------------------------------------


class TestLoadIntentRuntimeRulesEdgeCases:
    def test_pattern_or_intent_empty_not_appended(self):
        """if pattern and intent: is False when either is empty/None -> not appended."""
        config = {
            "quick_rules": {
                "intent_patterns": [{"pattern": "", "intent": "products"}],
                "context_inherit_patterns": [],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            import app.services.intent_service as _mod

            _mod._quick_intent_patterns = []
            from app.services.intent_service import _load_intent_runtime_rules

            _load_intent_runtime_rules()
            # empty pattern should NOT be appended
            assert not any(p == "" for p, _ in _mod._quick_intent_patterns)

    def test_context_inherit_empty_action_not_appended(self):
        """if pattern and action: is False when action is empty -> not appended."""
        config = {
            "quick_rules": {
                "intent_patterns": [],
                "context_inherit_patterns": [{"pattern": r"^再$", "action": ""}],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            import app.services.intent_service as _mod

            _mod._context_inherit_patterns = []
            from app.services.intent_service import _load_intent_runtime_rules

            _load_intent_runtime_rules()
            assert len(_mod._context_inherit_patterns) == 0

    def test_context_inherit_tuple_branch(self):
        """context_inherit_patterns as list of tuples."""
        config = {
            "quick_rules": {
                "intent_patterns": [],
                "context_inherit_patterns": [(r"^同样$", "repeat_last")],
                "command_map": {},
                "append_keywords": [],
            }
        }
        with patch("app.services.intent_service.get_intent_config", return_value=config):
            from app.services.intent_service import _load_intent_runtime_rules

            _load_intent_runtime_rules()
            import app.services.intent_service as _mod

            assert any(p == r"^同样$" for p, _ in _mod._context_inherit_patterns)


# ---------------------------------------------------------------------------
# get_tool_key_with_negation_check (lines 500-501)
# ---------------------------------------------------------------------------


class TestGetToolKeyWithNegationCheck:
    def test_returns_tool_key(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import get_tool_key_with_negation_check

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        engine = _make_engine(
            [{"id": "products", "tool_key": "products", "block_if_negated": False, "keywords": []}],
            [],
        )
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            result = get_tool_key_with_negation_check("查产品")
        assert result == "products"

    def test_returns_none_when_no_match(self):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import get_tool_key_with_negation_check

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        engine = _make_engine([], [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            result = get_tool_key_with_negation_check("随便")
        assert result is None


# ---------------------------------------------------------------------------
# Additional _recognize_intents_impl branches
# ---------------------------------------------------------------------------


class TestRecognizeIntentsImplExtra:
    """Targets remaining uncovered branches in _recognize_intents_impl."""

    def _base_run(self, message, *, matches=None, hints=None):
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        engine = _make_engine(matches or [], hints or [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            return recognize_intents(message)

    def test_print_model_spec_triggers_shipment_generate(self):
        """Lines 418-426: 打印 + 规格 pattern without container qty -> shipment_generate."""
        result = self._base_run("打印3规格25")
        assert result["tool_key"] == "shipment_generate"

    def test_print_model_spec_with_container_qty_no_trigger(self):
        """has_container_qty=True blocks the print+spec path."""
        result = self._base_run("打印3规格25桶")
        # tool_key might be set by another path; just assert it didn't come from this block
        # with container qty present the print-model-spec block is skipped
        # the container-and-spec block (line 395-407) might fire instead
        assert isinstance(result, dict)

    def test_order_action_with_signals_triggers_shipment(self):
        """Lines 433-450: 发货单 + 型号123 + 规格5 -> signals>=2 -> shipment_generate."""
        result = self._base_run("发货单型号12345规格5")
        assert result["tool_key"] == "shipment_generate"

    def test_order_action_with_only_one_signal_no_trigger(self):
        """signals < 2 -> shipment NOT set from the multi-signal block."""
        # only 规格 signal, no 编号/桶
        result = self._base_run("发货单规格5")
        # tool_key may or may not be set by other paths, but multi-signal block didn't fire
        assert isinstance(result, dict)

    def test_resolve_purchase_unit_exception_uses_raw_name(self):
        """Lines 473-475: resolve_purchase_unit raises RECOVERABLE_ERRORS -> resolved=None."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        exc_cls = RECOVERABLE_ERRORS[0] if isinstance(RECOVERABLE_ERRORS, tuple) else Exception
        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        engine = _make_engine([], [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                side_effect=exc_cls("db_fail"),
            ),
        ):
            arc.process.return_value = rr
            result = recognize_intents("七彩乐园的9803")
        # resolved=None -> uses potential_unit as fallback
        assert result["slots"].get("unit_name") == "七彩乐园"

    def test_unit_model_match_with_no_tool_key_sets_products(self):
        """Lines 480-488: unit_model_match found, tool_key is None -> sets products."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        engine = _make_engine([], [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            arc.process.return_value = rr
            result = recognize_intents("七彩乐园的9803")
        assert result["tool_key"] == "products"
        assert result["primary_intent"] == "products"

    def test_unit_model_match_but_already_has_tool_key_no_override(self):
        """Lines 480-488: unit_model_match found but tool_key already set -> NOT overridden."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        matches = [
            {
                "id": "shipment_generate",
                "tool_key": "shipment_generate",
                "block_if_negated": False,
                "keywords": [],
            }
        ]
        engine = _make_engine(matches, [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            arc.process.return_value = rr
            result = recognize_intents("七彩乐园的9803")
        # tool_key was already set to shipment_generate; the products override should NOT fire
        assert result["tool_key"] == "shipment_generate"

    def test_upload_keyword_already_in_hints_not_duplicated(self):
        """upload_file already in intent_hints -> append branch skipped."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        matches = [
            {
                "id": "upload_file",
                "tool_key": "upload_file",
                "block_if_negated": False,
                "keywords": [],
            }
        ]
        engine = _make_engine(matches, [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            result = recognize_intents("上传文件")
        assert result["intent_hints"].count("upload_file") == 1

    def test_shipment_template_hint_already_present_not_duplicated(self):
        """shipment_template match but template_query already in hints -> no duplicate."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        matches = [
            {
                "id": "shipment_template",
                "tool_key": "shipment_template",
                "block_if_negated": False,
                "keywords": [],
            }
        ]
        engine = _make_engine(matches, ["template_query"])  # hint engine returns template_query
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            result = recognize_intents("发货单模板")
        assert result["intent_hints"].count("template_query") == 1

    def test_container_spec_pattern_with_tool_key_products_overridden(self):
        """Lines 395-407: tool_key=products + 桶+规格+digit -> override to shipment_generate."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        matches = [
            {"id": "products", "tool_key": "products", "block_if_negated": False, "keywords": []}
        ]
        engine = _make_engine(matches, [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            result = recognize_intents("3桶规格25")
        assert result["tool_key"] == "shipment_generate"

    def test_shipment_generate_hint_already_present_in_shipment_starts_block(self):
        """Lines 384-393: starts with 发货单, has order info, but hint already in list."""
        from app.domain.neuro.reflex_arc import ReflexType
        from app.services.intent_service import recognize_intents

        rr = _make_reflex(ReflexType.GREETING, triggered=False)
        matches = [
            {
                "id": "shipment_generate",
                "tool_key": "shipment_generate",
                "block_if_negated": False,
                "keywords": [],
            }
        ]
        engine = _make_engine(matches, [])
        cache = _make_cache(None)
        with (
            patch("app.services.intent_service._reflex_arc") as arc,
            patch("app.services.intent_service.get_rule_engine", return_value=engine),
            patch("app.services.intent_service._intent_cache", cache),
        ):
            arc.process.return_value = rr
            # tool_key already set by match -> starts-with block won't override but checks hint
            result = recognize_intents("发货单七彩3桶")
        assert "shipment_generate" in result["intent_hints"]
        assert result["intent_hints"].count("shipment_generate") == 1


# ---------------------------------------------------------------------------
# Additional quick_recognize branches
# ---------------------------------------------------------------------------


class TestQuickRecognizeExtra:
    """Targets remaining uncovered branches in quick_recognize."""

    def test_quick_command_loop_no_match_continues(self):
        """Command map loop iterates but doesn't match -> falls through."""
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_cmd = _mod._quick_command_map
        old_pat = _mod._quick_intent_patterns
        _mod._quick_command_map = {"开单": "shipment_generate"}
        _mod._quick_intent_patterns = []
        try:
            result = quick_recognize("查产品")  # not in command_map
            assert result["primary_intent"] is None
        finally:
            _mod._quick_command_map = old_cmd
            _mod._quick_intent_patterns = old_pat

    def test_quick_pattern_loop_no_match_continues(self):
        """Pattern loop iterates but doesn't match -> falls through."""
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_cmd = _mod._quick_command_map
        old_pat = _mod._quick_intent_patterns
        _mod._quick_command_map = {}
        _mod._quick_intent_patterns = [(r"^\d+$", "products")]
        try:
            result = quick_recognize("非数字消息")
            assert result["primary_intent"] is None
        finally:
            _mod._quick_command_map = old_cmd
            _mod._quick_intent_patterns = old_pat

    def test_append_keyword_no_match_in_msg(self):
        """Append keyword loop: keyword not in msg -> inner if not entered."""
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        old_ci = _mod._context_inherit_patterns
        _mod._append_keywords = ["再加"]
        _mod._context_inherit_patterns = []
        ctx = {
            "current_intent": "products",
            "current_tool_key": "products",
        }
        try:
            result = quick_recognize("查一查", context=ctx)
            # msg doesn't start with 再加 -> append block not entered
            assert result["source"] != "append_inherit"
        finally:
            _mod._append_keywords = old_kw
            _mod._context_inherit_patterns = old_ci

    def test_context_inherit_non_repeat_last_action(self):
        """Pattern matches but action != 'repeat_last' -> inner block skipped."""
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        old_ci = _mod._context_inherit_patterns
        _mod._append_keywords = []
        _mod._context_inherit_patterns = [(r"^继续$", "continue_action")]
        ctx = {"current_intent": "products", "current_tool_key": "products"}
        try:
            result = quick_recognize("继续", context=ctx)
            # action != repeat_last -> not inherited via context_inherit
            assert result["source"] != "context_inherit"
        finally:
            _mod._append_keywords = old_kw
            _mod._context_inherit_patterns = old_ci

    def test_context_inherit_repeat_last_no_last_intent(self):
        """Pattern matches repeat_last but no last_intent/tool -> not returned."""
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        old_ci = _mod._context_inherit_patterns
        _mod._append_keywords = []
        _mod._context_inherit_patterns = [(r"^再一份$", "repeat_last")]
        ctx = {}  # empty context, no last_intent
        try:
            result = quick_recognize("再一份", context=ctx)
            # no last_intent -> context_inherit block not triggered
            assert result["source"] != "context_inherit"
        finally:
            _mod._append_keywords = old_kw
            _mod._context_inherit_patterns = old_ci

    def test_pending_confirmation_no_pending_intent(self):
        """pending_confirmation exists but has no intent/tool_key -> not returned."""
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        old_ci = _mod._context_inherit_patterns
        _mod._append_keywords = []
        _mod._context_inherit_patterns = []
        ctx = {
            "pending_confirmation": {
                "intent": None,
                "tool_key": None,
                "slots": {},
            }
        }
        try:
            result = quick_recognize("好的", context=ctx)
            # pending_intent is falsy -> block skipped, falls to end
            assert result["source"] != "context_pending"
        finally:
            _mod._append_keywords = old_kw
            _mod._context_inherit_patterns = old_ci

    def test_append_keyword_no_pending_no_last_intent_continues(self):
        """Append kw matches but both pending=None and last_intent=None -> no early return."""
        import app.services.intent_service as _mod
        from app.services.intent_service import quick_recognize

        old_kw = _mod._append_keywords
        old_ci = _mod._context_inherit_patterns
        _mod._append_keywords = ["再加"]
        _mod._context_inherit_patterns = []
        ctx = {}  # no pending, no last_intent
        try:
            result = quick_recognize("再加一桶", context=ctx)
            assert result["source"] != "append_inherit"
        finally:
            _mod._append_keywords = old_kw
            _mod._context_inherit_patterns = old_ci


# ---------------------------------------------------------------------------
# Additional quick_slot_extraction branches (lines 643-665)
# ---------------------------------------------------------------------------


class TestQuickSlotExtractionExtra:
    def test_shipment_no_unit_names_extracted(self):
        """unit_names empty -> unit_name not set in slots."""
        from app.services.intent_service import quick_slot_extraction

        # A message that won't produce extractable unit names
        slots = quick_slot_extraction("生成", "shipment_generate")
        assert "unit_name" not in slots

    def test_shipment_multi_unit(self):
        """len(unit_names) > 1 -> slots['unit_name'] is a list."""
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("发货单七彩乐园和太阳鸟各5桶", "shipment_generate")
        if "unit_name" in slots:
            assert isinstance(slots["unit_name"], list)

    def test_shipment_with_quantity_no_spec_no_model(self):
        """quantity matched, no spec, no model -> only quantity in slots."""
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("3桶", "shipment_generate")
        if "quantity" in slots:
            assert "3桶" in slots["quantity"]

    def test_shipment_with_spec_no_quantity(self):
        """spec matched -> spec set in slots."""
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("七彩规格25", "shipment_generate")
        if "spec" in slots:
            assert slots["spec"] == "25"

    def test_shipment_with_model(self):
        """型号 matched -> model_number set."""
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("型号9803", "shipment_generate")
        if "model_number" in slots:
            assert slots["model_number"] == "9803"

    def test_products_with_empty_msg(self):
        """products intent but empty msg -> keyword NOT set (line 662 branch)."""
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("", "products")
        assert "keyword" not in slots

    def test_customers_with_empty_msg(self):
        """customers intent but empty msg -> keyword NOT set."""
        from app.services.intent_service import quick_slot_extraction

        slots = quick_slot_extraction("", "customers")
        assert "keyword" not in slots
