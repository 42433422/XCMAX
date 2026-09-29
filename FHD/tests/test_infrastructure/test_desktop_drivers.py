"""Desktop automation: persisted app profiles and the permission-aware macOS driver."""

from __future__ import annotations

import subprocess

import pytest

from app.desktop_automation import drivers
from app.desktop_automation.drivers import MacDriver, MCPDriver, WindowsDriver
from app.desktop_automation.service import DesktopAutomationService


class FakeMac(MacDriver):
    def __init__(self, available: bool = True, running: bool = True) -> None:
        self.available, self.running, self.calls = available, running, []

    def is_available(self) -> bool:
        return self.available

    def accessibility_trusted(self) -> bool:
        return False

    def _run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        out = "true" if self.running else "false"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


@pytest.fixture
def svc(tmp_path):
    fake = FakeMac()
    return DesktopAutomationService(path=tmp_path / "profiles.json", driver=fake), fake


def test_unshipped_drivers_report_unavailable() -> None:
    assert WindowsDriver().is_available() is False
    assert MCPDriver("wechat_cv").is_available() is False


def test_mac_driver_availability_follows_platform(monkeypatch) -> None:
    monkeypatch.setattr(drivers.platform, "system", lambda: "Linux")
    assert MacDriver().is_available() is False


def test_profiles_persist_and_reject_unsafe_identifiers(svc, tmp_path) -> None:
    service, _fake = svc
    assert service.register_profile({"app_id": "Bad Id"})["success"] is False
    bad = service.register_profile({"app_id": "calc", "mac_bundle_id": 'x"; do shell script "id'})
    assert bad["success"] is False
    ok = service.register_profile(
        {"app_id": "calc", "name": "计算器", "mac_bundle_id": "com.apple.calculator"}
    )
    assert ok["success"] is True
    reloaded = DesktopAutomationService(path=tmp_path / "profiles.json", driver=FakeMac())
    assert reloaded.list_profiles() == [ok["profile"]]


def test_open_app_runs_whitelisted_workflow_and_reports_permission_state(svc) -> None:
    service, fake = svc
    service.register_profile({"app_id": "calc", "mac_bundle_id": "com.apple.calculator"})
    result = service.run_workflow("calc", "open_app")
    assert result == {
        "success": True,
        "workflow": "open_app",
        "running": True,
        "accessibility_trusted": False,
    }
    assert fake.calls[0] == ("open", "-b", "com.apple.calculator")
    assert service.run_workflow("calc", "open_and_send")["success"] is False
    assert service.run_workflow("missing", "open_app")["success"] is False
    fake.available = False
    assert service.run_workflow("calc", "app_status")["success"] is False


def test_ui_driving_actions_stay_unavailable(svc) -> None:
    service, _fake = svc
    assert service.find_element("calc", "button")["success"] is False
    assert service.send_wechat_message("a", "b")["message_sent"] is False
