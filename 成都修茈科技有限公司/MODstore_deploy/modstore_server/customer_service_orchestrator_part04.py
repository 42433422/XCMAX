# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations


from modstore_server.customer_service_orchestrator_part04_part01 import (
    _facade as _facade,
    _looks_like_raw_kb_line as _looks_like_raw_kb_line,
    _human_kb_tips as _human_kb_tips,
    _display_name_for_user as _display_name_for_user,
    _summarize_user_issue as _summarize_user_issue,
    _looks_like_forbidden_privilege_request as _looks_like_forbidden_privilege_request,
    _refuse_forbidden_privilege_reply as _refuse_forbidden_privilege_reply,
    _looks_like_product_issue as _looks_like_product_issue,
    _looks_like_concrete_issue as _looks_like_concrete_issue,
    _ack_concrete_issue_reply as _ack_concrete_issue_reply,
    _xiaoc_general_reply as _xiaoc_general_reply,
    build_reply as build_reply,
    resolve_issue_domain as resolve_issue_domain,
    title_for_intent as title_for_intent,
    _is_escalate_only as _is_escalate_only,
    _peek_prior_user_issue as _peek_prior_user_issue,
    _resolve_issue_text_for_reply as _resolve_issue_text_for_reply,
    _enrich_extracted_from_prior_issue as _enrich_extracted_from_prior_issue,
    subject_type_for_intent as subject_type_for_intent,
    session_payload as session_payload,
)
