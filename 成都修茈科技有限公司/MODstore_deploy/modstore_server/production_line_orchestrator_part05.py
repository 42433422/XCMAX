# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


def _step_status_map(
    pipeline: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, str]:
    out: _facade().Dict[str, str] = {}
    for block in ("production_line", "operations_line"):
        for s in pipeline.get(block, {}).get("steps", []):
            out[str(s.get("step_id"))] = str(s.get("status", "pending"))
    return out


def get_five_line_status() -> _facade().Dict[str, _facade().Any]:
    """五线独立自动化率 + 步骤映射（baseline 与实时 completed 取较大展示值）。"""
    pipeline = _facade().get_production_line_orchestrator().get_pipeline_status()
    statuses = _facade()._step_status_map(pipeline)
    lines: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for defn in _facade().FIVE_LINE_DEFINITIONS:
        mapped = [sid for sid in defn.step_ids if sid in statuses]
        completed = sum((1 for sid in mapped if statuses[sid] == "completed"))
        live_rate = (
            round(completed / len(mapped) * 100, 1) if mapped else defn.baseline_automation_rate
        )
        display_rate = (
            max(live_rate, defn.baseline_automation_rate)
            if mapped
            else defn.baseline_automation_rate
        )
        entry: _facade().Dict[str, _facade().Any] = {
            "line_id": defn.line_id.value,
            "name": defn.name,
            "subtitle": defn.subtitle,
            "step_ids": list(defn.step_ids),
            "steps_completed": completed,
            "steps_total": len(mapped),
            "automation_rate": display_rate,
            "live_automation_rate": live_rate,
            "baseline_automation_rate": defn.baseline_automation_rate,
        }
        if defn.release_channels:
            entry["release_channels"] = list(defn.release_channels)
            entry["channel_notes"] = dict(defn.channel_notes)
            entry["non_release_targets"] = list(_facade().NON_RELEASE_DEPLOY_TARGETS)
        lines.append(entry)
    rates = [ln["automation_rate"] for ln in lines]
    return {
        "schema_version": 1,
        "lines": lines,
        "overall_automation_rate": round(sum(rates) / len(rates), 1) if rates else 0.0,
        "legacy": {
            "production_line": pipeline.get("production_line"),
            "operations_line": pipeline.get("operations_line"),
        },
    }
