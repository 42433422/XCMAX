"""Behavior absorption bridge synthesized by Retort (not registry-only metadata)."""

from __future__ import annotations

import json
from typing import Any

from retort_engine.bounded_agent_loop import detect_stuck_pattern, persist_trajectory, run_bounded_agent_loop
from retort_engine.issue_capability_benchmark import run_heldout_oracle_suite
from retort_engine.process_safety import run_command_with_process_group
from retort_engine.repository_intelligence import build_ranked_repository_map, compare_repository_gaps

ABSORBED_BEHAVIOR_BRIDGE = json.loads("{\"dimensions\": [\"bounded_execution\", \"repository_intelligence\", \"reproducible_evaluation\", \"verified_task_synthesis\"], \"external_top_gaps\": [], \"focus_targets\": [{\"focus_hits\": 774, \"page_rank\": 0.00222288, \"path\": \"tests/test_core_review_score_matrix.py\", \"score\": 502.222884, \"symbols\": [\"test_core_comment_rank_score_matches_weight_matrix\", \"test_core_review_score_summary_flags_missing_cross_language_core_behavior\", \"test_core_review_score_summary_proves_cross_language_transfer_is_top_ranked\", \"test_core_review_score_summary_proves_hunk_semantics_is_top_ranked\", \"test_cross_language_transfer_weight_changes_core_ordering\", \"test_hunk_semantic_review_weight_beats_cross_language_when_confident\"]}, {\"focus_hits\": 91, \"page_rank\": 0.00390462, \"path\": \"retort_engine/real_absorption.py\", \"score\": 458.904622, \"symbols\": [\"_absorption_license_review\", \"_absorption_quality_target\", \"_append_log\", \"_architecture_memory_target\", \"_capability_import_name\", \"_capability_module_content\", \"_capability_target\", \"_capability_test_content\", \"_capability_test_target\", \"_changed_files\", \"_code_profile\", \"_context_focus_from_signals\"]}, {\"focus_hits\": 86, \"page_rank\": 0.00445636, \"path\": \"retort_engine/self_bootstrap.py\", \"score\": 434.456361, \"symbols\": [\"_behavior_layers\", \"_comparative_benchmark\", \"_feature_present\", \"_gate_evidence_ok\", \"_git_ok\", \"_implementation_hashes\", \"_landing_proof\", \"_merge_after_commit\", \"_pre_frontier_baseline\", \"_read_json\", \"_source_record_payload\", \"_source_recorded\"]}], \"gap_summary\": {\"decision_source\": \"repository_graph_gap\", \"external_selected_file_count\": 16, \"gap_count\": 0, \"marker_scan_is_auxiliary\": true, \"own_selected_file_count\": 16}, \"run_id\": \"self-depth-phase6\", \"source\": \"retort://self-depth-frontier\", \"target_files\": [\"retort_engine/bounded_agent_loop.py\", \"retort_engine/repository_intelligence.py\", \"retort_engine/issue_capability_benchmark.py\", \"retort_engine/issue_capability_benchmark.py\"]}")


def absorbed_behavior_plan() -> dict[str, Any]:
    return dict(ABSORBED_BEHAVIOR_BRIDGE)


def verify_absorbed_behavior_imports() -> dict[str, Any]:
    return {
        "run_bounded_agent_loop": callable(run_bounded_agent_loop),
        "persist_trajectory": callable(persist_trajectory),
        "detect_stuck_pattern": callable(detect_stuck_pattern),
        "run_command_with_process_group": callable(run_command_with_process_group),
        "build_ranked_repository_map": callable(build_ranked_repository_map),
        "compare_repository_gaps": callable(compare_repository_gaps),
        "run_heldout_oracle_suite": callable(run_heldout_oracle_suite),
        "dimensions": list(ABSORBED_BEHAVIOR_BRIDGE.get("dimensions") or []),
        "focus_targets": list(ABSORBED_BEHAVIOR_BRIDGE.get("focus_targets") or []),
    }
