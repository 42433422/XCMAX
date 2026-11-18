"""Explicit model-review completions for planner integration fixtures."""

import json


def goal_review_response(payload: dict, *, source: str, node_ids: list[str], outcome: str) -> dict:
    """Script one known review; never infer an approval from arbitrary plan content."""
    assert payload["task"] == "audit_goal_coverage"
    assert payload["user_message"] == source
    assert set(node_ids) == {node["node_id"] for node in payload["plan"]["nodes"]}
    review = {
        "goals": [
            {
                "goal_id": "g1",
                "source": source,
                "outcome": outcome,
                "node_ids": node_ids,
                "depends_on": [],
            }
        ],
        "violations": [],
    }
    return {"choices": [{"message": {"content": json.dumps(review, ensure_ascii=False)}}]}
