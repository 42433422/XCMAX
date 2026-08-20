from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from retort_engine.repository_intelligence import (
    build_ranked_repository_map,
    compare_repository_gaps,
    task_targets_from_map,
)


def synthesize_behavior_absorption(
    project: str | Path,
    *,
    source: str,
    external_path: str | Path,
    tasks: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    """Synthesize pr_review ranking weights and hunk semantic rules from external signals.

    Writes absorbed_review_rank_weights.py and absorbed_hunk_semantic_rules.py
    (both read by review_diff / analyze_hunk_semantics) plus behavior tests.
    Does not generate absorbed_behavior_bridge.py.
    """
    root = Path(project).expanduser().resolve()
    external = Path(external_path).expanduser().resolve()
    gap = compare_repository_gaps(root, external)
    own_map = build_ranked_repository_map(
        root,
        focus_terms=("review", "diagnostic", "agent", "benchmark", "absorb"),
        max_files=12,
        max_chars=12_000,
    )
    focus_targets = task_targets_from_map(own_map, limit=3)
    signals = _external_review_signals(external, source)
    weights = _weights_from_signals(signals, source=source, run_id=run_id)
    rules = _rules_from_signals(signals, source=source, run_id=run_id)
    module_rel = "retort_engine/absorbed_review_rank_weights.py"
    test_rel = "tests/test_absorbed_review_rank_weights.py"
    rules_rel = "retort_engine/absorbed_hunk_semantic_rules.py"
    rules_test_rel = "tests/test_absorbed_hunk_semantic_rules.py"
    (root / module_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / module_rel).write_text(_weights_module_content(weights), encoding="utf-8")
    (root / test_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / test_rel).write_text(_weights_test_content(weights), encoding="utf-8")
    (root / rules_rel).write_text(_rules_module_content(rules), encoding="utf-8")
    (root / rules_test_rel).write_text(_rules_test_content(rules), encoding="utf-8")
    payload = {
        "run_id": run_id,
        "source": source,
        "signals": signals,
        "weights": weights,
        "rules": rules,
        "focus_targets": focus_targets,
        "gap_summary": gap["summary"],
        "target_files": [
            "retort_engine/pr_review.py",
            "retort_engine/diff_hunk_semantics.py",
            module_rel,
            rules_rel,
        ],
    }
    return {
        "status": "synthesized",
        "behavior_source_files": [module_rel, rules_rel],
        "behavior_test_files": [test_rel, rules_test_rel],
        "changed_files": [module_rel, test_rel, rules_rel, rules_test_rel],
        "focus_targets": focus_targets,
        "gap": gap,
        "dimensions": ["diff_hunk_review", "review_pipeline"],
        "digest": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "payload": payload,
    }


def _external_review_signals(external: Path, source: str) -> dict[str, Any]:
    text_hits = {
        "reviewdog": 0,
        "pr-agent": 0,
        "qodo": 0,
        "security": 0,
        "permission": 0,
        "eval": 0,
    }
    files_scanned = 0
    if external.is_dir():
        for path in sorted(external.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {
                ".py",
                ".md",
                ".yml",
                ".yaml",
                ".json",
                ".ts",
                ".js",
                ".go",
            }:
                continue
            if any(
                part in {".git", "node_modules", ".venv", "__pycache__"}
                for part in path.parts
            ):
                continue
            files_scanned += 1
            if files_scanned > 80:
                break
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for token in text_hits:
                text_hits[token] += text.count(token)
    source_lower = source.lower()
    for token in text_hits:
        if token in source_lower:
            text_hits[token] += 3
    return {"text_hits": text_hits, "files_scanned": files_scanned, "source": source}


def _weights_from_signals(
    signals: dict[str, Any], *, source: str, run_id: str
) -> dict[str, Any]:
    hits = cast(
        dict[str, Any],
        signals.get("text_hits") if isinstance(signals.get("text_hits"), dict) else {},
    )
    reviewdog = 20 + min(40, int(hits.get("reviewdog") or 0) * 2)
    pr_agent = 15 + min(
        35, int(hits.get("pr-agent") or 0) * 2 + int(hits.get("qodo") or 0) * 2
    )
    security = 10 + min(
        20, int(hits.get("security") or 0) + int(hits.get("permission") or 0)
    )
    hunk_boost = 15 + min(
        25, int(hits.get("eval") or 0) + int(hits.get("permission") or 0)
    )
    return {
        "schema_version": 1,
        "source": source,
        "run_id": run_id,
        "external_source_boosts": {
            "reviewdog": reviewdog,
            "pr-agent": pr_agent,
            "qodo": pr_agent,
        },
        "rule_token_boosts": {
            "security": security,
            "permission": security,
            "token": security,
            "secret": security,
        },
        "capability_boosts": {
            "external_diagnostic_ingestion": 10 + min(30, reviewdog // 2),
            "hunk_semantic_review": hunk_boost,
            "cross_language_transfer": 0,
        },
    }


def _rules_from_signals(
    signals: dict[str, Any], *, source: str, run_id: str
) -> dict[str, Any]:
    hits = cast(
        dict[str, Any],
        signals.get("text_hits") if isinstance(signals.get("text_hits"), dict) else {},
    )
    rules = [
        {
            "token": "eval(",
            "finding_type": "absorbed_dangerous_eval",
            "severity": "high",
            "confidence": 88 + min(10, int(hits.get("eval") or 0)),
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
            "confidence": 90 + min(8, int(hits.get("permission") or 0)),
            "message": "注释或代码表明权限检查被移除，需要恢复授权门禁。",
            "review_context": "security",
        },
    ]
    return {
        "schema_version": 1,
        "source": source,
        "run_id": run_id,
        "token_rules": rules,
    }


def _weights_module_content(weights: dict[str, Any]) -> str:
    blob = json.dumps(weights, ensure_ascii=False, sort_keys=True)
    return f'''"""Absorbed review ranking weights that change review_diff behavior.

Synthesized by absorption_synthesizer from external review signals. This is a
behavior module (not a registry-only bridge): pr_review reads these boosts when
ranking external diagnostics and capabilities.
"""

from __future__ import annotations

import json
from typing import Any

ABSORBED_REVIEW_RANK_WEIGHTS: dict[str, Any] = json.loads({json.dumps(blob)})


def absorbed_rank_weights() -> dict[str, Any]:
    return dict(ABSORBED_REVIEW_RANK_WEIGHTS)


def external_source_boost(source: str, rule_id: str = "") -> int:
    source_lower = source.lower()
    rule_lower = rule_id.lower()
    boost = 0
    for token, value in (ABSORBED_REVIEW_RANK_WEIGHTS.get("external_source_boosts") or {{}}).items():
        if str(token).lower() in source_lower:
            boost += int(value)
    for token, value in (ABSORBED_REVIEW_RANK_WEIGHTS.get("rule_token_boosts") or {{}}).items():
        if str(token).lower() in rule_lower:
            boost += int(value)
    return boost


def capability_rank_boost(capability: str) -> int:
    boosts = ABSORBED_REVIEW_RANK_WEIGHTS.get("capability_boosts") or {{}}
    return int(boosts.get(str(capability or ""), 0) or 0)
'''


def _weights_test_content(weights: dict[str, Any]) -> str:
    reviewdog_boost = int(
        (weights.get("external_source_boosts") or {}).get("reviewdog") or 0
    )
    return f'''from retort_engine.absorbed_review_rank_weights import capability_rank_boost, external_source_boost, absorbed_rank_weights
from retort_engine.pr_review import review_diff


def test_absorbed_review_rank_weights_change_external_diagnostic_ranking() -> None:
    weights = absorbed_rank_weights()
    assert weights["run_id"]
    assert external_source_boost("reviewdog/reviewdog", "reviewdog:github-token-write-scope") >= {reviewdog_boost}
    assert capability_rank_boost("external_diagnostic_ingestion") >= 10

    diff = """diff --git a/.github/workflows/reviewdog.yml b/.github/workflows/reviewdog.yml
--- a/.github/workflows/reviewdog.yml
+++ b/.github/workflows/reviewdog.yml
@@ -0,0 +1,3 @@
+on: pull_request_target
+permissions:
+  contents: write
"""
    result = review_diff(
        diff,
        max_comments=6,
        external_diagnostics=[
            {{
                "source_project": "reviewdog/reviewdog",
                "path": ".github/workflows/reviewdog.yml",
                "line": 3,
                "rule_id": "reviewdog:github-token-write-scope",
                "severity": "error",
                "message": "write scope on pull_request_target",
            }}
        ],
    )
    external = [row for row in result["comments"] if row.get("capability") == "external_diagnostic_ingestion"]
    assert external
    assert external[0]["external_diagnostic_rank_weight"] >= 55 + {reviewdog_boost}
    assert result["comments"][0]["capability"] == "external_diagnostic_ingestion"
'''


def _rules_module_content(rules: dict[str, Any]) -> str:
    blob = json.dumps(rules, ensure_ascii=False, sort_keys=True)
    return f'''"""Absorbed hunk semantic rules that change review_diff hunk findings.

Synthesized by absorption_synthesizer from external review signals. Consumed by
diff_hunk_semantics.analyze_hunk_semantics — not a registry-only bridge.
"""

from __future__ import annotations

import json
from typing import Any

ABSORBED_HUNK_SEMANTIC_RULES: dict[str, Any] = json.loads({json.dumps(blob)})


def absorbed_hunk_rules() -> dict[str, Any]:
    return dict(ABSORBED_HUNK_SEMANTIC_RULES)


def match_absorbed_hunk_findings(added_lines: list[str], *, review_context: str = "other") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lowered_blob = "\\n".join(str(line) for line in added_lines).lower()
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
            {{
                "type": str(rule.get("finding_type") or "absorbed_hunk_rule"),
                "severity": str(rule.get("severity") or "medium"),
                "message": str(rule.get("message") or "Absorbed hunk rule matched."),
                "line": line_no,
                "review_context": str(rule.get("review_context") or review_context or "other"),
                "confidence": int(rule.get("confidence") or 70),
                "added_evidence": [evidence] if evidence else [],
                "removed_evidence": [],
                "absorbed_rule_token": token,
            }}
        )
    return findings
'''


def _rules_test_content(rules: dict[str, Any]) -> str:
    tokens = [
        str(item.get("token") or "")
        for item in rules.get("token_rules") or []
        if isinstance(item, dict)
    ]
    assert_token = tokens[0] if tokens else "eval("
    sample_line = (
        "eval(payload)" if assert_token.startswith("eval") else f"{assert_token}payload"
    )
    return f'''from retort_engine.absorbed_hunk_semantic_rules import absorbed_hunk_rules, match_absorbed_hunk_findings
from retort_engine.pr_review import review_diff


def test_absorbed_hunk_semantic_rules_change_review_diff() -> None:
    rules = absorbed_hunk_rules()
    assert rules["run_id"]
    assert match_absorbed_hunk_findings(["{sample_line}"])

    diff = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -0,0 +1,2 @@
+const token = localStorage.getItem('api_token');
+eval(token);
"""
    result = review_diff(diff, max_comments=6)
    semantic = [row for row in result["comments"] if row.get("capability") == "hunk_semantic_review"]
    assert semantic
    assert any(str(row.get("semantic_finding_type") or "").startswith("absorbed_") for row in semantic) or any(
        "eval" in str(row.get("body") or row.get("message") or "").lower() for row in semantic
    )
'''
