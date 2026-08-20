# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


from modstore_server.daily_digest_part04_part01_part01 import (
    _meeting_minutes_md_to_html as _meeting_minutes_md_to_html,
    _surface_meeting_topic as _surface_meeting_topic,
    _surface_audit_meeting_minutes_html as _surface_audit_meeting_minutes_html,
    build_meeting_minutes_html_sync as build_meeting_minutes_html_sync,
    _daily_meeting_error_card as _daily_meeting_error_card,
    _daily_meeting_outer_timeout_sec as _daily_meeting_outer_timeout_sec,
    _build_meeting_minutes_html_bounded as _build_meeting_minutes_html_bounded,
)
from modstore_server.daily_digest_part04_part01_part02 import (
    build_digest_html as build_digest_html,
    build_digest_approval_bundle as build_digest_approval_bundle,
    _surface_audit_failed_bundle as _surface_audit_failed_bundle,
    _build_surface_audit_bundle as _build_surface_audit_bundle,
)
