"""Vue path routing for vibe work units."""

from __future__ import annotations

from modstore_server.digest_vibe_work_units import resolve_work_unit_employee


def test_vue_routes_market_to_market_frontend_dev() -> None:
    eid = resolve_work_unit_employee(
        "fhd-core-maintainer",
        ["MODstore_deploy/market/src/views/Foo.vue"],
    )
    assert eid == "market-frontend-dev"


def test_vue_routes_fhd_frontend_to_maintainer() -> None:
    eid = resolve_work_unit_employee(
        "market-frontend-dev",
        ["FHD/frontend/src/views/AutomationPolicyView.vue"],
    )
    assert eid == "fhd-core-maintainer"
