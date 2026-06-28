from __future__ import annotations

from pathlib import Path
from typing import Any


LANGUAGE_FAMILY_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
    ".json": "config",
}

TRANSFER_PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "pattern_id": "github_action_write_scope",
        "needles": ("pull_request_target", "contents: write", "pull-requests: write", "issues: write"),
        "severity": "high",
        "context": "ci_config",
        "message": "跨语言 PR bot 配置打开写权限，需要证明最小权限、dry-run 降级和回滚路径。",
    },
    {
        "pattern_id": "llm_provider_prompt_surface",
        "needles": ("provider", "model", "prompt", "temperature", "openai", "anthropic"),
        "severity": "medium",
        "context": "config",
        "message": "外部 LLM provider/prompt 配置变更需要转成 Retort 的可复评契约，避免只吸收提示词表面。",
    },
    {
        "pattern_id": "async_review_entrypoint",
        "needles": ("async ", "await ", "Promise", "fetch(", "axios.", "subprocess", "Popen"),
        "severity": "medium",
        "context": "runtime",
        "message": "跨语言异步评审入口需要映射到 Retort worker 超时、重试和结果落盘语义。",
    },
    {
        "pattern_id": "review_comment_publish",
        "needles": ("createReviewComment", "pulls.createReview", "issues.createComment", "create_comment", "publish"),
        "severity": "medium",
        "context": "runtime",
        "message": "外部评论发布能力必须接入 Retort 的权限降级和删除回滚证明。",
    },
    {
        "pattern_id": "test_harness_signal",
        "needles": ("vitest", "jest", "pytest", "benchmark", "golden", "fixture"),
        "severity": "low",
        "context": "tests",
        "message": "外部测试/基准信号应转为 Retort 行为矩阵或回归门禁，而不是只记录为素材。",
    },
)


def build_cross_language_transfer(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Map external multi-language PR bot signals into Retort review behavior."""
    families = sorted({_language_family(str(item.get("path") or "")) for item in files if _language_family(str(item.get("path") or ""))})
    findings: list[dict[str, Any]] = []
    for file_review in files:
        path = str(file_review.get("path") or "")
        family = _language_family(path)
        for hunk in file_review.get("hunks") or []:
            for change in hunk.get("changes") or []:
                if change.get("type") != "add":
                    continue
                text = str(change.get("text") or "")
                finding = _transfer_finding(path, family, int(change.get("line") or 0), text)
                if finding:
                    findings.append(finding)
    contexts = sorted({str(item["review_context"]) for item in findings})
    pattern_ids = sorted({str(item["pattern_id"]) for item in findings})
    severity_counts = {severity: sum(1 for item in findings if item["severity"] == severity) for severity in ("high", "medium", "low")}
    return {
        "status": "mapped" if findings else "clean",
        "summary": {
            "language_family_count": len(families),
            "language_families": families,
            "finding_count": len(findings),
            "pattern_count": len(pattern_ids),
            "review_context_count": len(contexts),
            "review_contexts": contexts,
            "severity_counts": severity_counts,
            "cross_language_core_mapping": bool(findings and any(family in {"typescript", "javascript", "config"} for family in families)),
        },
        "findings": findings,
        "evidence": {
            "source": "absorbed_pr_bot_cross_language_transfer",
            "pattern_ids": [str(item["pattern_id"]) for item in TRANSFER_PATTERNS],
        },
    }


def _transfer_finding(path: str, family: str, line: int, text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    for pattern in TRANSFER_PATTERNS:
        needles = tuple(str(item).lower() for item in pattern["needles"])
        if not any(needle in lowered for needle in needles):
            continue
        context = str(pattern["context"])
        if context == "ci_config" and not _is_ci_file(path):
            continue
        return {
            "file": path,
            "line": line,
            "language_family": family or "unknown",
            "pattern_id": str(pattern["pattern_id"]),
            "severity": str(pattern["severity"]),
            "review_context": context,
            "message": str(pattern["message"]),
            "text": text.strip()[:240],
        }
    return None


def _language_family(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if name in {"go.mod", "go.sum"}:
        return "go"
    if name in {"action.yml", "action.yaml"} or normalized.startswith(".github/workflows/"):
        return "config"
    return LANGUAGE_FAMILY_BY_SUFFIX.get(Path(name).suffix, "")


def _is_ci_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith(".github/workflows/") or normalized.endswith(("action.yml", "action.yaml", "workflow.yml", "workflow.yaml"))
