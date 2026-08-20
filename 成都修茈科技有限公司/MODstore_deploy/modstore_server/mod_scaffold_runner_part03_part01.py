# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


from modstore_server.mod_scaffold_runner_part03_part01_part01 import (
    generate_workflow_for_intent as generate_workflow_for_intent,
    run_mod_ai_scaffold_async as run_mod_ai_scaffold_async,
    _suite_blueprint_file as _suite_blueprint_file,
    _suite_validation_summary as _suite_validation_summary,
    _json_response_format as _json_response_format,
    _mod_suite_industry_card_payload as _mod_suite_industry_card_payload,
    _mod_suite_ui_shell_payload as _mod_suite_ui_shell_payload,
    _mod_suite_user_lines as _mod_suite_user_lines,
    _repair_mod_suite_json_async as _repair_mod_suite_json_async,
    generate_mod_suite_blueprint_async as generate_mod_suite_blueprint_async,
)
from modstore_server.mod_scaffold_runner_part03_part01_part02 import (
    import_mod_suite_repository as import_mod_suite_repository,
    write_mod_suite_industry_card as write_mod_suite_industry_card,
    write_mod_suite_ui_shell as write_mod_suite_ui_shell,
    _openapi_node_summary as _openapi_node_summary,
    create_mod_suite_workflows_async as create_mod_suite_workflows_async,
    run_mod_suite_workflow_sandboxes as run_mod_suite_workflow_sandboxes,
    write_mod_suite_blueprint as write_mod_suite_blueprint,
    run_mod_suite_mod_sandbox as run_mod_suite_mod_sandbox,
)
