from __future__ import annotations

from pathlib import Path

import pytest

from retort_engine.context_packager import build_context_pack
from retort_engine.intent_alignment import assess_change_intent_alignment
from retort_engine.pr_review import parse_unified_diff, review_context_for_file, review_diff
from retort_engine.real_absorption import _should_absorb_frontend_visual
from retort_engine.static_analysis_gate import scan_static_analysis_findings


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def diff_for(path: str, *added_lines: str) -> str:
    body = "\n".join(f"+{line}" for line in added_lines)
    return f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -0,0 +1,{len(added_lines)} @@
{body}
"""


INTENT_CASES = [
    {
        "name": "password reset code path",
        "issue": "Fix password reset token expiry in auth flow",
        "path": "app/auth/password_reset.py",
        "lines": [
            "def refresh_password_reset_token(user):",
            "    return auth_token_expiry(user)",
        ],
        "expected": "aligned",
        "overlap": {"password", "reset", "token", "auth"},
    },
    {
        "name": "billing invoice code path",
        "issue": "Add invoice retry handling for billing webhooks",
        "path": "billing/invoice_retry.py",
        "lines": [
            "def retry_invoice_webhook(event):",
            "    return billing_queue.enqueue(event)",
        ],
        "expected": "aligned",
        "overlap": {"invoice", "billing", "retry", "webhooks"},
    },
    {
        "name": "github action code path",
        "issue": "Run PR review in GitHub Actions without hosting",
        "path": ".github/workflows/review.yml",
        "lines": [
            "name: ai-pr-review",
            "on: [pull_request]",
        ],
        "expected": "aligned",
        "overlap": {"github", "actions", "review"},
    },
    {
        "name": "context pack code path",
        "issue": "Build repository context pack before LLM review",
        "path": "retort_engine/context_packager.py",
        "lines": [
            "def build_repository_context_pack():",
            "    return 'context pack for review'",
        ],
        "expected": "aligned",
        "overlap": {"context", "pack", "review"},
    },
    {
        "name": "static analysis code path",
        "issue": "Detect unsafe yaml load during static analysis",
        "path": "retort_engine/static_analysis_gate.py",
        "lines": [
            "def detect_unsafe_yaml_load(node):",
            "    return 'static analysis finding'",
        ],
        "expected": "aligned",
        "overlap": {"unsafe", "yaml", "static", "analysis"},
    },
    {
        "name": "semantic index code path",
        "issue": "Create semantic index for related files",
        "path": "retort_engine/semantic_index.py",
        "lines": [
            "def semantic_related_files_index():",
            "    return 'related files'",
        ],
        "expected": "aligned",
        "overlap": {"semantic", "related", "files", "index"},
    },
    {
        "name": "rollback proof code path",
        "issue": "Verify rollback rehearsal after absorption merge",
        "path": "retort_engine/proof.py",
        "lines": [
            "def verify_rollback_rehearsal(merge_commit):",
            "    return 'rollback rehearsal merge proof'",
        ],
        "expected": "aligned",
        "overlap": {"rollback", "rehearsal", "merge", "proof"},
    },
    {
        "name": "employee queue code path",
        "issue": "Record employee queue result for absorption tasks",
        "path": "retort_engine/employee_queue.py",
        "lines": [
            "def record_employee_queue_result(task):",
            "    return 'employee queue absorption task'",
        ],
        "expected": "aligned",
        "overlap": {"employee", "queue", "absorption"},
    },
    {
        "name": "license gate code path",
        "issue": "Block incompatible license before external project absorption",
        "path": "retort_engine/license_gate.py",
        "lines": [
            "def block_incompatible_license(project):",
            "    return 'license absorption boundary'",
        ],
        "expected": "aligned",
        "overlap": {"license", "external", "absorption"},
    },
    {
        "name": "benchmark oracle code path",
        "issue": "Compare review quality benchmark before and after absorption",
        "path": "retort_engine/review_quality_benchmark.py",
        "lines": [
            "def compare_review_quality_before_after():",
            "    return 'benchmark absorption quality'",
        ],
        "expected": "aligned",
        "overlap": {"review", "quality", "benchmark", "absorption"},
    },
    {
        "name": "marketplace mismatch",
        "issue": "Close feedback audit for absorbed PR reviewer",
        "path": "marketplace/listing.ts",
        "lines": [
            "export const title = 'New AI employee listing';",
            "export const category = 'marketplace';",
        ],
        "expected": "misaligned",
        "overlap": set(),
    },
    {
        "name": "dashboard style mismatch",
        "issue": "Fix password reset token expiry in auth flow",
        "path": "app/theme.css",
        "lines": [
            ".hero { color: blue; }",
            ".card { border-radius: 8px; }",
        ],
        "expected": "misaligned",
        "overlap": set(),
    },
    {
        "name": "docs mismatch",
        "issue": "Patch shell injection in subprocess runner",
        "path": "docs/release-notes.md",
        "lines": [
            "## UI polish",
            "Updated marketing screenshots.",
        ],
        "expected": "misaligned",
        "overlap": set(),
    },
    {
        "name": "ops mismatch",
        "issue": "Add benchmark regression oracle for review quality",
        "path": ".github/workflows/deploy.yml",
        "lines": [
            "name: deploy",
            "on: [push]",
        ],
        "expected": "misaligned",
        "overlap": set(),
    },
    {
        "name": "frontend mismatch",
        "issue": "Validate rule violations before comments are posted",
        "path": "frontend/app.js",
        "lines": [
            "const heroTitle = 'Retort';",
            "const palette = ['blue', 'gold'];",
        ],
        "expected": "misaligned",
        "overlap": set(),
    },
]


@pytest.mark.parametrize("case", INTENT_CASES, ids=[case["name"] for case in INTENT_CASES])
def test_intent_alignment_frontier_cases(case: dict[str, object]) -> None:
    diff = diff_for(str(case["path"]), *[str(line) for line in case["lines"]])
    result = assess_change_intent_alignment(parse_unified_diff(diff), issue_context=str(case["issue"]))

    assert result["status"] == case["expected"]
    if case["expected"] == "aligned":
        assert set(result["overlap_keywords"]) & set(case["overlap"])
        assert result["summary"]["aligned"] is True
    else:
        assert result["summary"]["overlap_keyword_count"] == 0
        assert result["summary"]["aligned"] is False


REVIEW_CONTEXT_CASES = [
    ("app/auth/login.py", "security", "secrets_permissions_and_auth_edges"),
    ("app/security/policy.py", "security", "secrets_permissions_and_auth_edges"),
    ("tests/test_auth.py", "tests", "behavior_proof_and_regression_scope"),
    ("pkg/__tests__/review.test.ts", "tests", "behavior_proof_and_regression_scope"),
    (".github/workflows/review.yml", "ci_config", "repeatable_gates_and_release_safety"),
    ("deploy/docker-compose.yml", "ci_config", "repeatable_gates_and_release_safety"),
    ("Dockerfile", "ci_config", "repeatable_gates_and_release_safety"),
    ("docs/README.md", "docs", "operator_evidence_and_task_clarity"),
    ("docs/architecture.rst", "docs", "operator_evidence_and_task_clarity"),
    ("config/settings.toml", "config", "runtime_contract_and_environment_drift"),
    ("config/app.yaml", "config", "runtime_contract_and_environment_drift"),
    ("frontend/app.tsx", "frontend", "user_flow_and_state_surface"),
    ("ui/components/Button.jsx", "frontend", "user_flow_and_state_surface"),
    ("retort_engine/core.py", "runtime", "core_execution_path"),
    ("src/main.go", "runtime", "core_execution_path"),
    ("src/lib.rs", "runtime", "core_execution_path"),
    ("src/main.java", "runtime", "core_execution_path"),
    ("cmd/review/main.js", "runtime", "core_execution_path"),
    ("packages/worker/index.ts", "runtime", "core_execution_path"),
    ("apps/web/index.html", "frontend", "user_flow_and_state_surface"),
    ("styles/app.css", "frontend", "user_flow_and_state_surface"),
    ("config/.env", "config", "runtime_contract_and_environment_drift"),
    ("settings/app.ini", "config", "runtime_contract_and_environment_drift"),
    ("docs/operator-guide.md", "docs", "operator_evidence_and_task_clarity"),
    ("test_review.py", "tests", "behavior_proof_and_regression_scope"),
    ("pkg/service.spec.ts", "tests", "behavior_proof_and_regression_scope"),
    ("security/token_store.go", "security", "secrets_permissions_and_auth_edges"),
    ("auth/session.ts", "security", "secrets_permissions_and_auth_edges"),
    ("notes/plain.txt", "other", "general_review"),
]


@pytest.mark.parametrize("path,context,focus", REVIEW_CONTEXT_CASES)
def test_review_context_frontier_classification(path: str, context: str, focus: str) -> None:
    result = review_diff(diff_for(path, "value = 1"), max_comments=2)

    assert review_context_for_file(path) == context
    assert result["context_groups"][0]["context"] == context
    assert result["context_groups"][0]["review_focus"] == focus
    assert result["summary"]["review_context_group_count"] == 1


STATIC_ANALYSIS_CASES = [
    {
        "name": "shell true",
        "path": "app/runner.py",
        "line": "subprocess.run(command, shell=True)",
        "rule": "subprocess-shell-true",
        "severity": "high",
    },
    {
        "name": "eval",
        "path": "app/eval_runner.py",
        "line": "return eval(user_input)",
        "rule": "python-eval-exec",
        "severity": "high",
    },
    {
        "name": "exec",
        "path": "app/exec_runner.py",
        "line": "exec(dynamic_code)",
        "rule": "python-eval-exec",
        "severity": "high",
    },
    {
        "name": "yaml load",
        "path": "app/config.py",
        "line": "yaml.load(payload)",
        "rule": "unsafe-yaml-load",
        "severity": "high",
    },
    {
        "name": "pickle loads",
        "path": "app/cache.py",
        "line": "pickle.loads(raw_payload)",
        "rule": "pickle-deserialize",
        "severity": "medium",
    },
    {
        "name": "tls verify disabled",
        "path": "app/client.py",
        "line": "requests.get(url, verify=False)",
        "rule": "tls-verify-disabled",
        "severity": "high",
    },
]


@pytest.mark.parametrize("case", STATIC_ANALYSIS_CASES, ids=[case["name"] for case in STATIC_ANALYSIS_CASES])
def test_static_analysis_frontier_cases(case: dict[str, str]) -> None:
    files = parse_unified_diff(diff_for(case["path"], case["line"]))
    result = scan_static_analysis_findings(files)

    assert result["status"] == ("blocked" if case["severity"] == "high" else "review")
    assert result["summary"]["finding_count"] == 1
    assert result["findings"][0]["rule_id"] == case["rule"]
    assert result["findings"][0]["severity"] == case["severity"]
    assert result["findings"][0]["file"] == case["path"]


def test_static_analysis_allows_safe_yaml_loader() -> None:
    files = parse_unified_diff(diff_for("app/config.py", "yaml.load(payload, Loader=yaml.SafeLoader)"))
    result = scan_static_analysis_findings(files)

    assert result["status"] == "clean"
    assert result["summary"]["finding_count"] == 0


def test_review_diff_combines_static_analysis_and_intent_alignment() -> None:
    diff = diff_for(
        "app/theme.css",
        ".hero { color: blue; }",
        ".card { border-radius: 8px; }",
        "requests.get(url, verify=False)",
    )
    result = review_diff(
        diff,
        issue_context="Fix password reset token expiry in auth flow",
        pr_body="Refresh dashboard colors",
        max_comments=6,
    )

    assert result["intent_alignment"]["status"] == "misaligned"
    assert result["summary"]["intent_alignment"]["aligned"] is False
    assert result["summary"]["ready_for_employee_tasking"] is True
    assert any(comment["capability"] == "intent_alignment" for comment in result["comments"])
    assert result["summary"]["risk_counts"]["medium"] >= 1


def test_review_diff_keeps_intent_alignment_inside_comment_budget() -> None:
    diff = diff_for(
        "app/theme.css",
        ".hero { color: blue; }",
        ".card { border-radius: 8px; }",
        ".panel { padding: 12px; }",
    )
    result = review_diff(
        diff,
        issue_context="Fix password reset token expiry in auth flow",
        pr_body="Refresh dashboard colors",
        max_comments=1,
    )

    assert result["summary"]["comment_count"] == 1
    assert len(result["comments"]) == 1
    assert result["intent_alignment"]["status"] == "misaligned"


CONTEXT_PACK_FILES = [
    ("retort_engine/real_absorption.py", "absorb context review graph " * 40),
    ("retort_engine/pr_review.py", "review context issue alignment static analysis " * 35),
    ("retort_engine/context_packager.py", "context pack graph budget focus " * 30),
    ("retort_engine/intent_alignment.py", "issue intent alignment review " * 30),
    ("retort_engine/static_analysis_gate.py", "static analysis security yaml shell " * 30),
    ("retort_engine/codebase_graph.py", "codebase graph dependency hotspot " * 30),
    ("retort_engine/service.py", "api service context review " * 20),
    ("tests/test_pr_review.py", "review intent static analysis " * 30),
    ("tests/test_context_packager.py", "context pack budget " * 30),
    ("docs/retort_absorption_log.md", "absorb context review " * 300),
    ("node_modules/pkg/index.js", "absorb context review " * 300),
    (".retort/state.json", "absorb context review " * 300),
]


def test_context_pack_frontier_ignores_generated_noise_and_splits_budget(tmp_path: Path) -> None:
    for path, text in CONTEXT_PACK_FILES:
        write(tmp_path / path, text)

    pack = build_context_pack(
        tmp_path,
        focus_terms=["context", "review", "analysis", "intent"],
        max_files=5,
        max_chars=1000,
    )

    selected = [item["path"] for item in pack["files"]]
    assert pack["status"] == "ready"
    assert pack["summary"]["selected_file_count"] == 5
    assert pack["summary"]["used_chars"] == 1000
    assert "docs/retort_absorption_log.md" not in selected
    assert not any(path.startswith("node_modules/") for path in selected)
    assert not any(path.startswith(".retort/") for path in selected)
    assert selected[0] in {"retort_engine/pr_review.py", "retort_engine/real_absorption.py"}
    assert all(len(item["excerpt"]) <= 200 for item in pack["files"])


def test_context_pack_frontier_fallback_is_stable(tmp_path: Path) -> None:
    write(tmp_path / "zeta.py", "def zeta():\n    return 1\n")
    write(tmp_path / "alpha.py", "def alpha():\n    return 1\n")
    write(tmp_path / "beta.py", "def beta():\n    return 1\n")

    first = build_context_pack(tmp_path, focus_terms=["missing"], max_files=2, max_chars=200)
    second = build_context_pack(tmp_path, focus_terms=["missing"], max_files=2, max_chars=200)

    assert [item["path"] for item in first["files"]] == ["alpha.py", "beta.py"]
    assert first["files"] == second["files"]
    assert first["evidence"]["style"] == "deterministic_context_packaging"


VISUAL_PROFILES = [
    {
        "name": "earth profile",
        "expected": True,
        "profile": {
            "signals": [
                "planet_frontend",
                "atmosphere_shader",
                "procedural_surface",
                "webgl_scene",
                "cloud_texture_layer",
            ],
            "signal_evidence": {
                "planet_frontend": ["index.html"],
                "atmosphere_shader": ["src/getFresnelMat.js"],
                "procedural_surface": ["src/getEarthMat.js"],
                "webgl_scene": ["src/App.jsx"],
                "cloud_texture_layer": ["src/getEarthMat.js"],
            },
        },
    },
    {
        "name": "shader profile",
        "expected": True,
        "profile": {
            "signals": ["atmosphere_shader", "procedural_surface", "webgl_scene"],
            "signal_evidence": {
                "atmosphere_shader": ["src/atmosphereShader.js"],
                "procedural_surface": ["src/terrain.js"],
                "webgl_scene": ["src/webglScene.jsx"],
            },
        },
    },
    {
        "name": "dashboard incidental",
        "expected": False,
        "profile": {
            "signals": ["review_pipeline", "atmosphere_shader", "procedural_surface"],
            "signal_evidence": {
                "atmosphere_shader": ["apps/dashboard/src/app/layout.tsx"],
                "procedural_surface": ["apps/dashboard/src/app/page.tsx"],
            },
        },
    },
    {
        "name": "benchmark incidental",
        "expected": False,
        "profile": {
            "signals": ["benchmarking", "atmosphere_shader", "webgl_scene"],
            "signal_evidence": {
                "atmosphere_shader": ["README.md"],
                "webgl_scene": ["tests/test_programbench.py"],
            },
        },
    },
]


@pytest.mark.parametrize("case", VISUAL_PROFILES, ids=[case["name"] for case in VISUAL_PROFILES])
def test_frontend_visual_absorption_frontier_profiles(case: dict[str, object]) -> None:
    assert _should_absorb_frontend_visual(case["profile"]) is case["expected"]


def test_issue_intent_alignment_works_with_chinese_context() -> None:
    diff = diff_for(
        "retort_engine/absorption.py",
        "def 吸收项目深度():",
        "    return '反问吸收项目能力'",
    )
    result = assess_change_intent_alignment(
        parse_unified_diff(diff),
        issue_context="提升反问吸收项目深度，只保留有用能力",
        pr_body="吸收项目能力",
        min_keyword_length=2,
    )

    assert result["status"] == "aligned"
    assert "吸收项目" in result["issue_keywords"]
    assert result["summary"]["overlap_keyword_count"] >= 1


def test_issue_intent_alignment_not_requested_without_issue_context() -> None:
    diff = diff_for("app/theme.css", ".hero { color: blue; }")
    result = assess_change_intent_alignment(parse_unified_diff(diff))

    assert result["status"] == "not_requested"
    assert result["summary"]["aligned"] is True
    assert result["evidence"]["reason"] == "no_issue_context"


def test_issue_intent_alignment_uses_pr_body_as_supporting_context() -> None:
    diff = diff_for(
        "app/worker.py",
        "def run_background_job():",
        "    return queue.dispatch()",
    )
    result = assess_change_intent_alignment(
        parse_unified_diff(diff),
        issue_context="Fix invoice retry handling for billing webhooks",
        pr_body="This worker handles invoice retry events from billing webhooks.",
    )

    assert result["status"] == "aligned"
    assert {"invoice", "retry", "billing", "webhooks"} & set(result["overlap_keywords"])


def test_issue_intent_alignment_keeps_missing_keywords_for_employee_followup() -> None:
    diff = diff_for(
        "app/worker.py",
        "def run_background_job():",
        "    return queue.dispatch()",
    )
    result = assess_change_intent_alignment(
        parse_unified_diff(diff),
        issue_context="Fix invoice retry handling for billing webhooks",
        pr_body="General queue maintenance.",
    )

    assert result["status"] == "misaligned"
    assert {"invoice", "billing", "webhooks"} <= set(result["missing_keywords"])


def test_review_diff_reports_absorbed_reviewscope_source_after_openrabbit_absorption() -> None:
    result = review_diff(
        diff_for("app/auth/password_reset.py", "def password_reset(): return True"),
        issue_context="Fix password reset token expiry in auth flow",
        max_comments=3,
    )

    assert result["summary"]["absorbed_context_signal_strength"] >= 80
    assert result["summary"]["absorbed_file_grouping"] is True
    assert result["intent_alignment"]["status"] == "aligned"
    assert result["summary"]["ready_for_employee_tasking"] in {True, False}


def test_review_diff_incremental_review_preserves_intent_alignment_summary() -> None:
    previous = diff_for("app/auth/password_reset.py", "def password_reset(): return True")
    current = diff_for(
        "app/auth/password_reset.py",
        "def password_reset(): return True",
        "def refresh_auth_token(): return True",
    )
    result = review_diff(
        current,
        previous_diff_text=previous,
        issue_context="Fix password reset token expiry in auth flow",
        max_comments=4,
    )

    assert result["incremental"]["enabled"] is True
    assert result["summary"]["skipped_existing_change_count"] == 1
    assert result["summary"]["reviewed_new_change_count"] == 1
    assert result["intent_alignment"]["status"] == "aligned"


def test_static_analysis_findings_flow_into_pr_review_comments() -> None:
    result = review_diff(
        diff_for(
            "app/runner.py",
            "subprocess.run(command, shell=True)",
            "yaml.load(payload)",
            "pickle.loads(raw_payload)",
        ),
        issue_context="Harden runner security checks",
        max_comments=5,
    )

    static_comments = [comment for comment in result["comments"] if comment["capability"] == "static_analysis"]
    assert result["summary"]["static_analysis"]["finding_count"] == 3
    assert len(static_comments) == 3
    assert {comment["severity"] for comment in static_comments} == {"high", "medium"}
    assert result["summary"]["risk_counts"]["high"] == 2
