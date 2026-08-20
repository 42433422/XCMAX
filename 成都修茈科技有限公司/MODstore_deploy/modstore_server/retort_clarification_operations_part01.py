# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.retort_clarification_gate")


from modstore_server.retort_clarification_operations_part01_part01 import (
    answer_clarification as answer_clarification,
    cancel_clarification as cancel_clarification,
    mark_clarification_resolved as mark_clarification_resolved,
    _mirror_to_boss_inbox as _mirror_to_boss_inbox,
    open_clarification_session as open_clarification_session,
    open_clarification_for_change_request as open_clarification_for_change_request,
    _latest_session_for_subject as _latest_session_for_subject,
)
from modstore_server.retort_clarification_operations_part01_part02 import (
    evaluate_retort_clarification_gate as evaluate_retort_clarification_gate,
    clarification_blocks_auto_approve as clarification_blocks_auto_approve,
)
