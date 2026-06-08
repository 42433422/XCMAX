"""编制内运维 employee_pack：不参与公开市场（与 market_catalog_api 一致）。"""

from __future__ import annotations

from modstore_server.duty_roster import is_planned_duty_employee_pack


def test_is_planned_duty_employee_pack_positive() -> None:
    assert is_planned_duty_employee_pack("nginx-config-engineer", "employee_pack") is True


def test_is_planned_duty_employee_pack_wrong_artifact() -> None:
    assert is_planned_duty_employee_pack("nginx-config-engineer", "mod") is False


def test_is_planned_duty_employee_pack_custom_pack() -> None:
    assert is_planned_duty_employee_pack("my-custom-employee", "employee_pack") is False


def test_is_planned_duty_employee_pack_empty_id() -> None:
    assert is_planned_duty_employee_pack("", "employee_pack") is False
    assert is_planned_duty_employee_pack(None, "employee_pack") is False
