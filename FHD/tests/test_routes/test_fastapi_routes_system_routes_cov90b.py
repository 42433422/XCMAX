"""Second-wave coverage for app/fastapi_routes/system_routes.py.

Targets the still-uncovered regions:

* ``_allowed_industry_ids_for_request`` (lines 84-86): the enterprise-filter
  branch where ``enterprise_filter_applied`` is truthy and the current session
  is *not* an admin account, so the helper returns the filtered id set plus the
  first allowed id as fallback. Existing route tests patch this helper wholesale,
  so its internals were never executed.
* ``get_duty_roster`` (lines 332-382): the whole endpoint — happy path with
  manifest globbing (name/description present, missing emp id, non-dict json,
  per-file parse error), the ``cfg_dir is None`` short-circuit, the
  ``employees_dir`` not-a-directory short-circuit, and the
  ``RECOVERABLE_ERRORS`` -> HTTP 500 failure branch.

All external deps (entitlement lookup, onboarding catalog, duty-roster SSOT,
config-dir resolution, filesystem) are mocked; filesystem uses ``tmp_path``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.system_routes import (
    _allowed_industry_ids_for_request,
    router,
)
from app.infrastructure.auth.dependencies import require_admin_user


def _make_profile(*, name: str = "涂料") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        units={"桶": {"abbr": "t"}},
        quantity_fields={"primary_field": "tins"},
        product_fields={"name": "name"},
        order_types={"shipment": "发货单"},
        print_config={"template": "default"},
    )


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
        id=1, username="admin", tier="admin"
    )
    return TestClient(app, raise_server_exceptions=False)


# ── _allowed_industry_ids_for_request internals (lines 84-86) ────────────────


class TestAllowedIndustryIdsInternals:
    async def test_enterprise_filter_applied_non_admin_returns_filtered_set(self) -> None:
        """enterprise_filter_applied + not admin session → (set(ids), first_id)."""
        request = MagicMock()
        catalog = {
            "enterprise_filter_applied": True,
            "open_industry_ids": ["涂料", " 食品 ", "电子"],
        }
        with (
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
                new=AsyncMock(return_value=catalog),
            ),
            patch(
                "app.enterprise.mod_entitlements.is_admin_account_session",
                return_value=False,
            ),
        ):
            allowed, first = await _allowed_industry_ids_for_request(request)
        # whitespace stripped, all ids retained as a set
        assert allowed == {"涂料", "食品", "电子"}
        # first non-empty id (insertion order from the cleaned list)
        assert first == "涂料"

    async def test_filter_applied_blank_ids_dropped_first_none(self) -> None:
        """Blank/whitespace ids are dropped; empty list → first is None.

        NOTE: the comprehension keys off ``str(x).strip()`` truthiness, so only
        empty/whitespace *strings* drop out — ``None`` would survive as the
        literal string ``"None"``, which is why we exercise empties here.
        """
        request = MagicMock()
        catalog = {
            "enterprise_filter_applied": True,
            "open_industry_ids": ["", "   ", "\t\n"],
        }
        with (
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
                new=AsyncMock(return_value=catalog),
            ),
            patch(
                "app.enterprise.mod_entitlements.is_admin_account_session",
                return_value=False,
            ),
        ):
            allowed, first = await _allowed_industry_ids_for_request(request)
        assert allowed == set()
        assert first is None

    async def test_admin_session_returns_none(self) -> None:
        """Filter applied but admin session → bypass filter, return (None, None)."""
        request = MagicMock()
        catalog = {
            "enterprise_filter_applied": True,
            "open_industry_ids": ["涂料"],
        }
        with (
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
                new=AsyncMock(return_value=catalog),
            ),
            patch(
                "app.enterprise.mod_entitlements.is_admin_account_session",
                return_value=True,
            ),
        ):
            allowed, first = await _allowed_industry_ids_for_request(request)
        assert allowed is None
        assert first is None

    async def test_no_filter_applied_returns_none(self) -> None:
        """enterprise_filter_applied falsy → return (None, None) without touching ids."""
        request = MagicMock()
        catalog = {"enterprise_filter_applied": False, "open_industry_ids": ["涂料"]}
        with patch(
            "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
            new=AsyncMock(return_value=catalog),
        ):
            allowed, first = await _allowed_industry_ids_for_request(request)
        assert allowed is None
        assert first is None

    async def test_recoverable_error_swallowed_returns_none(self) -> None:
        """Catalog lookup raising a recoverable error → (None, None)."""
        request = MagicMock()
        with patch(
            "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
            new=AsyncMock(side_effect=ValueError("boom")),
        ):
            allowed, first = await _allowed_industry_ids_for_request(request)
        assert allowed is None
        assert first is None

    def test_filter_applied_drives_industries_endpoint(self, client: TestClient) -> None:
        """End-to-end: the filtered set actually limits /industries output."""
        fake_cfg = MagicMock()
        fake_cfg.get_available_industries.return_value = [
            {"id": "涂料", "name": "涂料"},
            {"id": "食品", "name": "食品"},
            {"id": "电子", "name": "电子"},
        ]
        fake_cfg.get_current_industry.return_value = "电子"  # not in allowed → falls back
        fake_cfg.get_industry_profile.side_effect = lambda iid: _make_profile(name=iid)
        catalog = {
            "enterprise_filter_applied": True,
            "open_industry_ids": ["食品", "涂料"],
        }
        with (
            patch.dict("sys.modules", {"resources.config.industry_config": fake_cfg}),
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
                new=AsyncMock(return_value=catalog),
            ),
            patch(
                "app.enterprise.mod_entitlements.is_admin_account_session",
                return_value=False,
            ),
        ):
            r = client.get("/api/system/industries")
        assert r.status_code == 200
        body = r.json()["data"]
        returned_ids = {ind["id"] for ind in body["industries"]}
        assert returned_ids == {"食品", "涂料"}  # 电子 filtered out
        # current "电子" not allowed → replaced by first allowed ("食品")
        assert body["current"] == "食品"


# ── get_duty_roster (lines 332-382) ─────────────────────────────────────────


def _make_duty_modules(doc: dict, planned_ids: list[str]):
    duty_mod = MagicMock()
    duty_mod.load_duty_roster_document.return_value = doc
    duty_mod.all_planned_duty_employee_ids.return_value = planned_ids
    return duty_mod


class TestGetDutyRoster:
    def test_happy_path_with_manifests(self, client: TestClient, tmp_path) -> None:
        """Globs mods/_employees/*/manifest.json and derives labels/descriptions."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        employees_dir = tmp_path / "mods" / "_employees"
        employees_dir.mkdir(parents=True)

        # emp with both name + description
        e1 = employees_dir / "小C"
        e1.mkdir()
        (e1 / "manifest.json").write_text(
            json.dumps({"id": "xiaoc", "name": "小C", "description": "助理"}),
            encoding="utf-8",
        )
        # emp with name only (no description) → only label set
        e2 = employees_dir / "noDesc"
        e2.mkdir()
        (e2 / "manifest.json").write_text(
            json.dumps({"id": "nodesc", "name": "无描述"}),
            encoding="utf-8",
        )
        # emp with empty id → skipped entirely
        e3 = employees_dir / "noId"
        e3.mkdir()
        (e3 / "manifest.json").write_text(
            json.dumps({"id": "  ", "name": "ghost", "description": "x"}),
            encoding="utf-8",
        )
        # manifest whose top-level json is a list (not dict) → skipped
        e4 = employees_dir / "listManifest"
        e4.mkdir()
        (e4 / "manifest.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        # emp with description but blank name → desc set, label not
        e5 = employees_dir / "descOnly"
        e5.mkdir()
        (e5 / "manifest.json").write_text(
            json.dumps({"id": "desconly", "name": "", "description": "仅说明"}),
            encoding="utf-8",
        )

        doc = {
            "areas": {"sales": ["xiaoc"]},
            "departments": {"front": {"label": "前台"}},
            "schema_version": 7,
        }
        duty_mod = _make_duty_modules(doc, ["xiaoc", "nodesc", "desconly"])

        with (
            patch.dict("sys.modules", {"app.mod_sdk.duty_roster": duty_mod}),
            patch(
                "app.mod_sdk.host_profile.resolve_fhd_config_dir",
                return_value=cfg_dir,
            ),
        ):
            r = client.get("/api/system/duty-roster")

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["areas"] == {"sales": ["xiaoc"]}
        assert data["departments"] == {"front": {"label": "前台"}}
        assert data["schema_version"] == 7
        # xiaoc: label + desc; nodesc: label only; desconly: desc only; ghost skipped
        assert data["employee_labels"]["xiaoc"] == "小C"
        assert data["employee_labels"]["nodesc"] == "无描述"
        assert "desconly" not in data["employee_labels"]
        assert "ghost" not in data["employee_labels"].values()
        assert data["employee_descriptions"]["xiaoc"] == "助理"
        assert data["employee_descriptions"]["desconly"] == "仅说明"
        assert "nodesc" not in data["employee_descriptions"]
        # sorted planned ids
        assert data["all_planned_ids"] == ["desconly", "nodesc", "xiaoc"]

    def test_per_manifest_parse_error_skipped(self, client: TestClient, tmp_path) -> None:
        """A manifest whose read raises a recoverable error is skipped, others survive."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        employees_dir = tmp_path / "mods" / "_employees"
        employees_dir.mkdir(parents=True)

        good = employees_dir / "good"
        good.mkdir()
        (good / "manifest.json").write_text(
            json.dumps({"id": "good", "name": "好员工", "description": "ok"}),
            encoding="utf-8",
        )
        bad = employees_dir / "bad"
        bad.mkdir()
        (bad / "manifest.json").write_text("{not valid json", encoding="utf-8")

        doc = {"areas": {}, "departments": {}, "schema_version": 1}
        duty_mod = _make_duty_modules(doc, ["good"])

        with (
            patch.dict("sys.modules", {"app.mod_sdk.duty_roster": duty_mod}),
            patch(
                "app.mod_sdk.host_profile.resolve_fhd_config_dir",
                return_value=cfg_dir,
            ),
        ):
            r = client.get("/api/system/duty-roster")

        assert r.status_code == 200
        data = r.json()["data"]
        # good parsed; the invalid-json manifest swallowed by the per-file except
        assert data["employee_labels"] == {"good": "好员工"}
        assert data["employee_descriptions"] == {"good": "ok"}

    def test_cfg_dir_none_skips_globbing(self, client: TestClient) -> None:
        """resolve_fhd_config_dir() is None → labels/descriptions stay empty."""
        doc = {"areas": {"a": []}, "departments": {}, "schema_version": 2}
        duty_mod = _make_duty_modules(doc, ["z", "a"])
        with (
            patch.dict("sys.modules", {"app.mod_sdk.duty_roster": duty_mod}),
            patch(
                "app.mod_sdk.host_profile.resolve_fhd_config_dir",
                return_value=None,
            ),
        ):
            r = client.get("/api/system/duty-roster")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["employee_labels"] == {}
        assert data["employee_descriptions"] == {}
        assert data["all_planned_ids"] == ["a", "z"]
        assert data["schema_version"] == 2

    def test_employees_dir_missing_skips_globbing(self, client: TestClient, tmp_path) -> None:
        """cfg_dir resolves but mods/_employees is absent → empty labels."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        # NOTE: do not create tmp_path/mods/_employees → employees_dir.is_dir() False
        doc = {"areas": {}, "departments": {}, "schema_version": 3}
        duty_mod = _make_duty_modules(doc, [])
        with (
            patch.dict("sys.modules", {"app.mod_sdk.duty_roster": duty_mod}),
            patch(
                "app.mod_sdk.host_profile.resolve_fhd_config_dir",
                return_value=cfg_dir,
            ),
        ):
            r = client.get("/api/system/duty-roster")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["employee_labels"] == {}
        assert data["employee_descriptions"] == {}
        assert data["all_planned_ids"] == []

    def test_missing_doc_keys_default_to_empty(self, client: TestClient) -> None:
        """doc without areas/departments → defaults ({} and schema_version 1)."""
        duty_mod = _make_duty_modules({}, [])
        with (
            patch.dict("sys.modules", {"app.mod_sdk.duty_roster": duty_mod}),
            patch(
                "app.mod_sdk.host_profile.resolve_fhd_config_dir",
                return_value=None,
            ),
        ):
            r = client.get("/api/system/duty-roster")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["areas"] == {}
        assert data["departments"] == {}
        assert data["schema_version"] == 1

    def test_load_document_recoverable_error_returns_500(self, client: TestClient) -> None:
        """load_duty_roster_document raising a recoverable error → HTTP 500."""
        duty_mod = MagicMock()
        duty_mod.load_duty_roster_document.side_effect = ValueError("corrupt ssot")
        duty_mod.all_planned_duty_employee_ids.return_value = []
        with patch.dict("sys.modules", {"app.mod_sdk.duty_roster": duty_mod}):
            r = client.get("/api/system/duty-roster")
        assert r.status_code == 500
        assert "corrupt ssot" in r.json()["detail"]
