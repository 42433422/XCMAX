"""onboarding_seed_mapper 单元测试。

覆盖：行业 manifest 加载（env override / 缺失 / 非法 JSON / 非 dict）、
种子 profile 派生（缺省 + customers/products 子系统）、字段演示值映射
（semantic / number / enum / 特殊 key / 兜底）、客户与产品行构造。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.application import onboarding_seed_mapper as osm


def _write_manifest(mods_root, mod_id: str, data) -> None:
    mod_dir = mods_root / mod_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    (mod_dir / "manifest.json").write_text(text, encoding="utf-8")


def _rich_manifest() -> dict:
    return {
        "industry": {
            "subsystems": {
                "customers": {
                    "entity": "会员",
                    "label": "会员管理",
                    "fields": [
                        {"key": "customer_name", "type": "text", "label": "会员名"},
                        {"key": "contact_phone", "type": "text"},
                        {
                            "key": "level",
                            "type": "enum",
                            "validators": [{"type": "oneOf", "params": ["黄金", "白银"]}],
                        },
                        {"key": "visits", "type": "number"},
                        {"key": "note", "type": "text", "semantic": "entity_name"},
                        "not-a-dict",
                        {"type": "text"},  # 无 key 跳过
                    ],
                },
                "products": {
                    "entity": "商品",
                    "label": "商品库",
                    "fields": [
                        {"key": "name", "type": "text", "label": "商品名"},
                        {"key": "model_number", "type": "text", "semantic": "model"},
                        {"key": "specification", "type": "text", "semantic": "spec"},
                        {"key": "price", "type": "number", "semantic": "price"},
                        {"key": "quantity", "type": "number"},
                        {"key": "unit", "type": "text"},
                    ],
                },
            }
        }
    }


# ── load_industry_manifest ────────────────────────────────────────────────


class TestLoadIndustryManifest:
    def test_no_mod_id_returns_none(self, monkeypatch):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: None)
        assert osm.load_industry_manifest("未知行业") is None

    def test_manifest_file_missing_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        assert osm.load_industry_manifest("行业") is None

    def test_invalid_json_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(tmp_path, "mod-x", "{not json")
        assert osm.load_industry_manifest("行业") is None

    def test_non_dict_json_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(tmp_path, "mod-x", ["a", "b"])
        assert osm.load_industry_manifest("行业") is None

    def test_valid_manifest_returned(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(tmp_path, "mod-x", _rich_manifest())
        data = osm.load_industry_manifest("行业")
        assert data is not None
        assert data["industry"]["subsystems"]["customers"]["entity"] == "会员"


# ── resolve_onboarding_seed_profile ──────────────────────────────────────


class TestResolveOnboardingSeedProfile:
    def test_empty_industry_defaults(self, monkeypatch):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: None)
        profile = osm.resolve_onboarding_seed_profile("")
        assert profile.industry_id == "通用"
        assert profile.customer_entity == "客户"
        assert profile.product_entity == "产品"
        assert profile.demo_customer_name == "XC 演示客户"
        assert profile.demo_product_name == "XC 演示产品"
        assert profile.customer_query_hint == "XC 演示客户"
        assert profile.subsystems_meta == {}

    def test_manifest_subsystems_mapped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(tmp_path, "mod-x", _rich_manifest())
        profile = osm.resolve_onboarding_seed_profile("珠宝")
        assert profile.mod_id == "mod-x"
        assert profile.customer_entity == "会员"
        assert profile.product_entity == "商品"
        assert profile.demo_customer_name == "XC 演示会员"
        assert profile.demo_product_name == "XC 演示商品"
        assert profile.customer_query_hint == "XC 演示会员"
        assert profile.subsystems_meta["customers"] == {"entity": "会员", "label": "会员管理"}
        assert profile.subsystems_meta["products"] == {"entity": "商品", "label": "商品库"}

    def test_manifest_without_subsystems_keeps_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(tmp_path, "mod-x", {"industry": {}})
        profile = osm.resolve_onboarding_seed_profile("行业")
        assert profile.customer_entity == "客户"
        assert profile.product_entity == "产品"
        assert profile.subsystems_meta == {}


# ── _demo_value_for_field ─────────────────────────────────────────────────


class TestDemoValueForField:
    def test_semantic_entity_name_callable(self):
        assert (
            osm._demo_value_for_field({"semantic": "entity_name"}, ctx={"entity": "会员"})
            == "XC 演示会员"
        )

    def test_semantic_static_values(self):
        assert osm._demo_value_for_field({"semantic": "model"}, ctx={}) == "DEMO-001"
        assert osm._demo_value_for_field({"semantic": "spec"}, ctx={}) == "标准"
        assert osm._demo_value_for_field({"semantic": "price"}, ctx={}) == Decimal("99.00")
        assert osm._demo_value_for_field({"semantic": "batch"}, ctx={}) == "BATCH-001"
        assert osm._demo_value_for_field({"semantic": "expiry"}, ctx={}) is None

    def test_semantic_foreign_ref(self):
        assert (
            osm._demo_value_for_field(
                {"semantic": "foreign_ref"}, ctx={"customer_demo_name": "XC 演示会员"}
            )
            == "XC 演示会员"
        )
        assert osm._demo_value_for_field({"semantic": "foreign_ref"}, ctx={}) == "XC 演示客户"

    def test_number_type(self):
        assert osm._demo_value_for_field({"type": "number"}, ctx={}) == Decimal("1")

    def test_enum_uses_first_oneof_param(self):
        field = {"type": "enum", "validators": [{"type": "oneOf", "params": ["黄金", "白银"]}]}
        assert osm._demo_value_for_field(field, ctx={}) == "黄金"

    def test_enum_without_validators_falls_back(self):
        assert osm._demo_value_for_field({"type": "enum"}, ctx={}) == "选项A"
        field = {"type": "enum", "validators": [{"type": "oneOf", "params": []}]}
        assert osm._demo_value_for_field(field, ctx={}) == "选项A"

    def test_special_keys(self):
        assert osm._demo_value_for_field({"key": "contact_phone"}, ctx={}) == "13800000000"
        assert osm._demo_value_for_field({"key": "contact_person"}, ctx={}) == "演示联系人"
        assert (
            osm._demo_value_for_field({"key": "address"}, ctx={"industry_id": "珠宝"})
            == "珠宝 · 首启演示地址"
        )
        assert (
            osm._demo_value_for_field({"key": "contact_address"}, ctx={"industry_id": "通用"})
            == "通用 · 首启演示地址"
        )
        assert osm._demo_value_for_field({"key": "unit"}, ctx={}) == "个"

    def test_fallback_label_or_key_or_default(self):
        assert osm._demo_value_for_field({"label": "备注"}, ctx={}) == "演示备注"
        assert osm._demo_value_for_field({"key": "remark"}, ctx={}) == "演示remark"
        assert osm._demo_value_for_field({}, ctx={}) == "演示值"


# ── build_customer_row / build_product_row ───────────────────────────────


class TestBuildCustomerRow:
    def test_no_manifest_fallback(self, monkeypatch):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: None)
        profile = osm.OnboardingSeedProfile(industry_id="通用")
        row = osm.build_customer_row(tenant_id=7, profile=profile)
        assert row == {
            "tenant_id": 7,
            "customer_name": "XC 演示客户",
            "contact_person": "演示联系人",
            "contact_phone": "13800000000",
            "contact_address": "通用 · 首启演示地址",
        }

    def test_fields_mapped_and_name_overridden(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(tmp_path, "mod-x", _rich_manifest())
        profile = osm.resolve_onboarding_seed_profile("珠宝")
        row = osm.build_customer_row(tenant_id=1, profile=profile)
        assert row["tenant_id"] == 1
        assert row["customer_name"] == "XC 演示会员"  # 强制覆盖
        assert row["contact_phone"] == "13800000000"
        assert row["contact_person"] == "演示联系人"
        assert "通用" not in row["contact_address"]


class TestBuildProductRow:
    def test_no_manifest_defaults(self, monkeypatch):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: None)
        profile = osm.OnboardingSeedProfile(industry_id="通用")
        row = osm.build_product_row(tenant_id=3, profile=profile)
        assert row == {
            "tenant_id": 3,
            "name": "XC 演示产品",
            "model_number": "DEMO-001",
            "specification": "通用 首启样例 SKU",
            "price": Decimal("99.00"),
            "quantity": 10,
            "category": "通用",
            "brand": "XCAGI",
            "unit": "个",
            "is_active": 1,
        }

    def test_fields_mapped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(tmp_path, "mod-x", _rich_manifest())
        profile = osm.resolve_onboarding_seed_profile("珠宝")
        row = osm.build_product_row(tenant_id=2, profile=profile)
        assert row["name"] == "XC 演示商品"
        assert row["model_number"] == "DEMO-001"  # semantic model
        assert row["specification"] == "标准"  # semantic spec
        assert row["price"] == Decimal("99.00")  # semantic price
        assert row["quantity"] == 1  # number type → Decimal("1") → int
        assert row["unit"] == "个"
        assert row["category"] == "珠宝"
        assert row["is_active"] == 1

    def test_non_decimal_price_falls_back(self, monkeypatch, tmp_path):
        monkeypatch.setattr(osm, "industry_mod_id_for", lambda iid: "mod-x")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        _write_manifest(
            tmp_path,
            "mod-x",
            {
                "industry": {
                    "subsystems": {
                        "products": {
                            "entity": "商品",
                            "fields": [{"key": "price", "type": "text", "label": "售价"}],
                        }
                    }
                }
            },
        )
        profile = osm.resolve_onboarding_seed_profile("行业")
        row = osm.build_product_row(tenant_id=1, profile=profile)
        assert row["price"] == Decimal("99.00")  # text 映射非 Decimal → 兜底


# ── _resolve_mod_manifest_root ────────────────────────────────────────────


class TestResolveModManifestRoot:
    """覆盖 _resolve_mod_manifest_root 双路径 fallback 逻辑。

    铁律 3 禁止只测 happy path；铁律 6 分支覆盖 ≠ 行覆盖。
    真实集成测试：用 FHD/mods/ 与 FHD/XCAGI/mods/ 真实目录（不 mock 被测函数）。
    """

    def test_mod_in_fhd_mods_returns_fhd_mods(self):
        """coating-industry 在 FHD/mods/ → 返回 FHD/mods 路径（编辑源优先）。"""
        result = osm._resolve_mod_manifest_root("coating-industry")
        assert result is not None
        assert result.name == "mods"
        assert result.parent.name == "FHD"
        assert (result / "coating-industry" / "manifest.json").is_file()

    def test_mod_only_in_xcagi_mods_returns_xcagi_mods(self):
        """attendance-industry 已迁移至 XCAGI/mods/ → fallback 到 FHD/XCAGI/mods。

        commit a34114a0a 的核心回归测试：FHD/mods/ 找不到时必须 fallback。
        """
        result = osm._resolve_mod_manifest_root("attendance-industry")
        assert result is not None
        assert result.name == "mods"
        assert result.parent.name == "XCAGI"
        assert (result / "attendance-industry" / "manifest.json").is_file()

    def test_mod_not_found_returns_none(self):
        """两个候选路径都不存在 → 返回 None。"""
        result = osm._resolve_mod_manifest_root("nonexistent-mod-xyz-99999")
        assert result is None

    def test_empty_mod_id_returns_none(self):
        """空 mod_id → 两个候选路径下 manifest.json 都不存在 → 返回 None。"""
        result = osm._resolve_mod_manifest_root("")
        assert result is None

    def test_load_industry_manifest_uses_fallback_for_attendance(self):
        """load_industry_manifest 通过 _resolve_mod_manifest_root 找到 attendance-industry。

        验证 _resolve_mod_manifest_root 被 load_industry_manifest 正确调用（而非仅 _fhd_mods_root 单路径）。
        这是 commit a34114a0a 的端到端回归测试。
        """
        baseline_path = (
            Path(osm.__file__).resolve().parents[2] / "config" / "industry_baseline.json"
        )
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        attendance_iid = next(
            (
                iid
                for iid, spec in (baseline.get("industry_packages") or {}).items()
                if isinstance(spec, dict) and spec.get("mod_id") == "attendance-industry"
            ),
            None,
        )
        assert attendance_iid is not None, "baseline 缺少 attendance-industry 映射"

        data = osm.load_industry_manifest(attendance_iid)
        assert data is not None
        assert str(data.get("id") or "") == "attendance-industry"
