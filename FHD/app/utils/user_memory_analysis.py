"""Read-only analysis helpers for user-memory records."""

from collections import defaultdict
from typing import Any

from app.utils.user_memory_models import UserMemory


def feedback_stats(memory: UserMemory | None) -> dict[str, Any]:
    if not memory:
        return {"total": 0, "confirmed": 0, "negated": 0, "corrected": 0}

    feedback_counts: dict[str, int] = defaultdict(int)
    intent_error_rates: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "errors": 0}
    )
    for record in memory.feedback_history:
        feedback_type = record.get("user_feedback", "unknown")
        feedback_counts[feedback_type] += 1
        recognized = record.get("recognized_intent", "")
        intent_error_rates[recognized]["total"] += 1
        if feedback_type in ("negated", "corrected"):
            intent_error_rates[recognized]["errors"] += 1

    error_rates = {
        intent: round(stats["errors"] / stats["total"], 3)
        for intent, stats in intent_error_rates.items()
        if stats["total"] >= 3
    }
    return {
        "total": len(memory.feedback_history),
        "confirmed": feedback_counts.get("confirmed", 0),
        "negated": feedback_counts.get("negated", 0),
        "corrected": feedback_counts.get("corrected", 0),
        "error_rates": error_rates,
    }


def analyze_action_sequence(memory: UserMemory) -> list[dict[str, Any]]:
    sequences: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0})
    for index in range(len(memory.historical_contexts) - 1):
        current = memory.historical_contexts[index]
        next_context = memory.historical_contexts[index + 1]
        sequence_key = f"{current.get('intent')}->{next_context.get('intent')}"
        sequences[sequence_key]["count"] += 1

    return [
        {
            "actions": sequence_key.split("->"),
            "confidence": min(0.95, stats["count"] * 0.15),
            "count": stats["count"],
        }
        for sequence_key, stats in sequences.items()
        if stats["count"] >= 2
    ]


def habit_suggestions(memory: UserMemory | None) -> list[dict[str, Any]]:
    if not memory:
        return []
    suggestions = []
    for sequence in analyze_action_sequence(memory):
        if sequence["confidence"] >= 0.8 and len(sequence["actions"]) >= 2:
            actions = sequence["actions"]
            suggestions.append(
                {
                    "type": "action_sequence",
                    "actions": actions,
                    "confidence": sequence["confidence"],
                    "suggestion": f"执行 {actions[0]} 后主动提示 {actions[1]}",
                }
            )
    return suggestions


def memory_summary(memory: UserMemory | None) -> dict[str, Any]:
    if not memory:
        return {"has_memory": False}
    return {
        "has_memory": True,
        "preference_count": len(memory.preferences),
        "action_count": len(memory.frequent_actions),
        "feedback_count": len(memory.feedback_history),
        "last_updated": memory.updated_at,
        "top_intents": [action.get("intent") for action in memory.frequent_actions[:3]],
    }
