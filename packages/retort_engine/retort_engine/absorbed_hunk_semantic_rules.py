"""Absorbed hunk semantic rules that change review_diff hunk findings.

Synthesized by absorption_synthesizer from external review signals. Consumed by
diff_hunk_semantics.analyze_hunk_semantics — not a registry-only bridge.
"""

from __future__ import annotations

import json
from typing import Any

ABSORBED_HUNK_SEMANTIC_RULES: dict[str, Any] = json.loads(
    '{"run_id": "20260719151907-f7cfdfd7bc", "schema_version": 1, "source": "https://github.com/alibaba/open-code-review", "token_rules": [{"confidence": 98, "finding_type": "absorbed_dangerous_eval", "message": "\u65b0\u589e eval \u8c03\u7528\uff0c\u9700\u8981\u8bc1\u660e\u8f93\u5165\u5df2\u6d88\u6bd2\u5e76\u9650\u5236\u6267\u884c\u9762\u3002", "review_context": "runtime", "severity": "high", "token": "eval("}, {"confidence": 84, "finding_type": "absorbed_dom_injection", "message": "\u65b0\u589e DOM \u6ce8\u5165\u9762\uff0c\u9700\u8981\u8bc1\u660e\u5185\u5bb9\u5df2\u8f6c\u4e49\u3002", "review_context": "frontend", "severity": "high", "token": "innerhtml"}, {"confidence": 98, "finding_type": "absorbed_permission_removal", "message": "\u6ce8\u91ca\u6216\u4ee3\u7801\u8868\u660e\u6743\u9650\u68c0\u67e5\u88ab\u79fb\u9664\uff0c\u9700\u8981\u6062\u590d\u6388\u6743\u95e8\u7981\u3002", "review_context": "security", "severity": "high", "token": "permission check removed"}]}'
)


def absorbed_hunk_rules() -> dict[str, Any]:
    return dict(ABSORBED_HUNK_SEMANTIC_RULES)


def match_absorbed_hunk_findings(
    added_lines: list[str], *, review_context: str = "other"
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lowered_blob = "\n".join(str(line) for line in added_lines).lower()
    for rule in ABSORBED_HUNK_SEMANTIC_RULES.get("token_rules") or []:
        if not isinstance(rule, dict):
            continue
        token = str(rule.get("token") or "").lower()
        if not token or token not in lowered_blob:
            continue
        line_no = 0
        evidence = ""
        for index, line in enumerate(added_lines, start=1):
            if token in str(line).lower():
                line_no = index
                evidence = str(line)[:160]
                break
        findings.append(
            {
                "type": str(rule.get("finding_type") or "absorbed_hunk_rule"),
                "severity": str(rule.get("severity") or "medium"),
                "message": str(rule.get("message") or "Absorbed hunk rule matched."),
                "line": line_no,
                "review_context": str(
                    rule.get("review_context") or review_context or "other"
                ),
                "confidence": int(rule.get("confidence") or 70),
                "added_evidence": [evidence] if evidence else [],
                "removed_evidence": [],
                "absorbed_rule_token": token,
            }
        )
    return findings
