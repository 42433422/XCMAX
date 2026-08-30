from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[1]
ADMIN_CONSOLE = FHD_ROOT / "admin-console" / "src"


def test_diagnostic_terminal_is_reachable_from_admin_navigation() -> None:
    routes = (ADMIN_CONSOLE / "adminHostRoutes.ts").read_text(encoding="utf-8")
    navigation = (ADMIN_CONSOLE / "constants" / "adminOperatorNav.ts").read_text(encoding="utf-8")

    assert "path: '/diagnostic-terminal'" in routes
    assert "name: 'diagnostic-terminal'" in routes
    assert "component: () => import('./views/DiagnosticTerminalView.vue')" in routes
    assert "{ key: 'diagnostic-terminal', name: '诊断终端'" in navigation


def test_diagnostic_terminal_page_keeps_the_read_only_contract_visible() -> None:
    view = (ADMIN_CONSOLE / "views" / "DiagnosticTerminalView.vue").read_text(encoding="utf-8")

    assert "executeDiagnosticTerminalCommand(command)" in view
    assert "不执行 Shell" in view
    assert "void runCommand('doctor')" in view
