# mypy: disable-error-code="no-any-return"
"""Fallback employee manifest result builder."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def _build_fallback_manifest_result(state):
    return {
        "id": state["pid"],
        "name": state["name"],
        "version": "1.0.0",
        "author": "XCAGI",
        "description": _facade()._clean_brief_for_description(state["brief"], 400),
        "artifact": "employee_pack",
        "scope": "global",
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {
            "id": state["employee_id"],
            "label": state["name"],
            "capabilities": state["capabilities"],
        },
        "workflow_employees": [
            {
                "id": state["employee_id"],
                "label": state["name"],
                "panel_title": state["name"],
                "panel_summary": state["panel_summary"],
                "capabilities": state["capabilities"],
                "api_base_path": f"employees/{state['employee_id']}",
                "entry_action": "run",
            }
        ],
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "employee_config_v2": {
            "identity": {
                "id": state["pid"],
                "version": "1.0.0",
                "artifact": "employee_pack",
                "name": state["name"],
                "description": _facade()._clean_brief_for_description(state["brief"], 500),
            },
            "perception": {
                "type": (
                    "csv"
                    if state["_is_csv_read"]
                    else (
                        "json"
                        if state["_is_csv_gen"] or state["_is_excel_gen"]
                        else "excel" if state["_is_excel_read"] else "file_or_text"
                    )
                ),
                "accepted_extensions": state["rule_spec"].get("accepted_extensions")
                or (
                    [".json"]
                    if state["_is_csv_gen"] or state["_is_excel_gen"]
                    else (
                        [".csv"]
                        if state["_is_csv_read"]
                        else (
                            [".xlsx", ".xlsm"]
                            if state["_is_excel_read"]
                            else [".docx", ".pdf"] if state["_is_doc_review"] else [".xlsx"]
                        )
                    )
                ),
            },
            "memory": {"type": "session"},
            "cognition": {
                "agent": {
                    "system_prompt": state["prompt"],
                    "role": {
                        "name": state["name"],
                        "persona": state["persona"],
                        "tone": "professional",
                        "expertise": state["expertise"],
                    },
                    "behavior_rules": state["behavior_rules"],
                    "few_shot_examples": state["few_shot"],
                    "model": {
                        "provider": "auto",
                        "model_name": "auto",
                        "temperature": 0.1 if not state["_is_doc_review"] else 0.3,
                        "max_tokens": 4000 if state["_is_doc_review"] else 2000,
                        "top_p": 0.9,
                    },
                },
                "skills": [{"name": state["skill_name"], "brief": state["skill_brief"]}],
            },
            "collaboration": {"workflow": {"workflow_id": 0, "name": state["name"]}},
            "actions": state["actions_cfg"],
        },
        "metadata": {"framework_version": "2.0.0", "created_by": "asset_pipeline"},
    }
