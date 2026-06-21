"""Coverage tests for app/services/intent_confirmation_service.py.

Targets missing branches: check_missing_slots, generate_followup_question,
build_slot_fill_prompt, IntentConfirmationService methods, and get_confirmation_service.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.intent_confirmation_service import (
    FALLBACK_QUESTIONS,
    INTENT_REQUIRED_SLOTS,
    IntentConfirmationService,
    build_slot_fill_prompt,
    check_missing_slots,
    generate_followup_question,
    get_confirmation_service,
)

# ---------------------------------------------------------------------------
# check_missing_slots
# ---------------------------------------------------------------------------


class TestCheckMissingSlots:
    def test_unknown_intent_returns_empty(self):
        result = check_missing_slots("nonexistent_intent", {"some_slot": "val"})
        assert result == []

    def test_all_required_slots_present(self):
        result = check_missing_slots("shipment_generate", {"unit_name": "Acme"})
        assert result == []

    def test_missing_required_slot(self):
        result = check_missing_slots("shipment_generate", {})
        assert "unit_name" in result

    def test_empty_string_slot_counts_as_missing(self):
        result = check_missing_slots("shipment_generate", {"unit_name": ""})
        assert "unit_name" in result

    def test_whitespace_only_slot_counts_as_missing(self):
        result = check_missing_slots("shipment_generate", {"unit_name": "   "})
        assert "unit_name" in result

    def test_none_slot_value_counts_as_missing(self):
        result = check_missing_slots("shipment_generate", {"unit_name": None})
        assert "unit_name" in result

    def test_intent_with_no_required_slots(self):
        # "materials" has no required slots
        result = check_missing_slots("materials", {})
        assert result == []

    def test_customer_edit_missing_unit_name(self):
        result = check_missing_slots("customer_edit", {})
        assert "unit_name" in result

    def test_wechat_send_missing_unit_name(self):
        result = check_missing_slots("wechat_send", {})
        assert "unit_name" in result

    def test_print_label_missing_unit_name(self):
        result = check_missing_slots("print_label", {})
        assert "unit_name" in result


# ---------------------------------------------------------------------------
# generate_followup_question
# ---------------------------------------------------------------------------


class TestGenerateFollowupQuestion:
    def test_known_intent_known_slot(self):
        question = generate_followup_question("shipment_generate", ["unit_name"])
        assert "购买单位" in question

    def test_known_intent_multiple_slots(self):
        question = generate_followup_question("shipment_generate", ["unit_name", "quantity_tins"])
        assert "购买单位" in question or "多少桶" in question

    def test_known_intent_slot_not_in_prompts(self):
        # missing_slots contains a slot key not in prompts dict — falls through to fallback
        question = generate_followup_question("shipment_generate", ["nonexistent_slot"])
        assert question  # should return fallback or default string

    def test_fallback_question_used_when_no_prompt_match(self):
        question = generate_followup_question("shipment_generate", ["nonexistent_slot"])
        assert question == FALLBACK_QUESTIONS.get("shipment_generate", "请提供更多信息？")

    def test_unknown_intent_returns_default(self):
        question = generate_followup_question("unknown_intent", ["some_slot"])
        assert question == "请提供更多信息？"

    def test_empty_missing_slots_uses_fallback(self):
        # no slots -> questions list empty -> fall through to FALLBACK_QUESTIONS
        question = generate_followup_question("shipment_generate", [])
        assert question == FALLBACK_QUESTIONS["shipment_generate"]


# ---------------------------------------------------------------------------
# build_slot_fill_prompt
# ---------------------------------------------------------------------------


class TestBuildSlotFillPrompt:
    def test_returns_dict_with_required_keys(self):
        result = build_slot_fill_prompt("shipment_generate", {}, ["unit_name"])
        assert "intent" in result
        assert "missing_slots" in result
        assert "current_slots" in result
        assert "questions" in result
        assert "question_text" in result

    def test_known_intent_populates_prompts(self):
        result = build_slot_fill_prompt("shipment_generate", {}, ["unit_name"])
        assert "unit_name" in result["questions"]

    def test_unknown_intent_gives_empty_questions(self):
        result = build_slot_fill_prompt("no_such_intent", {}, ["slot_x"])
        assert result["questions"] == {}

    def test_slot_not_in_prompts_uses_slot_name(self):
        result = build_slot_fill_prompt("shipment_generate", {}, ["mystery_field"])
        assert result["questions"]["mystery_field"] == "mystery_field"

    def test_current_slots_passed_through(self):
        slots = {"unit_name": "Acme", "quantity_tins": "10"}
        result = build_slot_fill_prompt("shipment_generate", slots, [])
        assert result["current_slots"] == slots


# ---------------------------------------------------------------------------
# IntentConfirmationService.check_and_build_prompt
# ---------------------------------------------------------------------------


class TestIntentConfirmationServiceCheckAndBuild:
    def setup_method(self):
        self.svc = IntentConfirmationService()

    def test_unclear_intent_no_field(self):
        result = self.svc.check_and_build_prompt({})
        assert result["status"] == "unclear"
        assert result["intent"] is None

    def test_unclear_intent_unk_value(self):
        result = self.svc.check_and_build_prompt({"final_intent": "unk"})
        assert result["status"] == "unclear"

    def test_final_intent_takes_priority(self):
        result = self.svc.check_and_build_prompt(
            {
                "final_intent": "materials",
                "primary_intent": "something_else",
                "slots": {},
            }
        )
        # "materials" has no required slots -> complete
        assert result["status"] == "complete"
        assert result["intent"] == "materials"

    def test_primary_intent_fallback(self):
        result = self.svc.check_and_build_prompt(
            {
                "primary_intent": "materials",
                "slots": {},
            }
        )
        assert result["status"] == "complete"

    def test_tool_key_fallback(self):
        result = self.svc.check_and_build_prompt(
            {
                "tool_key": "materials",
                "slots": {},
            }
        )
        assert result["status"] == "complete"

    def test_deepseek_intent_fallback(self):
        result = self.svc.check_and_build_prompt(
            {
                "deepseek_intent": "materials",
                "slots": {},
            }
        )
        assert result["status"] == "complete"

    def test_missing_slots_status(self):
        result = self.svc.check_and_build_prompt(
            {
                "final_intent": "shipment_generate",
                "slots": {},
            }
        )
        assert result["status"] == "missing_slots"
        assert "unit_name" in result["missing_slots"]
        assert result["question"]

    def test_complete_with_all_slots(self):
        result = self.svc.check_and_build_prompt(
            {
                "final_intent": "shipment_generate",
                "slots": {"unit_name": "Acme"},
            }
        )
        assert result["status"] == "complete"
        assert result["question"] is None
        assert result["pending_data"]["missing_slots"] == []


# ---------------------------------------------------------------------------
# IntentConfirmationService pending intent management
# ---------------------------------------------------------------------------


class TestPendingIntentManagement:
    def setup_method(self):
        self.svc = IntentConfirmationService()

    def test_set_and_get_pending_intent(self):
        data = {"intent": "shipment_generate", "slots": {}}
        self.svc.set_pending_intent("user1", data)
        assert self.svc.get_pending_intent("user1") == data

    def test_get_nonexistent_returns_none(self):
        assert self.svc.get_pending_intent("ghost_user") is None

    def test_clear_pending_intent(self):
        self.svc.set_pending_intent("user1", {"intent": "x"})
        self.svc.clear_pending_intent("user1")
        assert self.svc.get_pending_intent("user1") is None

    def test_clear_nonexistent_is_safe(self):
        self.svc.clear_pending_intent("does_not_exist")  # should not raise


# ---------------------------------------------------------------------------
# IntentConfirmationService.merge_slots
# ---------------------------------------------------------------------------


class TestMergeSlots:
    def setup_method(self):
        self.svc = IntentConfirmationService()

    def test_no_pending_returns_new_slots(self):
        # No pending intent and no unit_name -> no DB call needed
        merged = self.svc.merge_slots("user1", {"quantity_tins": "5"})
        assert merged == {"quantity_tins": "5"}

    def test_merges_with_existing_slots(self):
        self.svc.set_pending_intent(
            "user1",
            {"intent": "shipment_generate", "slots": {"quantity_tins": "5"}},
        )
        # unit_name triggers resolve_purchase_unit -> mock at the source module
        with patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            merged = self.svc.merge_slots("user1", {"unit_name": "Acme"})
        assert merged["unit_name"] == "Acme"
        assert merged["quantity_tins"] == "5"

    def test_new_slots_override_old(self):
        self.svc.set_pending_intent(
            "user1",
            {"intent": "shipment_generate", "slots": {"unit_name": "OldCo"}},
        )
        with patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            merged = self.svc.merge_slots("user1", {"unit_name": "NewCo"})
        assert merged["unit_name"] == "NewCo"

    def test_unit_name_resolved_when_present(self):
        self.svc.set_pending_intent("user1", {"intent": "shipment_generate", "slots": {}})
        resolved = MagicMock(unit_name="Resolved Corp")
        with patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=resolved,
        ):
            merged = self.svc.merge_slots("user1", {"unit_name": "Corp"})
        assert merged["unit_name"] == "Resolved Corp"

    def test_unit_name_not_resolved_keeps_original(self):
        self.svc.set_pending_intent("user1", {"intent": "shipment_generate", "slots": {}})
        with patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            merged = self.svc.merge_slots("user1", {"unit_name": "Corp"})
        assert merged["unit_name"] == "Corp"


# ---------------------------------------------------------------------------
# get_confirmation_service singleton
# ---------------------------------------------------------------------------


class TestGetConfirmationService:
    def test_returns_instance(self):
        svc = get_confirmation_service()
        assert isinstance(svc, IntentConfirmationService)

    def test_returns_same_singleton(self):
        svc1 = get_confirmation_service()
        svc2 = get_confirmation_service()
        assert svc1 is svc2
