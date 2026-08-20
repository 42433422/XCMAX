# isort: skip_file
"""Search, metrics, and salvage operations for self-evolution knowledge."""

from __future__ import annotations


from modstore_server.self_evolution_operations_part01 import (
    _facade as _facade,
    _search_docs as _search_docs,
    record_fix_knowledge as record_fix_knowledge,
    search_fix_knowledge as search_fix_knowledge,
    record_code_pattern as record_code_pattern,
    search_code_patterns as search_code_patterns,
    _coverage_candidates as _coverage_candidates,
    _load_coverage_modules as _load_coverage_modules,
    _dev_script as _dev_script,
    collect_proactive_signals as collect_proactive_signals,
    load_evolution_metrics as load_evolution_metrics,
    record_evolution_metrics as record_evolution_metrics,
    _metric_float as _metric_float,
    _metric_delta as _metric_delta,
    evaluate_evolution_regression as evaluate_evolution_regression,
    evolution_metrics_gate as evolution_metrics_gate,
    _knowledge_query as _knowledge_query,
    build_self_evolution_context as build_self_evolution_context,
    render_self_evolution_context as render_self_evolution_context,
    _step_report_text as _step_report_text,
    infer_pattern_from_diff as infer_pattern_from_diff,
    record_loop_evolution_knowledge as record_loop_evolution_knowledge,
    _salvage_kb_files as _salvage_kb_files,
    salvage_kb_from_workspace as salvage_kb_from_workspace,
)
