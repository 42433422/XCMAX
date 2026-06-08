"""employee_api execute-file suffix allowlist and mismatch messages."""

from __future__ import annotations

import pytest


def test_pptx_allowed_for_ppt_read_employee():
    from modstore_server.employee_api import _suffix_allowed_for_employee

    assert _suffix_allowed_for_employee("ppt-full-read-employee", ".pptx") is True
    assert _suffix_allowed_for_employee("ppt-full-read-employee", ".ppt") is True


def test_pptx_rejected_for_word_generate_employee():
    from modstore_server.employee_api import _suffix_allowed_for_employee

    assert _suffix_allowed_for_employee("word-generate-employee", ".pptx") is False


def test_pptx_mismatch_message_mentions_ppt_read():
    from modstore_server.employee_api import _employee_upload_suffix_mismatch_message

    msg = _employee_upload_suffix_mismatch_message("word-generate-employee", ".pptx")
    assert "ppt-full-read-employee" in msg
    assert "PPT" in msg
