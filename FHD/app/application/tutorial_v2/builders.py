"""Builders shared by the versioned tutorial course definitions."""

from __future__ import annotations

from typing import Any

COURSE_VERSION = 5


def _guide(
    instruction: str,
    target_selector: str = "",
    expected_input: str = "",
) -> dict[str, str]:
    return {
        "instruction": instruction,
        "target_selector": target_selector,
        "expected_input": expected_input,
    }


def _step(
    step_id: str,
    title: str,
    *,
    goal: str,
    instruction: str,
    success: str,
    why: str,
    hint: str,
    route_name: str,
    target_selector: str,
    verifier: str,
    location_label: str,
    completion_cue: str,
    guide_actions: tuple[dict[str, str], ...],
    principle: str = "",
) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": title,
        "goal": goal,
        "instruction": instruction,
        "success_criteria": success,
        "why": why,
        "hint": hint,
        "route_name": route_name,
        "target_selector": target_selector,
        "verifier": verifier,
        "required": True,
        "location_label": location_label,
        "completion_cue": completion_cue,
        "guide_actions": list(guide_actions),
        "action_checklist": [item["instruction"] for item in guide_actions],
        "principle": principle,
    }
