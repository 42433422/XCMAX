from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[1]
ADMIN_CONSOLE = FHD_ROOT / "admin-console" / "src"


def test_founder_autonomy_page_is_reachable_from_admin_navigation() -> None:
    routes = (ADMIN_CONSOLE / "adminHostRoutes.ts").read_text(encoding="utf-8")
    navigation = (ADMIN_CONSOLE / "constants" / "adminOperatorNav.ts").read_text(encoding="utf-8")

    assert "path: '/founder-autonomy'" in routes
    assert "name: 'founder-autonomy'" in routes
    assert "component: () => import('./views/FounderAutonomyView.vue')" in routes
    assert "requiresAdminAccount: true" in routes
    assert "{ key: 'founder-autonomy', name: '创始人状态'" in navigation


def test_founder_autonomy_approval_link_targets_admin_approval_route() -> None:
    view = (ADMIN_CONSOLE / "views" / "FounderAutonomyView.vue").read_text(encoding="utf-8")

    assert "name: 'autonomy-approval-hub'" in view
    assert "requestedName === 'approval-hub' ? 'autonomy-approval-hub'" in view
