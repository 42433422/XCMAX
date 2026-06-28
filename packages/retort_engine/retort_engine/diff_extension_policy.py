from __future__ import annotations

from pathlib import Path
from typing import Any


EXTENSION_POLICIES: dict[str, dict[str, Any]] = {
    ".py": {"family": "python", "review_context": "runtime", "risk_tags": ["runtime_logic", "typing"]},
    ".pyi": {"family": "python", "review_context": "runtime", "risk_tags": ["typing_contract"]},
    ".rs": {"family": "rust", "review_context": "runtime", "risk_tags": ["ownership", "error_handling"]},
    ".go": {"family": "go", "review_context": "runtime", "risk_tags": ["error_handling", "concurrency"]},
    ".ts": {"family": "typescript", "review_context": "runtime", "risk_tags": ["type_contract", "async_flow"]},
    ".tsx": {"family": "typescript", "review_context": "frontend", "risk_tags": ["state_flow", "type_contract"]},
    ".js": {"family": "javascript", "review_context": "runtime", "risk_tags": ["async_flow", "runtime_contract"]},
    ".jsx": {"family": "javascript", "review_context": "frontend", "risk_tags": ["state_flow"]},
    ".java": {"family": "jvm", "review_context": "runtime", "risk_tags": ["api_contract", "threading"]},
    ".kt": {"family": "jvm", "review_context": "runtime", "risk_tags": ["nullability", "api_contract"]},
    ".cpp": {"family": "cpp", "review_context": "runtime", "risk_tags": ["memory_safety", "build_flags"]},
    ".cc": {"family": "cpp", "review_context": "runtime", "risk_tags": ["memory_safety", "build_flags"]},
    ".cxx": {"family": "cpp", "review_context": "runtime", "risk_tags": ["memory_safety", "build_flags"]},
    ".h": {"family": "cpp", "review_context": "runtime", "risk_tags": ["header_contract"]},
    ".hpp": {"family": "cpp", "review_context": "runtime", "risk_tags": ["header_contract"]},
    ".cs": {"family": "dotnet", "review_context": "runtime", "risk_tags": ["nullable_contract", "async_flow"]},
    ".csproj": {"family": "dotnet", "review_context": "ci_config", "risk_tags": ["dependency_graph", "build_contract"]},
    ".php": {"family": "php", "review_context": "runtime", "risk_tags": ["runtime_contract", "input_validation"]},
    ".rb": {"family": "ruby", "review_context": "runtime", "risk_tags": ["runtime_contract", "dependency_graph"]},
    ".mod": {"family": "go", "review_context": "config", "risk_tags": ["dependency_graph"]},
    ".sum": {"family": "go", "review_context": "config", "risk_tags": ["dependency_integrity"]},
    ".json": {"family": "data", "review_context": "config", "risk_tags": ["schema_drift"]},
    ".jsonc": {"family": "data", "review_context": "config", "risk_tags": ["schema_drift"]},
    ".yaml": {"family": "config", "review_context": "ci_config", "risk_tags": ["workflow_gate"]},
    ".yml": {"family": "config", "review_context": "ci_config", "risk_tags": ["workflow_gate"]},
    ".toml": {"family": "config", "review_context": "config", "risk_tags": ["dependency_graph"]},
    ".html": {"family": "frontend", "review_context": "frontend", "risk_tags": ["dom_state"]},
    ".css": {"family": "frontend", "review_context": "frontend", "risk_tags": ["responsive_layout"]},
    ".md": {"family": "docs", "review_context": "docs", "risk_tags": ["operator_contract"]},
    ".rst": {"family": "docs", "review_context": "docs", "risk_tags": ["operator_contract"]},
    ".adoc": {"family": "docs", "review_context": "docs", "risk_tags": ["operator_contract"]},
}


def extension_policy_for_path(path: str) -> dict[str, Any]:
    suffix = _suffix(path)
    policy = EXTENSION_POLICIES.get(suffix, {})
    return {
        "extension": suffix or "<none>",
        "family": str(policy.get("family") or "unknown"),
        "review_context": str(policy.get("review_context") or "other"),
        "risk_tags": [str(item) for item in policy.get("risk_tags") or []],
        "source": "retort_holdout_extension_policy_v1" if policy else "fallback",
        "known": bool(policy),
    }


def extension_review_context(path: str) -> str:
    return str(extension_policy_for_path(path).get("review_context") or "other")


def extension_policy_summary(paths: list[str]) -> dict[str, Any]:
    policies = [extension_policy_for_path(path) for path in paths]
    known = [item for item in policies if item["known"]]
    families = sorted({str(item["family"]) for item in known if item.get("family")})
    contexts = sorted({str(item["review_context"]) for item in known if item.get("review_context")})
    risk_tags = sorted({str(tag) for item in known for tag in item.get("risk_tags", [])})
    return {
        "file_count": len(paths),
        "known_extension_count": len(known),
        "unknown_extension_count": len(policies) - len(known),
        "known_extension_ratio": round(len(known) / len(paths), 3) if paths else 0.0,
        "language_family_count": len(families),
        "language_families": families,
        "review_context_count": len(contexts),
        "review_contexts": contexts,
        "risk_tag_count": len(risk_tags),
        "risk_tags": risk_tags,
        "policy_source": "retort_holdout_extension_policy_v1",
    }


def _suffix(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if name in {"go.mod", "go.sum"}:
        return "." + name.rsplit(".", 1)[-1]
    return Path(name).suffix
