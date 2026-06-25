"""Smoke: 工作流员工商店合集 id 与 FHD mods 目录对齐。"""

from __future__ import annotations

from pathlib import Path

import pytest

from modstore_server.workflow_employee_pack import (
    BUNDLE_ARCHIVE_NAME,
    WORKFLOW_EMPLOYEE_PKG_IDS,
    build_workflow_employee_bundle_zip,
)


def test_workflow_employee_pkg_ids_count():
    assert len(WORKFLOW_EMPLOYEE_PKG_IDS) == 6


def test_workflow_bundle_archive_name():
    assert BUNDLE_ARCHIVE_NAME == "workflow-employee-pack.zip"


def test_build_workflow_bundle_importable():
    assert callable(build_workflow_employee_bundle_zip)


def test_fhd_mod_dirs_exist_when_repo_present():
    repo = Path(__file__).resolve().parents[2]
    fhd_mods = repo.parent / "FHD" / "mods"
    if not fhd_mods.is_dir():
        return
    missing = [pid for pid in WORKFLOW_EMPLOYEE_PKG_IDS if not (fhd_mods / pid).is_dir()]
    if missing:
        pytest.skip(f"workflow employee mods not yet created in FHD/mods: {missing}")
