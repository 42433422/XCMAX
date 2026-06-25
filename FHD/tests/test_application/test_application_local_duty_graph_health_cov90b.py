"""真实行为测试（第二波）：覆盖 local_duty_graph_health 中未测分支。

目标未覆盖逻辑：
- _local_registered_employee_pack_ids 的委托（line 16）
- _staffing_areas_from_doc 的 departments 回退（24-25）与 subzones 递归（34-36）
- read_local_employee_manifest 的全部分支（98-130）
- build_local_employee_status 的全部分支（135-145）

所有外部依赖（mod_manager / metrics / 文件系统）均 mock；离线、确定。
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from app.application import local_duty_graph_health as mod
from app.application.local_duty_graph_health import (
    _local_registered_employee_pack_ids,
    _staffing_areas_from_doc,
    build_local_employee_status,
    read_local_employee_manifest,
)

MODULE = "app.application.local_duty_graph_health"


# --------------------------------------------------------------------------- #
# _local_registered_employee_pack_ids（line 16）
# --------------------------------------------------------------------------- #
def test_local_registered_employee_pack_ids_delegates() -> None:
    """委托给 _installed_employee_pack_ids，原样返回其 set。"""
    with patch(
        f"{MODULE}._installed_employee_pack_ids",
        return_value={"emp-a", "emp-b"},
    ) as installed:
        out = _local_registered_employee_pack_ids()
    assert out == {"emp-a", "emp-b"}
    installed.assert_called_once_with()


# --------------------------------------------------------------------------- #
# _staffing_areas_from_doc
# --------------------------------------------------------------------------- #
def test_staffing_areas_from_areas_with_missing() -> None:
    doc = {"areas": {"seo": {"label": "SEO 区", "ids": ["a", "b", "c"]}}}
    out = _staffing_areas_from_doc(doc, registered={"a"})
    assert len(out) == 1
    block = out[0]
    assert block["key"] == "seo"
    assert block["label"] == "SEO 区"
    # missing = ids - registered, 排序
    assert block["missing"] == ["b", "c"]


def test_staffing_areas_falls_back_to_departments() -> None:
    """areas 缺失/非 dict 时回退到 departments（line 24-25）。"""
    doc = {
        "areas": "not-a-dict",
        "departments": {"ops": {"label": "运维部", "ids": ["x", "y"]}},
    }
    out = _staffing_areas_from_doc(doc, registered={"x"})
    assert len(out) == 1
    assert out[0]["key"] == "ops"
    assert out[0]["label"] == "运维部"
    assert out[0]["missing"] == ["y"]


def test_staffing_areas_departments_non_dict_yields_empty() -> None:
    """areas 空且 departments 非 dict → areas_doc={}，输出空列表。"""
    doc = {"departments": ["not", "a", "dict"]}
    out = _staffing_areas_from_doc(doc, registered=set())
    assert out == []


def test_staffing_areas_recurses_into_subzones() -> None:
    """subzones 递归展开为带斜杠 key 的区段（line 34-36）。"""
    doc = {
        "areas": {
            "growth": {
                "label": "增长",
                "ids": ["lead"],
                "subzones": {
                    "paid": {"label": "付费", "ids": ["ads-a", "ads-b"]},
                    "broken": "ignored-non-dict",
                },
            }
        }
    }
    out = _staffing_areas_from_doc(doc, registered={"ads-a"})
    by_key = {b["key"]: b for b in out}
    # 父区段
    assert by_key["growth"]["missing"] == ["lead"]
    # 子区段 key 形如 父/子
    assert "growth/paid" in by_key
    assert by_key["growth/paid"]["label"] == "付费"
    assert by_key["growth/paid"]["missing"] == ["ads-b"]
    # 非 dict 的 subzone 被忽略，不产生 growth/broken
    assert "growth/broken" not in by_key


def test_staffing_areas_block_without_ids_is_skipped() -> None:
    """无 ids 的 block 不追加（只递归）。"""
    doc = {"areas": {"empty": {"label": "空", "subzones": {}}}}
    out = _staffing_areas_from_doc(doc, registered=set())
    assert out == []


def test_staffing_areas_label_defaults_to_key() -> None:
    """label 缺失时回退为 key。"""
    doc = {"areas": {"zzz": {"ids": ["only"]}}}
    out = _staffing_areas_from_doc(doc, registered=set())
    assert out[0]["label"] == "zzz"


def test_staffing_areas_ignores_non_dict_top_blocks() -> None:
    doc = {"areas": {"good": {"ids": ["g"]}, "bad": "string-block"}}
    out = _staffing_areas_from_doc(doc, registered=set())
    keys = {b["key"] for b in out}
    assert keys == {"good"}


# --------------------------------------------------------------------------- #
# read_local_employee_manifest
# --------------------------------------------------------------------------- #
def test_read_manifest_empty_id_returns_none() -> None:
    """空/空白 employee_id → None（line 99-100），不触碰 mod_manager。"""
    assert read_local_employee_manifest("") is None
    assert read_local_employee_manifest("   ") is None
    assert read_local_employee_manifest(None) is None  # type: ignore[arg-type]


def test_read_manifest_found_returns_merged_dict(tmp_path) -> None:
    """all_mods_roots 正常 + manifest 存在且为 dict → 合并返回。"""
    mods_root = tmp_path / "mods"
    emp_dir = mods_root / "_employees" / "seo-curator"
    emp_dir.mkdir(parents=True)
    manifest_payload = {"name": "SEO Curator", "version": "1.2.3"}
    (emp_dir / "manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")

    mgr = MagicMock()
    mgr.all_mods_roots.return_value = [str(mods_root)]
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mgr,
    ):
        out = read_local_employee_manifest("seo-curator")

    assert out is not None
    assert out["employee_id"] == "seo-curator"
    assert out["manifest"] == manifest_payload
    # **data 展开
    assert out["name"] == "SEO Curator"
    assert out["version"] == "1.2.3"


def test_read_manifest_all_roots_raises_uses_primary_fallback(tmp_path) -> None:
    """all_mods_roots 抛 RECOVERABLE → 回退到 mgr.mods_root（line 109-114）。"""
    mods_root = tmp_path / "primary"
    emp_dir = mods_root / "_employees" / "emp-x"
    emp_dir.mkdir(parents=True)
    (emp_dir / "manifest.json").write_text(json.dumps({"ok": 1}), encoding="utf-8")

    mgr = MagicMock()
    mgr.all_mods_roots.side_effect = OSError("disk gone")
    mgr.mods_root = str(mods_root)
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mgr,
    ):
        out = read_local_employee_manifest("emp-x")

    assert out is not None
    assert out["employee_id"] == "emp-x"
    assert out["ok"] == 1


def test_read_manifest_no_roots_no_primary_returns_none() -> None:
    """all_mods_roots 返回空 + 无 mods_root → 没有可遍历 root → None。"""
    mgr = MagicMock()
    mgr.all_mods_roots.return_value = []
    mgr.mods_root = None
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mgr,
    ):
        out = read_local_employee_manifest("emp-y")
    assert out is None


def test_read_manifest_skips_falsy_root_then_missing_file(tmp_path) -> None:
    """root 列表含空串（被 continue 跳过）+ 真实 root 无 manifest 文件 → None。"""
    real_root = tmp_path / "real"
    real_root.mkdir()
    mgr = MagicMock()
    mgr.all_mods_roots.return_value = ["", str(real_root)]
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mgr,
    ):
        out = read_local_employee_manifest("nope")
    assert out is None


def test_read_manifest_non_dict_payload_returns_none(tmp_path) -> None:
    """manifest 文件内容是 JSON 数组（非 dict）→ 不返回（line 122 守卫）→ None。"""
    mods_root = tmp_path / "mods"
    emp_dir = mods_root / "_employees" / "emp-list"
    emp_dir.mkdir(parents=True)
    (emp_dir / "manifest.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    mgr = MagicMock()
    mgr.all_mods_roots.return_value = [str(mods_root)]
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mgr,
    ):
        out = read_local_employee_manifest("emp-list")
    assert out is None


def test_read_manifest_get_mod_manager_import_failure_returns_none() -> None:
    """get_mod_manager 抛 RECOVERABLE（如 ImportError）→ 外层 except → None（128-130）。"""
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        side_effect=ImportError("no mod manager"),
    ):
        out = read_local_employee_manifest("emp-boom")
    assert out is None


def test_read_manifest_corrupt_json_returns_none(tmp_path) -> None:
    """manifest 文件是损坏 JSON → json.load 抛 JSONDecodeError（RECOVERABLE）→ None。"""
    mods_root = tmp_path / "mods"
    emp_dir = mods_root / "_employees" / "emp-bad"
    emp_dir.mkdir(parents=True)
    (emp_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    mgr = MagicMock()
    mgr.all_mods_roots.return_value = [str(mods_root)]
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mgr,
    ):
        out = read_local_employee_manifest("emp-bad")
    assert out is None


# --------------------------------------------------------------------------- #
# build_local_employee_status（line 135-145）
# --------------------------------------------------------------------------- #
def test_build_status_deployed_with_metrics() -> None:
    """manifest 存在 → deployed True；有 runs → success_rate 正确计算。"""
    metrics = {
        "by_employee": {
            "emp-1": {
                "runs_total": 4,
                "runs_success": 3,
                "runs_failed": 1,
                "runs_blocked": 0,
                "last_execution": "2026-06-24T08:00:00+08:00",
            }
        }
    }
    with (
        patch(
            f"{MODULE}.read_local_employee_manifest",
            return_value={"employee_id": "emp-1", "manifest": {}},
        ),
        patch(
            "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
            return_value=metrics,
        ),
    ):
        out = build_local_employee_status("  emp-1  ")

    assert out["employee_id"] == "emp-1"  # 已 strip
    assert out["deployed"] is True
    assert out["last_execution"] == "2026-06-24T08:00:00+08:00"
    stats = out["execution_stats"]
    assert stats["total_executions"] == 4
    assert stats["success_count"] == 3
    assert stats["failed_count"] == 1
    assert stats["blocked_count"] == 0
    assert stats["success_rate"] == 0.75


def test_build_status_not_deployed_zero_runs() -> None:
    """manifest None → deployed False；无 runs → success_rate 0（total 假分支）。"""
    with (
        patch(f"{MODULE}.read_local_employee_manifest", return_value=None),
        patch(
            "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
            return_value={"by_employee": {}},
        ),
    ):
        out = build_local_employee_status("ghost")

    assert out["employee_id"] == "ghost"
    assert out["deployed"] is False
    assert out["last_execution"] is None
    stats = out["execution_stats"]
    assert stats["total_executions"] == 0
    assert stats["success_count"] == 0
    assert stats["failed_count"] == 0
    assert stats["blocked_count"] == 0
    assert stats["success_rate"] == 0


def test_build_status_metrics_missing_by_employee_key() -> None:
    """metrics 没有 by_employee 键 → row 为空 dict，各计数回退 0。"""
    with (
        patch(
            f"{MODULE}.read_local_employee_manifest",
            return_value={"employee_id": "emp-2"},
        ),
        patch(
            "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
            return_value={},
        ),
    ):
        out = build_local_employee_status("emp-2")

    assert out["deployed"] is True
    assert out["execution_stats"]["total_executions"] == 0
    assert out["execution_stats"]["success_rate"] == 0


def test_module_all_exports() -> None:
    """__all__ 暴露三个公开入口。"""
    assert set(mod.__all__) == {
        "build_local_duty_graph_health",
        "build_local_employee_status",
        "read_local_employee_manifest",
    }


def test_read_manifest_path_construction(tmp_path) -> None:
    """验证 manifest 路径由 abspath(mods_root)/_employees/<pid>/manifest.json 构成。"""
    mods_root = tmp_path / "mr"
    emp_dir = mods_root / "_employees" / "p-id"
    emp_dir.mkdir(parents=True)
    (emp_dir / "manifest.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")

    expected = os.path.join(os.path.abspath(str(mods_root)), "_employees", "p-id", "manifest.json")
    assert os.path.isfile(expected)

    mgr = MagicMock()
    mgr.all_mods_roots.return_value = [str(mods_root)]
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mgr,
    ):
        out = read_local_employee_manifest("p-id")
    assert out is not None
    assert out["k"] == "v"
