"""Absorbed hunk semantic rules that change review_diff hunk findings.

Synthesized by absorption_synthesizer from external review signals. Consumed by
diff_hunk_semantics.analyze_hunk_semantics — not a registry-only bridge.
"""

from __future__ import annotations

from typing import Any


ABSORBED_HUNK_SEMANTIC_RULES: dict[str, Any] = {
    "schema_version": 1,
    "source": "baseline",
    "run_id": "",
    "token_rules": [
        {
            "token": "eval(",
            "finding_type": "absorbed_dangerous_eval",
            "severity": "high",
            "confidence": 88,
            "message": "新增 eval 调用，需要证明输入已消毒并限制执行面。",
            "review_context": "runtime",
        },
        {
            "token": "innerhtml",
            "finding_type": "absorbed_dom_injection",
            "severity": "high",
            "confidence": 84,
            "message": "新增 DOM 注入面，需要证明内容已转义。",
            "review_context": "frontend",
        },
        {
            "token": "permission check removed",
            "finding_type": "absorbed_permission_removal",
            "severity": "high",
            "confidence": 90,
            "message": "注释或代码表明权限检查被移除，需要恢复授权门禁。",
            "review_context": "security",
        },
    ],
}


def absorbed_hunk_rules() -> dict[str, Any]:
    return dict(ABSORBED_HUNK_SEMANTIC_RULES)


def match_absorbed_hunk_findings(added_lines: list[str], *, review_context: str = "other") -> list[dict[str, Any]]:
    """Return semantic findings for added hunk lines using absorbed token rules."""
    findings: list[dict[str, Any]] = []
    joined = "\n".join(str(line) for line in added_lines)
    lowered = joined.lower()
    for rule in ABSORBED_HUNK_SEMANTIC_RULES.get("token_rules") or []:
        if not isinstance(rule, dict):
            continue
        token = str(rule.get("token") or "").lower()
        if not token or token not in lowered:
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
                "review_context": str(rule.get("review_context") or review_context or "other"),
                "confidence": int(rule.get("confidence") or 70),
                "added_evidence": [evidence] if evidence else [],
                "removed_evidence": [],
                "absorbed_rule_token": token,
            }
        )
    return findings
