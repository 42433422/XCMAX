"""industry_package_validator 单元测试。

覆盖 iter_industry_package_manifests() 双路径去重 + 边界场景。

铁律 3 禁止只测 happy path；铁律 6 分支覆盖 ≠ 行覆盖。
真实集成测试 + tmp_path 边界场景双管齐下：
- 真实场景：FHD/mods/coating-industry + FHD/XCAGI/mods/attendance-industry 双路径命中
- tmp_path：mods_root 缺失 / 非 -industry 跳过 / manifest 缺失 / 同名去重 / fallback 补齐
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.contracts import industry_package_validator as ipv


def _make_mod(root: Path, mod_id: str, content: str = "{}") -> Path:
    """在 root 下创建 mod_id/manifest.json，返回 manifest 路径。"""
    manifest = root / mod_id / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(content, encoding="utf-8")
    return manifest


class TestIterIndustryPackageManifestsRealEnv:
    """真实环境（FHD/mods + FHD/XCAGI/mods）双路径命中验证。"""

    def test_finds_coating_in_fhd_mods_first(self):
        """coating-industry 同时存在于两路径 → 编辑源（FHD/mods）优先。"""
        manifests = ipv.iter_industry_package_manifests()
        coating = [m for m in manifests if m.parent.name == "coating-industry"]
        assert len(coating) == 1, "coating-industry 应只出现一次（去重）"
        # 编辑源优先：路径中包含 FHD/ 而非 XCAGI/
        assert "FHD" in coating[0].parts
        assert "XCAGI" not in coating[0].parts

    def test_finds_attendance_in_xcagi_mods_fallback(self):
        """attendance-industry 仅在 FHD/XCAGI/mods/ → fallback 路径补齐。

        commit a34114a0a 的回归测试：双路径扫描避免迁移期间漏检。
        """
        manifests = ipv.iter_industry_package_manifests()
        attendance = [m for m in manifests if m.parent.name == "attendance-industry"]
        assert len(attendance) == 1
        assert "XCAGI" in attendance[0].parts

    def test_returns_list_of_manifest_paths(self):
        """返回类型 list[Path]，每项都以 manifest.json 结尾，父目录以 -industry 结尾。"""
        manifests = ipv.iter_industry_package_manifests()
        assert isinstance(manifests, list)
        assert all(isinstance(m, Path) for m in manifests)
        assert all(m.name == "manifest.json" for m in manifests)
        assert all(m.parent.name.endswith("-industry") for m in manifests)

    def test_at_least_two_packages_present(self):
        """真实环境至少有 coating-industry + attendance-industry 两个包。"""
        manifests = ipv.iter_industry_package_manifests()
        ids = {m.parent.name for m in manifests}
        assert "coating-industry" in ids
        assert "attendance-industry" in ids
        assert len(ids) >= 2


class TestIterIndustryPackageManifestsBoundary:
    """tmp_path 隔离环境覆盖边界分支（mods_root 缺失 / 非 -industry / manifest 缺失 / 去重 / fallback）。"""

    def test_empty_when_both_mods_roots_missing(self, monkeypatch, tmp_path):
        """两个 mods_root 都不存在 → 全部 continue 分支，返回空列表。"""
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (tmp_path / "no_fhd", tmp_path / "no_xcagi"))
        assert ipv.iter_industry_package_manifests() == []

    def test_empty_when_first_missing_second_has_no_industry(self, monkeypatch, tmp_path):
        """第一个 mods_root 不存在，第二个存在但无 -industry 包 → 返回空。"""
        xcagi_mods = tmp_path / "xcagi_mods"
        xcagi_mods.mkdir()
        _make_mod(xcagi_mods, "regular-mod")  # 非 -industry 后缀
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (tmp_path / "no_fhd", xcagi_mods))
        assert ipv.iter_industry_package_manifests() == []

    def test_skips_non_industry_suffix_dirs(self, monkeypatch, tmp_path):
        """目录有 manifest.json 但不以 -industry 结尾 → 跳过。"""
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        _make_mod(mods_root, "coating-industry")
        _make_mod(mods_root, "regular-mod")
        _make_mod(mods_root, "another-mod")
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (mods_root,))
        manifests = ipv.iter_industry_package_manifests()
        ids = {m.parent.name for m in manifests}
        assert ids == {"coating-industry"}

    def test_skips_industry_dirs_without_manifest(self, monkeypatch, tmp_path):
        """目录以 -industry 结尾但无 manifest.json → 跳过。"""
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        (mods_root / "broken-industry").mkdir()  # 无 manifest.json
        _make_mod(mods_root, "good-industry")
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (mods_root,))
        manifests = ipv.iter_industry_package_manifests()
        ids = {m.parent.name for m in manifests}
        assert ids == {"good-industry"}

    def test_skips_non_directory_entries_with_industry_name(self, monkeypatch, tmp_path):
        """目录中含名为 xxx-industry 的普通文件（非目录）→ 跳过。"""
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        # 普通文件，名字像 -industry 但不是目录
        (mods_root / "fake-industry").write_text("not a dir", encoding="utf-8")
        _make_mod(mods_root, "real-industry")
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (mods_root,))
        manifests = ipv.iter_industry_package_manifests()
        ids = {m.parent.name for m in manifests}
        assert ids == {"real-industry"}

    def test_dedup_across_dual_paths_keeps_first(self, monkeypatch, tmp_path):
        """同名包在两个 mods_root 中都存在 → 仅保留编辑源（第一个）。"""
        fhd_mods = tmp_path / "fhd_mods"
        xcagi_mods = tmp_path / "xcagi_mods"
        fhd_mods.mkdir()
        xcagi_mods.mkdir()
        for root in (fhd_mods, xcagi_mods):
            _make_mod(root, "coating-industry")
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (fhd_mods, xcagi_mods))
        manifests = ipv.iter_industry_package_manifests()
        coating = [m for m in manifests if m.parent.name == "coating-industry"]
        assert len(coating) == 1, "同名包应去重，仅出现一次"
        # 编辑源优先：保留 fhd_mods 中的版本
        assert coating[0].parent.parent == fhd_mods

    def test_fallback_picks_up_package_only_in_second_path(self, monkeypatch, tmp_path):
        """仅第二个 mods_root 有的包 → fallback 补齐。"""
        fhd_mods = tmp_path / "fhd_mods"
        xcagi_mods = tmp_path / "xcagi_mods"
        fhd_mods.mkdir()
        xcagi_mods.mkdir()
        _make_mod(xcagi_mods, "attendance-industry")
        # 第一个路径放一个不同的 industry 包，验证两者都被收集
        _make_mod(fhd_mods, "coating-industry")
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (fhd_mods, xcagi_mods))
        manifests = ipv.iter_industry_package_manifests()
        ids = {m.parent.name for m in manifests}
        assert ids == {"coating-industry", "attendance-industry"}
        # attendance-industry 来自 fallback 路径
        attendance = next(m for m in manifests if m.parent.name == "attendance-industry")
        assert attendance.parent.parent == xcagi_mods

    def test_sorted_iteration_order(self, monkeypatch, tmp_path):
        """iterdir 排序后扫描，结果稳定（按目录名排序）。"""
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        # 故意倒序创建
        for name in ("z-industry", "a-industry", "m-industry"):
            _make_mod(mods_root, name)
        monkeypatch.setattr(ipv, "_MODS_ROOTS", (mods_root,))
        manifests = ipv.iter_industry_package_manifests()
        names = [m.parent.name for m in manifests]
        assert names == sorted(names)  # 升序
        assert names == ["a-industry", "m-industry", "z-industry"]


class TestValidateIndustryManifest:
    """validate_industry_manifest 边界场景补充。"""

    def test_manifest_not_found_returns_error(self, tmp_path):
        """传入不存在的 manifest 路径 → 返回错误信息。"""
        errors = ipv.validate_industry_manifest(tmp_path / "nonexistent.json")
        assert len(errors) == 1
        assert "manifest not found" in errors[0]

    def test_invalid_json_returns_error(self, tmp_path):
        """manifest.json 内容非法 JSON → 返回错误。"""
        manifest = tmp_path / "broken-industry" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{not valid json", encoding="utf-8")
        errors = ipv.validate_industry_manifest(manifest)
        assert len(errors) == 1
        assert "invalid JSON" in errors[0]

    def test_non_dict_root_returns_error(self, tmp_path):
        """manifest.json 根为 list 而非 dict → 返回错误。"""
        manifest = tmp_path / "list-industry" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('["a", "b"]', encoding="utf-8")
        errors = ipv.validate_industry_manifest(manifest)
        assert errors == ["manifest root must be an object"]
