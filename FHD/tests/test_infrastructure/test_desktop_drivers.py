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
    assert reloaded.get_profile("calc") == ok["profile"]


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


@pytest.mark.parametrize(
    "message,app_id,workflow",
    [
        ("请打开 macOS 文本编辑应用 TextEdit。验收标记 C4-DESKTOP-001", "textedit", "open_app"),
        ("启动计算器", "calculator", "open_app"),
        ("查看访达运行状态", "finder", "app_status"),
        ("关闭 TextEdit", "textedit", "unsupported"),
        ("打开 TextEdit 和 Finder", "", "open_app"),
        ("打开一个桌面应用", "", "open_app"),
        ("打开 TextEditX 应用", "", "open_app"),
    ],
)
def test_desktop_requests_plan_without_llm_and_keep_approval(
    svc, monkeypatch, message, app_id, workflow
):
    from app.application.normal_chat_dispatch import route_normal_mode_message
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
    from app.desktop_automation import service as module

    monkeypatch.setattr(module, "_service", svc[0])
    route = route_normal_mode_message(message)
    assert route == {"intent": "desktop", "slots": {"app_id": app_id, "workflow": workflow}}
    planner = object.__new__(LLMWorkflowPlanner)
    plan = planner.plan("7", message, get_tool_registry(), {})
    node = plan.nodes[0]
    if app_id and workflow != "unsupported":
        assert (node.tool_id, node.action, node.params) == (
            "desktop_automation",
            workflow,
            {"app_id": app_id},
        )
        assert ApprovalService().check_node_requires_approval(node) == (workflow == "open_app")
    else:
        assert node.tool_id == "clarify"
    assert svc[1].calls == []


def test_desktop_dispatch_uses_registered_profile_and_truthful_driver_result(svc, monkeypatch):
    from app.application.normal_chat_dispatch import route_normal_mode_message
    from app.desktop_automation import service as module
    from app.services.tools_workflow_dispatch import execute_registered_workflow_tool

    monkeypatch.setattr(module, "_service", svc[0])
    params = {"app_id": "textedit", "_runtime_context": {"user_id": "7"}}
    assert (
        execute_registered_workflow_tool("desktop_automation", "open_app", {"app_id": "textedit"})[
            "success"
        ]
        is False
    )
    result = execute_registered_workflow_tool("desktop_automation", "open_app", params)
    assert result["success"] is True and result["running"] is True
    assert svc[1].calls[0] == ("open", "-b", "com.apple.TextEdit")
    svc[1].running = False
    assert (
        execute_registered_workflow_tool("desktop_automation", "open_app", params)["success"]
        is False
    )
    svc[1].calls.clear()
    assert route_normal_mode_message("不要打开 TextEdit").get("intent") != "desktop"
    assert svc[1].calls == []
