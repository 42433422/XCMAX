from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[1]
ADMIN_CONSOLE = FHD_ROOT / "admin-console" / "src"
MODSTORE_ROOT = FHD_ROOT.parent / "成都修茈科技有限公司" / "MODstore_deploy"


def test_diagnostic_terminal_is_cli_only_in_admin_console() -> None:
    routes = (ADMIN_CONSOLE / "adminHostRoutes.ts").read_text(encoding="utf-8")
    navigation = (ADMIN_CONSOLE / "constants" / "adminOperatorNav.ts").read_text(encoding="utf-8")
    api = (ADMIN_CONSOLE / "api" / "xcmaxAdmin.ts").read_text(encoding="utf-8")
    proxy = (FHD_ROOT / "app" / "fastapi_routes" / "xcmax_admin_part02_part02.py").read_text(
        encoding="utf-8"
    )

    assert "diagnostic-terminal" not in routes
    assert "diagnostic-terminal" not in navigation
    assert "DiagnosticTerminal" not in api
    assert "diagnostic-terminal" not in proxy
    assert not (ADMIN_CONSOLE / "views" / "DiagnosticTerminalView.vue").exists()
    assert not (ADMIN_CONSOLE / "views" / "DiagnosticTerminalView.css").exists()


def test_diagnostic_terminal_is_cli_only_in_modstore() -> None:
    router = (MODSTORE_ROOT / "market" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
    app = (MODSTORE_ROOT / "market" / "src" / "App.vue").read_text(encoding="utf-8")
    sidebar = (
        MODSTORE_ROOT / "market" / "src" / "components" / "workbench" / "SidebarUserMenu.vue"
    ).read_text(encoding="utf-8")
    app_factory = (MODSTORE_ROOT / "modstore_server" / "api" / "app_factory.py").read_text(
        encoding="utf-8"
    )

    assert "ops-terminal" not in router
    assert "ops-terminal" not in app
    assert "ops-terminal" not in sidebar
    assert "admin_diagnostic_terminal_api" not in app_factory
    assert not (MODSTORE_ROOT / "market" / "src" / "views" / "AdminOpsTerminalView.vue").exists()
    assert not (MODSTORE_ROOT / "modstore_server" / "admin_diagnostic_terminal_api.py").exists()


def test_cli_entrypoint_and_service_remain_available() -> None:
    assert (MODSTORE_ROOT / "scripts" / "xcmax_terminal.py").is_file()
    assert (MODSTORE_ROOT / "modstore_server" / "diagnostic_terminal_cli.py").is_file()
    assert (MODSTORE_ROOT / "modstore_server" / "diagnostic_terminal_service.py").is_file()
