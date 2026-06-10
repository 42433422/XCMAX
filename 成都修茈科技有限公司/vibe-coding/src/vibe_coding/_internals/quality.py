"""``quality_report`` lifted from eskill.static_executor.

Same semantics as upstream so generated artefacts behave identically.
"""

from __future__ import annotations

import re
from typing import Any


def quality_report(output: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    score = 1.0
    min_length = int(gate.get("min_length") or 0)
    text = " ".join(
        str(v)
        for k, v in output.items()
        if k not in {"logic_type", "eskill_logic_type", "solidified_version"}
    )
    if min_length > 0 and len(text) < min_length:
        issues.append(f"min_length:{len(text)}<{min_length}")
        score = min(score, len(text) / max(min_length, 1))
    for key in [str(x) for x in gate.get("required_keys") or []]:
        if key not in output:
            issues.append(f"missing_key:{key}")
            score = min(score, 0.6)
    for token in [str(x) for x in gate.get("contains_all") or []]:
        if token and token not in text:
            issues.append(f"missing_text:{token}")
            score = min(score, 0.6)
    any_tokens = [str(x) for x in gate.get("contains_any") or []]
    if any_tokens and not any(token in text for token in any_tokens):
        issues.append("missing_any_text")
        score = min(score, 0.7)
    pattern = str(gate.get("regex") or "")
    if pattern:
        try:
            if not re.search(pattern, text):
                issues.append("regex_not_matched")
                score = min(score, 0.7)
        except re.error:
            issues.append("invalid_regex")
            score = min(score, 0.5)
    min_score = float(gate.get("min_score") or 0.0)
    return {"passed": not issues and score >= min_score, "score": round(score, 4), "issues": issues}
