"""Branch-coverage tests for app.application.ops_closure_status.

Covers: _installed_employee_pack_ids, _duty_employee_area_map,
_build_roster_rows, build_ops_closure_status, _next_actions.
Focus on exception paths, empty inputs, and branch conditions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.ops_closure_status import (
    _build_roster_rows,
    _duty_employee_area_map,
    _installed_employee_pack_ids,
    _next_actions,
    build_ops_closure_status,
)

# ---------------------------------------------------------------------------
# _installed_employee_pack_ids
# ---------------------------------------------------------------------------


class TestInstalledEmployeePackIds:
    def test_returns_empty_when_mod_manager_raises(self):
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("no mods"),
        ):
            result = _installed_employee_pack_ids()
        assert result == set()

    def test_collects_packs_from_registry(self):
        mock_mgr = MagicMock()
        mock_mgr.all_mods_roots.return_value = ["/tmp/mods"]
        mock_mgr.list_loaded_mods.return_value = []

        mock_pack1 = {"id": "emp-a"}
        mock_pack2 = {"id": "emp-b"}
        mock_pack_empty = {"id": ""}

        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mock_mgr
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry"
            ) as mock_reg_cls,
        ):
            mock_reg = MagicMock()
            mock_reg.list_packs.return_value = [mock_pack1, mock_pack2, mock_pack_empty]
            mock_reg_cls.return_value = mock_reg
            result = _installed_employee_pack_ids()
        assert result == {"emp-a", "emp-b"}

    def test_falls_back_to_primary_mods_root(self):
        mock_mgr = MagicMock()
        mock_mgr.all_mods_roots.return_value = []
        mock_mgr.mods_root = "/tmp/primary_mods"
        mock_mgr.list_loaded_mods.return_value = []

        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mock_mgr
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry"
            ) as mock_reg_cls,
        ):
            mock_reg = MagicMock()
            mock_reg.list_packs.return_value = [{"id": "emp-x"}]
            mock_reg_cls.return_value = mock_reg
            result = _installed_employee_pack_ids()
        assert result == {"emp-x"}

    def test_skips_empty_mods_root(self):
        mock_mgr = MagicMock()
        mock_mgr.all_mods_roots.return_value = ["", None, "/tmp/mods"]
        mock_mgr.list_loaded_mods.return_value = []

        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mock_mgr
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry"
            ) as mock_reg_cls,
        ):
            mock_reg = MagicMock()
            mock_reg.list_packs.return_value = [{"id": "emp-y"}]
            mock_reg_cls.return_value = mock_reg
            result = _installed_employee_pack_ids()
        assert result == {"emp-y"}

    def test_all_mods_roots_raises_falls_back(self):
        mock_mgr = MagicMock()
        mock_mgr.all_mods_roots.side_effect = RuntimeError("fail")
        mock_mgr.mods_root = "/tmp/primary"
        mock_mgr.list_loaded_mods.return_value = []

        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mock_mgr
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry"
            ) as mock_reg_cls,
        ):
            mock_reg = MagicMock()
            mock_reg.list_packs.return_value = [{"id": "emp-z"}]
            mock_reg_cls.return_value = mock_reg
            result = _installed_employee_pack_ids()
        assert result == {"emp-z"}

    def test_collects_from_loaded_mods_employee_pack(self):
        mock_mgr = MagicMock()
        mock_mgr.all_mods_roots.return_value = ["/tmp/mods"]
        mock_mgr.list_loaded_mods.return_value = []

        # First call (registry) returns nothing; second mod_manager call returns employee_pack mods
        mock_mgr_2 = MagicMock()
        mod1 = MagicMock()
        mod1.artifact = "employee_pack"
        mod1.id = "loaded-emp-1"
        mod2 = MagicMock()
        mod2.artifact = "other"
        mod2.id = "loaded-other"
        mod3 = MagicMock()
        mod3.artifact = "  EMPLOYEE_PACK  "
        mod3.id = "loaded-emp-2"
        mock_mgr_2.list_loaded_mods.return_value = [mod1, mod2, mod3]

        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=[mock_mgr, mock_mgr_2],
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry"
            ) as mock_reg_cls,
        ):
            mock_reg = MagicMock()
            mock_reg.list_packs.return_value = []
            mock_reg_cls.return_value = mock_reg
            result = _installed_employee_pack_ids()
        assert "loaded-emp-1" in result
        assert "loaded-emp-2" in result
        assert "loaded-other" not in result

    def test_loaded_mods_raises_returns_collected(self):
        mock_mgr = MagicMock()
        mock_mgr.all_mods_roots.return_value = ["/tmp/mods"]
        mock_mgr.list_loaded_mods.return_value = []

        mock_mgr_2 = MagicMock()
        mock_mgr_2.list_loaded_mods.side_effect = RuntimeError("fail")

        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=[mock_mgr, mock_mgr_2],
            ),
            patch(
                "app.infrastructure.mods.employee_registry.EmployeeRegistry"
            ) as mock_reg_cls,
        ):
            mock_reg = MagicMock()
            mock_reg.list_packs.return_value = [{"id": "emp-from-reg"}]
            mock_reg_cls.return_value = mock_reg
            result = _installed_employee_pack_ids()
        assert result == {"emp-from-reg"}


# ---------------------------------------------------------------------------
# _duty_employee_area_map
# ---------------------------------------------------------------------------


class TestDutyEmployeeAreaMap:
    def test_empty_doc(self):
        with patch(
            "app.application.ops_closure_status.load_duty_roster_document",
            return_value={},
        ):
            result = _duty_employee_area_map()
        assert result == {}

    def test_areas_not_dict(self):
        with patch(
            "app.application.ops_closure_status.load_duty_roster_document",
            return_value={"areas": ["not", "a", "dict"]},
        ):
            result = _duty_employee_area_map()
        assert result == {}

    def test_block_not_dict_skipped(self):
        with patch(
            "app.application.ops_closure_status.load_duty_roster_document",
            return_value={"areas": {"zone1": "not-a-dict", "zone2": {"label": "Z2", "ids": ["e1"]}}},
        ):
            result = _duty_employee_area_map()
        assert result == {"e1": {"area_key": "zone2", "area_label": "Z2"}}

    def test_ids_not_list_skipped(self):
        with patch(
            "app.application.ops_closure_status.load_duty_roster_document",
            return_value={"areas": {"zone1": {"label": "Z1", "ids": "not-a-list"}}},
        ):
            result = _duty_employee_area_map()
        assert result == {}

    def test_label_falls_back_to_key(self):
        with patch(
            "app.application.ops_closure_status.load_duty_roster_document",
            return_value={"areas": {"zone1": {"ids": ["e1"]}}},
        ):
            result = _duty_employee_area_map()
        assert result == {"e1": {"area_key": "zone1", "area_label": "zone1"}}

    def test_empty_label_falls_back_to_key(self):
        with patch(
            "app.application.ops_closure_status.load_duty_roster_document",
            return_value={"areas": {"zone1": {"label": "  ", "ids": ["e1"]}}},
        ):
            result = _duty_employee_area_map()
        assert result == {"e1": {"area_key": "zone1", "area_label": "zone1"}}

    def test_empty_employee_id_skipped(self):
        with patch(
            "app.application.ops_closure_status.load_duty_roster_document",
            return_value={"areas": {"zone1": {"label": "Z1", "ids": ["", "  ", "e1", None]}}},
        ):
            result = _duty_employee_area_map()
        assert result == {"e1": {"area_key": "zone1", "area_label": "Z1"}}


# ---------------------------------------------------------------------------
# _build_roster_rows
# ---------------------------------------------------------------------------


class TestBuildRosterRows:
    def test_empty_planned(self):
        rows = _build_roster_rows(
            [], missing_remote_set=set(), local_packs=set(), area_map={}
        )
        assert rows == []

    def test_in_catalog_and_local_installed(self):
        rows = _build_roster_rows(
            ["emp-a"],
            missing_remote_set=set(),
            local_packs={"emp-a"},
            area_map={"emp-a": {"area_key": "z1", "area_label": "Zone1"}},
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["in_catalog"] is True
        assert row["local_installed"] is True
        assert row["needs_action"] is False
        assert row["area_key"] == "z1"
        assert row["area_label"] == "Zone1"

    def test_missing_remote_needs_action(self):
        rows = _build_roster_rows(
            ["emp-a"],
            missing_remote_set={"emp-a"},
            local_packs=set(),
            area_map={},
        )
        assert rows[0]["in_catalog"] is False
        assert rows[0]["local_installed"] is False
        assert rows[0]["needs_action"] is True

    def test_in_catalog_but_not_local_installed(self):
        rows = _build_roster_rows(
            ["emp-a"],
            missing_remote_set=set(),
            local_packs=set(),
            area_map={},
        )
        assert rows[0]["in_catalog"] is True
        assert rows[0]["local_installed"] is False
        assert rows[0]["needs_action"] is True

    def test_area_map_missing_uses_empty(self):
        rows = _build_roster_rows(
            ["emp-a"],
            missing_remote_set=set(),
            local_packs={"emp-a"},
            area_map={},
        )
        assert rows[0]["area_key"] == ""
        assert rows[0]["area_label"] == ""


# ---------------------------------------------------------------------------
# _next_actions
# ---------------------------------------------------------------------------


class TestNextActions:
    def test_no_issues_returns_ready_action(self):
        actions = _next_actions([], [], 0)
        assert actions == ["编制与本地安装均已就绪，可下达运维任务"]

    def test_missing_remote_action(self):
        actions = _next_actions(["emp-a"], [], 0)
        assert any("onboard" in a for a in actions)

    def test_missing_local_action(self):
        actions = _next_actions([], ["emp-a"], 0)
        assert any("install-local" in a for a in actions)

    def test_pending_cr_action(self):
        actions = _next_actions([], [], 3)
        assert any("Change Request" in a for a in actions)

    def test_all_three_actions(self):
        actions = _next_actions(["emp-a"], ["emp-b"], 2)
        assert len(actions) == 3


# ---------------------------------------------------------------------------
# build_ops_closure_status
# ---------------------------------------------------------------------------


class TestBuildOpsClosureStatus:
    def test_none_remote_health(self):
        with patch(
            "app.application.ops_closure_status.all_planned_duty_employee_ids",
            return_value=[],
        ):
            result = build_ops_closure_status(None)
        assert result["deliverable"] is True
        assert result["staffing"]["planned_count"] == 0

    def test_non_dict_remote_health(self):
        with patch(
            "app.application.ops_closure_status.all_planned_duty_employee_ids",
            return_value=[],
        ):
            result = build_ops_closure_status("not-a-dict")  # type: ignore[arg-type]
        assert result["deliverable"] is True

    def test_missing_remote_employees_creates_blocker(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=["emp-a", "emp-b"],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value={"emp-a", "emp-b"},
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status(
                {"staffing": {"missing_employees": ["emp-a"]}}
            )
        assert result["deliverable"] is False
        assert any(b["code"] == "REMOTE_STAFFING_GAP" for b in result["blockers"])

    def test_missing_local_packs_creates_blocker(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=["emp-a"],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status({"staffing": {}})
        assert result["deliverable"] is True  # no missing_remote, no pending_cr
        assert any(b["code"] == "LOCAL_EMPLOYEE_PACK_MISSING" for b in result["blockers"])

    def test_pending_change_requests_creates_blocker(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=[],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status(
                {"change_requests": {"pending": 5}}
            )
        assert result["deliverable"] is False
        assert any(b["code"] == "PENDING_CHANGE_REQUESTS" for b in result["blockers"])

    def test_extra_local_packs(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=["emp-a"],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value={"emp-a", "emp-extra"},
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status({"staffing": {}})
        assert "emp-extra" in result["extra_local_employee_pack_ids"]

    def test_staffing_local_merges_remote_fields(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=["emp-a"],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value={"emp-a"},
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status(
                {
                    "staffing": {
                        "planned_count": 10,
                        "registered_count": 8,
                        "missing_employees": [],
                    }
                }
            )
        assert result["staffing"]["remote_planned_count"] == 10
        assert result["staffing"]["remote_registered_count"] == 8
        assert result["staffing"]["planned_count"] == 1
        assert result["staffing"]["registered_count"] == 1

    def test_staffing_not_dict_handled(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=[],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status({"staffing": "not-a-dict"})
        assert result["staffing"]["planned_count"] == 0

    def test_change_requests_not_dict_handled(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=[],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status({"change_requests": "not-a-dict"})
        assert result["deliverable"] is True

    def test_roster_rows_built(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=["emp-a", "emp-b"],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value={"emp-a"},
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={"emp-a": {"area_key": "z1", "area_label": "Z1"}},
            ),
        ):
            result = build_ops_closure_status({"staffing": {}})
        assert len(result["roster_rows"]) == 2
        emp_a = next(r for r in result["roster_rows"] if r["id"] == "emp-a")
        assert emp_a["local_installed"] is True
        assert emp_a["area_key"] == "z1"

    def test_missing_remote_truncated_to_50(self):
        many_missing = [f"emp-{i}" for i in range(60)]
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=[],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status(
                {"staffing": {"missing_employees": many_missing}}
            )
        blocker = next(b for b in result["blockers"] if b["code"] == "REMOTE_STAFFING_GAP")
        assert len(blocker["employee_ids"]) == 50
        assert blocker["count"] == 60

    def test_planned_local_installed_count(self):
        with (
            patch(
                "app.application.ops_closure_status.all_planned_duty_employee_ids",
                return_value=["emp-a", "emp-b", "emp-c"],
            ),
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value={"emp-a", "emp-b", "emp-extra"},
            ),
            patch(
                "app.application.ops_closure_status._duty_employee_area_map",
                return_value={},
            ),
        ):
            result = build_ops_closure_status({"staffing": {}})
        assert result["planned_local_installed_count"] == 2
