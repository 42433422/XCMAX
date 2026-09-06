"""员工联系人 SSOT 派生（employee_ssot_contacts）单元测试。

覆盖：manifest 元数据加载（lru_cache）、显示名/描述回退、联系人记录构造、
超级员工联系人、三端统一 contacts 派生（去重 / installed / planned / 企业端上架）、
label 映射派生。
"""

from __future__ import annotations

import json

import pytest

from app.mod_sdk import assistant_ssot
from app.mod_sdk import employee_ssot as ess
from app.mod_sdk import employee_ssot_contacts as esc


@pytest.fixture(autouse=True)
def _clear_manifest_cache():
    """每个用例前后清空 lru_cache，避免 manifest 元数据串测试。"""
    orig = esc.load_employee_manifest_meta
    if hasattr(orig, "cache_clear"):
        orig.cache_clear()
    yield
    if hasattr(orig, "cache_clear"):
        orig.cache_clear()


def _mk_config_root(tmp_path, manifests: dict[str, dict]):
    """构造 ``<root>/config`` + ``<root>/mods/_employees/<emp>/manifest.json``。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    for emp_id, data in manifests.items():
        emp_dir = tmp_path / "mods" / "_employees" / emp_id
        emp_dir.mkdir(parents=True, exist_ok=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    return cfg_dir


def _patch_cfg_dir(monkeypatch, cfg_dir):
    monkeypatch.setattr(esc, "resolve_fhd_config_dir", lambda: cfg_dir)


def _patch_super_registry(monkeypatch, registry: dict, factory_ids: frozenset[str] = frozenset()):
    monkeypatch.setattr(assistant_ssot, "super_employees", lambda: registry)
    monkeypatch.setattr(assistant_ssot, "is_factory_employee", lambda eid: eid in factory_ids)


def _patch_admin_roster(monkeypatch, departments, on_duty):
    monkeypatch.setattr(
        ess,
        "derive_admin_duty_roster",
        lambda installed_ids=None: {
            "departments": departments,
            "planned_employee_ids": sorted(
                {
                    e["id"]
                    for d in departments
                    if isinstance(d, dict)
                    for e in d.get("employees", [])
                    if isinstance(e, dict)
                }
            ),
            "on_duty_employee_ids": sorted(on_duty),
        },
    )


def _patch_enterprise(monkeypatch, employees: dict):
    monkeypatch.setattr(ess, "load_enterprise_employees", lambda: employees)


# ── load_employee_manifest_meta ──────────────────────────────────────────


class TestLoadEmployeeManifestMeta:
    def test_config_dir_none_returns_empty(self, monkeypatch):
        _patch_cfg_dir(monkeypatch, None)
        assert esc.load_employee_manifest_meta() == {}

    def test_employees_dir_missing_returns_empty(self, monkeypatch, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        _patch_cfg_dir(monkeypatch, cfg_dir)
        assert esc.load_employee_manifest_meta() == {}

    def test_valid_manifest_full_fields(self, monkeypatch, tmp_path):
        cfg = _mk_config_root(
            tmp_path, {"emp-a": {"id": "emp-a", "name": "员工甲", "description": "描述甲"}}
        )
        _patch_cfg_dir(monkeypatch, cfg)
        assert esc.load_employee_manifest_meta() == {
            "emp-a": {"name": "员工甲", "description": "描述甲"}
        }

    def test_name_falls_back_to_employee_label(self, monkeypatch, tmp_path):
        cfg = _mk_config_root(tmp_path, {"emp-b": {"id": "emp-b", "employee": {"label": "标签乙"}}})
        _patch_cfg_dir(monkeypatch, cfg)
        assert esc.load_employee_manifest_meta() == {"emp-b": {"name": "标签乙"}}

    def test_description_only(self, monkeypatch, tmp_path):
        cfg = _mk_config_root(tmp_path, {"emp-c": {"id": "emp-c", "description": "仅描述"}})
        _patch_cfg_dir(monkeypatch, cfg)
        assert esc.load_employee_manifest_meta() == {"emp-c": {"description": "仅描述"}}

    def test_skips_non_dict_manifest(self, monkeypatch, tmp_path):
        cfg = _mk_config_root(tmp_path, {"emp-a": {"id": "emp-a", "name": "甲"}})
        bad_dir = tmp_path / "mods" / "_employees" / "emp-bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "manifest.json").write_text('["not", "a", "dict"]', encoding="utf-8")
        _patch_cfg_dir(monkeypatch, cfg)
        assert esc.load_employee_manifest_meta() == {"emp-a": {"name": "甲"}}

    def test_skips_missing_id(self, monkeypatch, tmp_path):
        cfg = _mk_config_root(tmp_path, {"emp-x": {"name": "无ID", "description": "跳过"}})
        _patch_cfg_dir(monkeypatch, cfg)
        assert esc.load_employee_manifest_meta() == {}

    def test_skips_empty_name_and_description(self, monkeypatch, tmp_path):
        cfg = _mk_config_root(tmp_path, {"emp-e": {"id": "emp-e", "name": "  ", "description": ""}})
        _patch_cfg_dir(monkeypatch, cfg)
        assert esc.load_employee_manifest_meta() == {}

    def test_skips_invalid_json(self, monkeypatch, tmp_path):
        cfg = _mk_config_root(tmp_path, {"emp-a": {"id": "emp-a", "name": "甲"}})
        bad_dir = tmp_path / "mods" / "_employees" / "emp-corrupt"
        bad_dir.mkdir(parents=True)
        (bad_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")
        _patch_cfg_dir(monkeypatch, cfg)
        assert esc.load_employee_manifest_meta() == {"emp-a": {"name": "甲"}}


# ── employee_display_name / employee_description ─────────────────────────


class TestDisplayNameAndDescription:
    def _patch_meta(self, monkeypatch, meta):
        monkeypatch.setattr(esc, "load_employee_manifest_meta", lambda: meta)

    def test_display_name_from_manifest(self, monkeypatch):
        self._patch_meta(monkeypatch, {"emp-a": {"name": "员工甲"}})
        assert esc.employee_display_name("emp-a") == "员工甲"

    def test_display_name_falls_back_to_id(self, monkeypatch):
        self._patch_meta(monkeypatch, {})
        assert esc.employee_display_name("emp-unknown") == "emp-unknown"

    def test_display_name_strips_whitespace_id(self, monkeypatch):
        self._patch_meta(monkeypatch, {"emp-a": {"name": "员工甲"}})
        assert esc.employee_display_name("  emp-a  ") == "员工甲"

    def test_description_from_manifest(self, monkeypatch):
        self._patch_meta(monkeypatch, {"emp-a": {"description": "负责打单"}})
        assert esc.employee_description("emp-a") == "负责打单"

    def test_description_unknown_returns_empty(self, monkeypatch):
        self._patch_meta(monkeypatch, {})
        assert esc.employee_description("emp-unknown") == ""


# ── _employee_contact_record ─────────────────────────────────────────────


class TestEmployeeContactRecord:
    def test_default_routes_and_fields(self):
        row = esc._employee_contact_record(
            "label-printer",
            display_name="标签员",
            department="execution",
            source="installed",
            installed=True,
        )
        assert row["employee_id"] == "label-printer"
        assert row["surface_name"] == "标签员"
        assert row["runnable"] is True and row["online"] is True
        assert row["pinned"] is False
        assert row["avatar_key"] == "label"
        assert row["contact_route"] == "/api/admin/employees/chat/label-printer"
        assert row["mobile_contact_route"] == "/api/mobile/v1/employees/label-printer/messages"
        assert row["capabilities"] == []
        assert row["last_task_status"] == "idle"

    def test_custom_routes_and_surface_name(self):
        row = esc._employee_contact_record(
            "emp-x",
            display_name="X",
            department="super",
            source="codex",
            installed=True,
            surface_name="小X",
            pinned=True,
            capabilities=["chat"],
            contact_route="/custom/route",
            mobile_contact_route="/custom/mobile",
            last_task_status="running",
        )
        assert row["surface_name"] == "小X"
        assert row["pinned"] is True
        assert row["capabilities"] == ["chat"]
        assert row["contact_route"] == "/custom/route"
        assert row["mobile_contact_route"] == "/custom/mobile"
        assert row["last_task_status"] == "running"

    @pytest.mark.parametrize(
        ("source", "installed", "expected"),
        [
            ("installed", True, True),
            ("builtin", True, True),
            ("codex", True, True),
            ("planned", True, False),
            ("installed", False, False),
        ],
    )
    def test_runnable_matrix(self, source, installed, expected):
        row = esc._employee_contact_record(
            "emp", display_name="E", department="d", source=source, installed=installed
        )
        assert row["runnable"] is expected
        assert row["online"] is expected

    def test_empty_id_avatar_fallback(self):
        row = esc._employee_contact_record(
            "", display_name="E", department="d", source="planned", installed=False
        )
        assert row["avatar_key"] == "employee"


# ── _super_employee_contacts ─────────────────────────────────────────────


class TestSuperEmployeeContacts:
    def _registry(self):
        return {
            "codex-super-employee": {
                "display_name": "Codex 超级员工",
                "summary": "Codex 总控",
                "display_tool": "Codex",
            },
            "cursor-super-employee": {"display_name": "Cursor 超级员工", "display_tool": "Cursor"},
            "claude-super-employee": {"display_name": "Claude 超级员工", "summary": ""},
            "trae-super-employee": {"display_name": "Trae 超级员工", "summary": "Trae 派工"},
        }

    def test_all_four_in_order(self, monkeypatch):
        _patch_super_registry(monkeypatch, self._registry())
        rows = esc._super_employee_contacts()
        assert [r["employee_id"] for r in rows] == list(esc.SUPER_EMPLOYEE_CONTACT_ORDER)

    def test_codex_source_and_pinned(self, monkeypatch):
        _patch_super_registry(monkeypatch, self._registry())
        rows = {r["employee_id"]: r for r in esc._super_employee_contacts()}
        codex = rows["codex-super-employee"]
        assert codex["source"] == "codex" and codex["pinned"] is True
        assert codex["department"] == "super" and codex["installed"] is True
        assert codex["description"] == "Codex 总控"
        assert codex["contact_route"] == "/api/admin/codex-super-employee/messages"
        others = rows["cursor-super-employee"]
        assert others["source"] == "builtin" and others["pinned"] is False

    def test_summary_fallback_uses_display_tool(self, monkeypatch):
        _patch_super_registry(monkeypatch, self._registry())
        rows = {r["employee_id"]: r for r in esc._super_employee_contacts()}
        assert "Cursor" in rows["cursor-super-employee"]["description"]
        assert "超级员工" in rows["cursor-super-employee"]["description"]

    def test_factory_employee_skipped(self, monkeypatch):
        _patch_super_registry(
            monkeypatch, self._registry(), factory_ids=frozenset({"trae-super-employee"})
        )
        ids = [r["employee_id"] for r in esc._super_employee_contacts()]
        assert "trae-super-employee" not in ids
        assert len(ids) == 3

    def test_missing_registry_entry_skipped(self, monkeypatch):
        registry = self._registry()
        del registry["claude-super-employee"]
        _patch_super_registry(monkeypatch, registry)
        ids = [r["employee_id"] for r in esc._super_employee_contacts()]
        assert "claude-super-employee" not in ids


# ── derive_employee_contacts ─────────────────────────────────────────────


class TestDeriveEmployeeContacts:
    def _setup(
        self,
        monkeypatch,
        *,
        registry=None,
        factory_ids=frozenset(),
        manifests=None,
        departments=None,
        on_duty=(),
        enterprise=None,
    ):
        _patch_super_registry(monkeypatch, registry or {}, factory_ids)
        monkeypatch.setattr(esc, "load_employee_manifest_meta", lambda: manifests or {})
        _patch_admin_roster(monkeypatch, departments or [], set(on_duty))
        _patch_enterprise(monkeypatch, enterprise or {})

    def test_admin_installed_vs_planned(self, monkeypatch):
        departments = [
            {
                "id": "execution",
                "employees": [{"id": "emp-on"}, {"id": "emp-off"}],
            }
        ]
        self._setup(
            monkeypatch,
            departments=departments,
            on_duty={"emp-on"},
            manifests={"emp-on": {"name": "在岗员工", "description": "打单"}},
        )
        rows = {r["employee_id"]: r for r in esc.derive_employee_contacts(include_super=False)}
        assert rows["emp-on"]["source"] == "installed"
        assert rows["emp-on"]["installed"] is True and rows["emp-on"]["runnable"] is True
        assert rows["emp-on"]["display_name"] == "在岗员工"
        assert rows["emp-on"]["description"] == "打单"
        assert rows["emp-off"]["source"] == "planned"
        assert rows["emp-off"]["installed"] is False and rows["emp-off"]["runnable"] is False
        assert rows["emp-off"]["description"] == "编制内但未安装员工包"

    def test_installed_default_description(self, monkeypatch):
        departments = [{"id": "service", "employees": [{"id": "emp-on"}]}]
        self._setup(monkeypatch, departments=departments, on_duty={"emp-on"})
        rows = {r["employee_id"]: r for r in esc.derive_employee_contacts(include_super=False)}
        assert rows["emp-on"]["description"] == "已安装，可联系"

    def test_department_fallback_chain(self, monkeypatch):
        departments = [
            {"key": "tools", "employees": [{"id": "emp-k"}]},  # 无 id → 用 key
            {"label": "仅标签", "employees": [{"id": "emp-l"}]},  # 无 id/key → 用 label
            {"employees": [{"id": "emp-d"}]},  # 全缺 → "admin"
        ]
        self._setup(monkeypatch, departments=departments)
        rows = {r["employee_id"]: r for r in esc.derive_employee_contacts(include_super=False)}
        assert rows["emp-k"]["department"] == "tools"
        assert rows["emp-l"]["department"] == "仅标签"
        assert rows["emp-d"]["department"] == "admin"

    def test_skips_malformed_dept_and_employee(self, monkeypatch):
        departments = [
            "not-a-dict",
            {"id": "execution", "employees": ["bad-emp", {"id": "  "}, {"id": "emp-ok"}]},
        ]
        self._setup(monkeypatch, departments=departments)
        rows = esc.derive_employee_contacts(include_super=False)
        assert [r["employee_id"] for r in rows] == ["emp-ok"]

    def test_include_super_false_excludes_super(self, monkeypatch):
        self._setup(
            monkeypatch,
            registry={"codex-super-employee": {"display_name": "Codex"}},
        )
        rows = esc.derive_employee_contacts(include_super=False)
        assert all(r["department"] != "super" for r in rows)

    def test_super_dedup_against_admin(self, monkeypatch):
        departments = [{"id": "super", "employees": [{"id": "codex-super-employee"}]}]
        self._setup(
            monkeypatch,
            registry={"codex-super-employee": {"display_name": "Codex 总控"}},
            departments=departments,
            on_duty={"codex-super-employee"},
        )
        rows = esc.derive_employee_contacts()
        codex_rows = [r for r in rows if r["employee_id"] == "codex-super-employee"]
        assert len(codex_rows) == 1
        assert codex_rows[0]["source"] == "codex"  # 超管版本优先，admin 重复被去重

    def test_enterprise_listed_included_unlisted_skipped(self, monkeypatch):
        enterprise = {
            "wechat_contacts": {
                "id": "wechat_contacts",
                "label": "微信触点",
                "enterprise_layer": "service",
                "listing": "listed",
            },
            "lan_gate": {
                "id": "lan_gate",
                "label": "局域网门禁",
                "enterprise_layer": "tools",
                "listing": "unlisted",
            },
        }
        self._setup(monkeypatch, enterprise=enterprise)
        rows = {r["employee_id"]: r for r in esc.derive_employee_contacts(include_super=False)}
        assert "wechat_contacts" in rows
        assert rows["wechat_contacts"]["department"] == "service"
        assert rows["wechat_contacts"]["display_name"] == "微信触点"
        assert "lan_gate" not in rows

    def test_enterprise_installed_flag_from_installed_ids(self, monkeypatch):
        enterprise = {
            "wechat_contacts": {
                "id": "wechat_contacts",
                "label": "微信触点",
                "enterprise_layer": "service",
                "listing": "listed",
            },
        }
        self._setup(monkeypatch, enterprise=enterprise)
        rows = {
            r["employee_id"]: r
            for r in esc.derive_employee_contacts(
                installed_ids={" wechat_contacts ", ""}, include_super=False
            )
        }
        assert rows["wechat_contacts"]["source"] == "installed"
        assert rows["wechat_contacts"]["installed"] is True

    def test_enterprise_display_fallback_and_layer_default(self, monkeypatch):
        enterprise = {
            "emp-no-label": {
                "id": "emp-no-label",
                "label": "",
                "enterprise_layer": "",
                "listing": "listed",
            },
        }
        self._setup(
            monkeypatch,
            enterprise=enterprise,
            manifests={"emp-no-label": {"name": "清单名", "description": "来自清单"}},
        )
        rows = {r["employee_id"]: r for r in esc.derive_employee_contacts(include_super=False)}
        row = rows["emp-no-label"]
        assert row["display_name"] == "清单名"  # label 空 → manifest name
        assert row["department"] == "management"  # layer 空 → 兜底
        assert row["description"] == "来自清单"

    def test_enterprise_excluded_when_flag_false(self, monkeypatch):
        enterprise = {
            "wechat_contacts": {
                "id": "wechat_contacts",
                "label": "微信触点",
                "enterprise_layer": "service",
                "listing": "listed",
            },
        }
        self._setup(monkeypatch, enterprise=enterprise)
        rows = esc.derive_employee_contacts(include_super=False, include_enterprise_listed=False)
        assert all(r["employee_id"] != "wechat_contacts" for r in rows)

    def test_enterprise_dedup_against_admin(self, monkeypatch):
        departments = [{"id": "service", "employees": [{"id": "wechat_contacts"}]}]
        enterprise = {
            "wechat_contacts": {
                "id": "wechat_contacts",
                "label": "微信触点",
                "enterprise_layer": "service",
                "listing": "listed",
            },
        }
        self._setup(monkeypatch, departments=departments, enterprise=enterprise)
        rows = esc.derive_employee_contacts(include_super=False)
        assert [r["employee_id"] for r in rows].count("wechat_contacts") == 1

    def test_none_installed_ids_treated_as_empty(self, monkeypatch):
        departments = [{"id": "execution", "employees": [{"id": "emp-a"}]}]
        self._setup(monkeypatch, departments=departments)
        rows = {
            r["employee_id"]: r for r in esc.derive_employee_contacts(None, include_super=False)
        }
        assert rows["emp-a"]["installed"] is False

    def test_super_rows_empty_or_duplicate_id_skipped(self, monkeypatch):
        monkeypatch.setattr(
            esc,
            "_super_employee_contacts",
            lambda: [
                {"employee_id": "  "},
                {"employee_id": "emp-dup", "department": "super"},
                {"employee_id": "emp-dup", "department": "super"},
            ],
        )
        monkeypatch.setattr(esc, "load_employee_manifest_meta", lambda: {})
        _patch_admin_roster(monkeypatch, [], set())
        _patch_enterprise(monkeypatch, {})
        rows = esc.derive_employee_contacts()
        assert [r["employee_id"] for r in rows] == ["emp-dup"]


# ── employee_label_maps ──────────────────────────────────────────────────


class TestEmployeeLabelMaps:
    def test_maps_derived_from_manifest_meta(self, monkeypatch):
        monkeypatch.setattr(
            esc,
            "load_employee_manifest_meta",
            lambda: {
                "emp-a": {"name": "员工甲", "description": "描述甲"},
                "emp-b": {"name": "员工乙"},
                "emp-c": {"description": "仅描述"},
            },
        )
        labels, descriptions = esc.employee_label_maps()
        assert labels == {"emp-a": "员工甲", "emp-b": "员工乙"}
        assert descriptions == {"emp-a": "描述甲", "emp-c": "仅描述"}

    def test_empty_meta_returns_empty_maps(self, monkeypatch):
        monkeypatch.setattr(esc, "load_employee_manifest_meta", lambda: {})
        assert esc.employee_label_maps() == ({}, {})
