# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations


from modstore_server.employee_autonomy_service_part01_part01 import (
    _facade as _facade,
    _jloads as _jloads,
    _jdumps as _jdumps,
    _dedupe_strs as _dedupe_strs,
    _resolve_actor_user_id as _resolve_actor_user_id,
    _publish_event as _publish_event,
    _suggestion_auto_dispatch_enabled as _suggestion_auto_dispatch_enabled,
    _brief_auto_dispatch_enabled as _brief_auto_dispatch_enabled,
    _doc_autofix_enabled as _doc_autofix_enabled,
    _evolution_enabled as _evolution_enabled,
    _infer_suggestion_targets as _infer_suggestion_targets,
    create_collab_thread as create_collab_thread,
    post_collab_message as post_collab_message,
    create_employee_suggestion as create_employee_suggestion,
    ingest_suggestion_event_payload as ingest_suggestion_event_payload,
    approve_suggestion as approve_suggestion,
    reject_suggestion as reject_suggestion,
    _build_subtask_text as _build_subtask_text,
    dispatch_suggestion as dispatch_suggestion,
    dispatch_pending_suggestions as dispatch_pending_suggestions,
)
