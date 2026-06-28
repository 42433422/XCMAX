from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".toml", ".yml", ".yaml", ".json"}
SKIP_PARTS = {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache"}
GENERATED_EVIDENCE_FILES = {"retort_external_review_report.json", "retort_absorption_log.md", "absorbed_external_patterns.py", "retort_absorbed_patterns.py"}
RETORT_SCORE_DIMENSIONS = (
    "product_level",
    "architecture_depth",
    "test_gate_evidence",
    "api_contract_quality",
    "operational_readiness",
    "evolution_readiness",
    "external_ingestion",
    "comparative_analysis_depth",
    "absorption_tasking",
    "employee_execution_integration",
    "feedback_loop_closure",
    "product_operability",
    "safety_license_gate",
    "branch_absorption_workflow",
    "retort_product_maturity",
    "evidence_loop_score",
    "capability_absorption_score",
    "calibrated_overall",
)
RETORT_LLM_SCORING_RUBRIC = """Retort LLM 评分必须区分“证据闭环”和“能力吸收”，不能把证据文件完整度当成产品能力：
- 你必须直接给每个维度 0-100 分，并给出可验证理由。
- 重点评估深度，不用功能数量堆高分。
- UI、按钮、关键词、文件存在只能证明“有入口”，不能证明“闭环完成”。
- lint/test 通过可以提高 test_gate_evidence 和 operational_readiness，但不能单独把产品级推到 90+。
- 没有 branch diff、员工执行结果、post-absorption tests、merge、外部优势复评五类证据时，calibrated_overall 不得超过 82。
- 没有员工真实执行证据时，employee_execution_integration 不得超过 78。
- 没有吸收后复评和反馈回灌证据时，feedback_loop_closure 不得超过 82。
- 没有真实外部项目吸收、分支落地、合并或回滚证据时，product_level 和 retort_product_maturity 不得超过 84。
- 如果吸收 diff 主要是报告、日志、absorbed_patterns 快照，而没有改动核心行为代码或行为测试，则 capability_absorption_score 不得超过 84，calibrated_overall 不得超过 84。
- 能力吸收审计只提供风险信号、阻塞项、测试/源码比例和最近 diff 类型；不得把本地能力吸收审计当作参考分。
- 如果员工执行结果由 Retort 本地 CLI 同进程生成，而不是独立 employee_runtime/agent_loop 完成，则 employee_execution_integration 不得超过 88。
- 如果只验证了一个外部项目，external_ingestion 可以高，但 retort_product_maturity 不得超过 88，除非还有跨项目复现证据。
- evidence_loop_score 用于评价五证闭环完整度；capability_absorption_score 用于评价吸收后 Retort 核心能力是否真的变强。calibrated_overall 必须更接近 capability_absorption_score，而不是 evidence_loop_score。
- 如果本地证据与项目摘要冲突，以更保守的证据解释为准。
"""


def build_retort_paibi_panel_prompt(
    *,
    project: Path,
    mode: str,
    panel_id: str,
    panel_title: str,
    focus: str,
    external_source: str = "",
    external_path: str = "",
    tasks: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    base = build_retort_paibi_prompt(
        project=project,
        mode=mode,
        external_source=external_source,
        external_path=external_path,
        tasks=tasks or [],
        evidence=evidence or [],
        metadata=metadata or {},
    )
    return f"""{base}

并发评审面板：
- panel_id: {panel_id}
- panel_title: {panel_title}
- focus: {focus}

额外要求：
- 只回答本 panel 的判断，不要等待其它 panel。
- 如果发现阻塞，必须输出 blockers 和 unblock_tasks。
- JSON 须额外包含 "panel_id": "{panel_id}"。
- unblock_tasks 每项须包含 title、owner_hint、acceptance、evidence_required。
"""


def build_retort_paibi_prompt(
    *,
    project: Path,
    mode: str,
    external_source: str = "",
    external_path: str = "",
    scores: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    task_lines = "\n".join(f"- {item.get('task_id')}: {item.get('title')} [{item.get('dimension')}]" for item in tasks or []) or "- no tasks supplied"
    critical = prioritized_evidence(evidence or [])
    critical_evidence_lines = "\n".join(f"- {item}" for item in critical) or "- no critical evidence supplied"
    critical_set = set(critical)
    secondary = [item for item in (evidence or []) if item not in critical_set][:45]
    evidence_lines = "\n".join(f"- {item}" for item in secondary) or "- no secondary evidence supplied"
    scoring_audit_json = json.dumps(scoring_audit(metadata or {}), ensure_ascii=False, indent=2, sort_keys=True)[:3000]
    own = project_digest(project, snippet_limit=5, snippet_chars=420)
    external_digest = project_digest(Path(external_path), snippet_limit=1, snippet_chars=300) if external_path and Path(external_path).is_dir() else "external project not materialized"
    return f"""MODSTORE_REPORT_ONLY=1
report_only=true
[report-only]

你是排比 Para/Codex 调度器里的 Retort LLM 评审员。

目标：你负责给反问 Retort 直接评分。确定性代码只负责采集证据；最终分数由你按下面提示词裁决。

模式：{mode}
主项目：{project}
外部来源：{external_source or "无"}
外部本地路径：{external_path or "无"}

评分提示词：
{RETORT_LLM_SCORING_RUBRIC}

本地不提供任何分数，避免锚定。能力吸收审计如果出现 local_score_removed=true，表示本地只给风险事实，不给参考分；你只能按证据、diff、本提示词评分。

当前 Retort 任务：
{task_lines}

关键证据（优先裁决，若与摘要冲突以这里为准）：
{critical_evidence_lines}

本地证据：
{evidence_lines}

评分审计摘要：
{scoring_audit_json}

主项目摘要：
{own}

外部项目摘要：
{external_digest}

请输出严格 JSON：
{{
  "level": "prototype|usable|product",
  "score_suggestion": 0-100,
  "scores": [
    {{"dimension": "product_level", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "architecture_depth", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "test_gate_evidence", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "api_contract_quality", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "operational_readiness", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "evolution_readiness", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "external_ingestion", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "comparative_analysis_depth", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "absorption_tasking", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "employee_execution_integration", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "feedback_loop_closure", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "product_operability", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "safety_license_gate", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "branch_absorption_workflow", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "retort_product_maturity", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "evidence_loop_score", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "capability_absorption_score", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "calibrated_overall", "value": 0-100, "reason": "≤18字"}}
  ],
  "do_not_raise_score_without_proof": true,
  "architecture_gaps": ["..."],
  "absorption_opportunities": ["..."],
  "employee_tasks": [
    {{"title": "...", "owner_hint": "...", "acceptance": "...", "evidence_required": "..."}}
  ],
  "questions": ["Retort 下一轮必须反问自己的问题"]
}}

要求：
- 这是只读评分任务，不要修改任何文件。
- 直接在最终输出里打印严格 JSON，不要 markdown 代码块。
- 输出必须少于 3200 字符，不能输出逐条长证据。
- 不允许因为已有按钮、关键词或 UI 就给 90+。
- 不允许因为 evidence_loop_score 高就自动给 calibrated_overall 90+。
- 没有 branch diff、员工执行结果、post-absorption tests、merge、外部优势复评五类证据时，总分建议不得超过 82。
- 吸收 diff 只改报告/日志/absorbed_patterns 时，总分建议不得超过 84。
- 重点评估深度，不评估广度。
- scores 必须覆盖这些维度：{", ".join(RETORT_SCORE_DIMENSIONS)}。
"""


def project_digest(root: Path, *, snippet_limit: int = 18, snippet_chars: int = 900) -> str:
    if not root.is_dir():
        return "project folder not found"
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & SKIP_PARTS:
            continue
        files.append(path)
    suffix_counts: dict[str, int] = {}
    snippets: list[str] = []
    for path in files[:400]:
        suffix_counts[path.suffix.lower() or "<none>"] = suffix_counts.get(path.suffix.lower() or "<none>", 0) + 1
        if len(snippets) >= snippet_limit or path.suffix.lower() not in SOURCE_SUFFIXES or path.name in GENERATED_EVIDENCE_FILES:
            continue
        text = _read(path)
        if not text.strip():
            continue
        rel = path.relative_to(root)
        snippets.append(f"## {rel}\n{_compact(text)[:snippet_chars]}")
    return json.dumps({"file_count": len(files), "suffix_counts": suffix_counts, "snippets": snippets}, ensure_ascii=False, indent=2)


def prioritized_evidence(evidence: list[str]) -> list[str]:
    must_keep_prefixes = (
        "operator_journey_replay_",
        "absorption_release_decision_operator_",
        "external_advantage_matrix_",
        "release_decision_self_reference=",
    )
    prefixes = (
        "absorption_source=",
        "latest_absorption_",
        "closed_loop_five_proofs_verified=",
        "gates_passed=",
        "commit=",
        "merge_commit=",
        "rollback_rehearsal=",
        "code_graph_proof_passed=",
        "feedback_audit_closed=",
        "capability_absorption_",
        "latest_absorption_behavior_",
        "behavior_source_file_count=",
        "behavior_test_file_count=",
        "total_behavior_source_file_count=",
        "total_behavior_test_file_count=",
        "test_to_source_ratio=",
        "post_absorption_hardening_",
        "quality_gate_bundle_",
        "employee_execution_mode=",
        "employee_runtime_worker_review=",
        "employee_runtime_patch_closure=",
        "employee_patch_closure_",
        "production_recovery_drill_",
        "operator_journey_replay_",
        "cross_domain_live_probe_",
        "release_decision_self_reference=",
        "absorption_release_decision_",
        "review_adjudication_",
        "pr_live_publish_probe_status=",
        "pr_low_permission_probe_status=",
        "pr_low_permission_probe_real_network=",
        "pr_readonly_degradation_probe_",
        "pr_review_calibration_",
        "pr_long_run_review_",
        "pr_holdout_blind_eval_",
        "pr_failure_rollback_replay_",
        "external_advantage_matrix_",
        "multi_project_absorption_replay_",
        "absorption_continuity_",
    )
    must_keep = [item for item in evidence if any(str(item).startswith(prefix) for prefix in must_keep_prefixes)]
    selected = [item for item in evidence if any(str(item).startswith(prefix) for prefix in prefixes) and item not in must_keep]
    return [*must_keep, *selected][:80]


def scoring_audit(metadata: dict[str, Any]) -> dict[str, Any]:
    proof = metadata.get("closed_loop_proof") if isinstance(metadata.get("closed_loop_proof"), dict) else {}
    audit = metadata.get("capability_absorption_audit") if isinstance(metadata.get("capability_absorption_audit"), dict) else {}
    patch = audit.get("employee_patch_closure") if isinstance(audit.get("employee_patch_closure"), dict) else {}
    review_runtime = audit.get("pr_review_runtime") if isinstance(audit.get("pr_review_runtime"), dict) else {}
    hardening = audit.get("post_absorption_hardening") if isinstance(audit.get("post_absorption_hardening"), dict) else {}
    compact_audit = {
        "local_score_removed": True,
        "status": audit.get("status"),
        "risk_level": audit.get("risk_level"),
        "blockers": audit.get("blockers"),
        "reason": audit.get("reason"),
        "latest_behavior_source_count": len(audit.get("behavior_source_files") or []),
        "latest_behavior_test_count": len(audit.get("behavior_test_files") or []),
        "support_behavior_source_count": len(audit.get("support_behavior_source_files") or []),
        "support_behavior_test_count": len(audit.get("support_behavior_test_files") or []),
        "post_absorption_hardening_source_count": len(hardening.get("behavior_source_files") or []),
        "post_absorption_hardening_test_count": len(hardening.get("behavior_test_files") or []),
        "total_behavior_source_count": len(audit.get("behavior_source_files") or []) + len(hardening.get("behavior_source_files") or []),
        "total_behavior_test_count": len(audit.get("behavior_test_files") or []) + len(hardening.get("behavior_test_files") or []),
        "behavior_count_scope": "latest_absorption_plus_post_merge_hardening",
        "external_project_count": audit.get("external_project_count"),
        "test_to_source_ratio": audit.get("test_to_source_ratio"),
        "employee_execution_mode": audit.get("employee_execution_mode"),
        "employee_worker_review": audit.get("employee_worker_review"),
        "employee_patch_closure": patch,
        "review_adjudication_calibration": {
            "status": review_runtime.get("adjudication_status"),
            "human_label_count": review_runtime.get("adjudication_human_label_count"),
            "pass_rate": review_runtime.get("adjudication_pass_rate"),
            "false_positive_count": review_runtime.get("adjudication_false_positive_count"),
            "false_negative_count": review_runtime.get("adjudication_false_negative_count"),
        },
    }
    return {
        "git_tracking_state": metadata.get("git_tracking_state"),
        "closed_loop_verified": proof.get("verified"),
        "closed_loop_missing": proof.get("missing"),
        "capability_absorption_audit": compact_audit,
    }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _compact(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return "\n".join(line[:180] for line in text.splitlines()[:80])
