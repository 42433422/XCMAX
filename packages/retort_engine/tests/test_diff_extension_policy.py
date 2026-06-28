from __future__ import annotations

import pytest

from retort_engine.diff_extension_policy import extension_policy_for_path, extension_policy_summary, extension_review_context


@pytest.mark.parametrize(
    ("path", "family", "context", "risk_tag"),
    [
        ("src/lib.rs", "rust", "runtime", "ownership"),
        ("internal/worker.go", "go", "runtime", "concurrency"),
        ("ui/App.tsx", "typescript", "frontend", "state_flow"),
        ("service/Worker.cs", "dotnet", "runtime", "nullable_contract"),
        ("service/Worker.csproj", "dotnet", "ci_config", "build_contract"),
        ("native/buffer.cpp", "cpp", "runtime", "memory_safety"),
        ("docs/architecture.adoc", "docs", "docs", "operator_contract"),
        ("go.mod", "go", "config", "dependency_graph"),
        ("go.sum", "go", "config", "dependency_integrity"),
        (".github/workflows/review.yml", "config", "ci_config", "workflow_gate"),
    ],
)
def test_extension_policy_for_holdout_project_extensions(path: str, family: str, context: str, risk_tag: str) -> None:
    policy = extension_policy_for_path(path)

    assert policy["known"] is True
    assert policy["family"] == family
    assert policy["review_context"] == context
    assert risk_tag in policy["risk_tags"]
    assert extension_review_context(path) == context


def test_extension_policy_summary_exposes_cross_language_review_depth() -> None:
    summary = extension_policy_summary(
        [
            "src/lib.rs",
            "internal/worker.go",
            "ui/App.tsx",
            "service/Worker.csproj",
            "native/buffer.cpp",
            "docs/architecture.adoc",
            "scripts/generated.unknown",
        ]
    )

    assert summary["file_count"] == 7
    assert summary["known_extension_count"] == 6
    assert summary["unknown_extension_count"] == 1
    assert summary["known_extension_ratio"] == pytest.approx(0.857)
    assert summary["language_family_count"] >= 6
    assert {"runtime", "frontend", "ci_config", "docs"}.issubset(set(summary["review_contexts"]))
    assert {"ownership", "concurrency", "memory_safety", "operator_contract"}.issubset(set(summary["risk_tags"]))


def test_unknown_extension_falls_back_without_claiming_review_depth() -> None:
    policy = extension_policy_for_path("scripts/review.unknownext")

    assert policy == {
        "extension": ".unknownext",
        "family": "unknown",
        "review_context": "other",
        "risk_tags": [],
        "source": "fallback",
        "known": False,
    }
