"""Release-gate regression for the super-employee validation boundary."""

from __future__ import annotations

from app.application.super_employee_service import CODEX_PROFILE, SuperEmployeeService


def test_verify_workspace_rejects_unregistered_directory(tmp_path) -> None:
    trusted_storage = tmp_path / "state"
    trusted_storage.mkdir()
    unrelated = tmp_path / "customer-files"
    unrelated.mkdir()
    (unrelated / "secret.py").write_text("token = 'secret'\n", encoding="utf-8")
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=trusted_storage)

    ok, message = service._verify_workspace(str(unrelated))

    assert ok is False
    assert message == "拒绝验证未登记的工作区"
