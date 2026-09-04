from __future__ import annotations

import pytest
from fastapi import HTTPException

from modstore_server.yuangon_onboard_admin_api import _validated_pkg_ids


def test_pkg_ids_are_canonicalized_before_subprocess() -> None:
    assert _validated_pkg_ids("employee.a, employee-b employee.a") == "employee.a,employee-b"


@pytest.mark.parametrize("value", ["employee;rm -rf /", "$(whoami)", "a\n--repo-root", "员工"])
def test_pkg_ids_reject_shell_and_option_injection(value: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _validated_pkg_ids(value)
    assert exc.value.status_code == 422
