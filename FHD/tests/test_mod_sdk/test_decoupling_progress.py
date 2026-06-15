"""mod_sdk decoupling_progress 单测。"""

from __future__ import annotations

from app.mod_sdk.decoupling_progress import build_decoupling_progress_payload


def test_build_decoupling_progress_payload_shape():
    payload = build_decoupling_progress_payload(installed_mod_ids=[])
    assert payload["schema_version"] == 1
    assert payload["progress_percent"] == 100
    assert payload["adcdfg_complete"] is True
    assert isinstance(payload["milestones"], list)
    assert payload["milestones_total"] == len(payload["milestones"])
    assert "bridges" in payload
    assert "pages" in payload
    assert "repositories" in payload


def test_build_decoupling_progress_generic_pack_flag():
    from app.mod_sdk.platform_shell import GENERIC_HOST_MOD_IDS

    payload = build_decoupling_progress_payload(installed_mod_ids=list(GENERIC_HOST_MOD_IDS))
    assert payload["generic_pack_installed"] is True
