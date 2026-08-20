# 成都修茈科技有限公司/MODstore_deploy/tests/test_build_employee_pack.py
"""build_employee_pack 单元测试。"""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from modstore_server.build_employee_pack import (
    PackSchemaError,
    _get_commit_diff_files,
    build_pack_from_commit,
    build_xcemp_archive,
    register_in_packages_json,
    validate_pack_schema,
)


def _make_pack_files(tmp_path: Path) -> Path:
    pack_dir = tmp_path / "intent-clerk@1.0.0"
    pack_dir.mkdir()
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "intent-clerk",
                "version": "1.0.0",
                "department": "engineering",
                "prompt_template": "You are...",
                "skills": ["intent-benchmark"],
                "tools": ["read_file"],
                "acceptance_criteria": ["recall >= 0.7"],
            }
        ),
        encoding="utf-8",
    )
    (pack_dir / "prompt.txt").write_text("You are an intent clerk...", encoding="utf-8")
    return pack_dir


def test_validate_pack_schema_passes_valid_pack(tmp_path):
    pack_dir = _make_pack_files(tmp_path)
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    validate_pack_schema(manifest)  # 不抛异常即通过


def test_commit_diff_preserves_unicode_paths(tmp_path):
    changed = (
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/files/"
        "pilot-low-risk-clerk@1.0.0/manifest.json"
    )
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=(changed + "\0").encode("utf-8"), stderr=b""
    )
    with patch("modstore_server.build_employee_pack.subprocess.run", return_value=completed) as run:
        assert _get_commit_diff_files(commit_sha="abc123", repo_root=tmp_path) == [changed]
    assert "-z" in run.call_args.args[0]


def test_validate_pack_schema_rejects_missing_field(tmp_path):
    bad_manifest = {"name": "x"}  # 缺 version / department / prompt_template 等
    with pytest.raises(PackSchemaError, match="missing"):
        validate_pack_schema(bad_manifest)


def test_validate_pack_schema_rejects_invalid_department():
    bad_manifest = {
        "name": "x",
        "version": "1.0.0",
        "department": "marketing",
        "prompt_template": "x",
        "skills": [],
        "tools": [],
        "acceptance_criteria": [],
    }
    with pytest.raises(PackSchemaError, match="department"):
        validate_pack_schema(bad_manifest)


def test_register_in_packages_json_appends_new_pack(tmp_path, monkeypatch):
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
    files_root = tmp_path / "catalog_data" / "files"
    files_root.mkdir(parents=True)
    pack_dir = _make_pack_files(tmp_path)
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    manifest = {
        "name": "intent-clerk",
        "version": "1.0.0",
        "department": "engineering",
        "prompt_template": "x",
        "skills": [],
        "tools": [],
        "acceptance_criteria": [],
    }
    pack_id = register_in_packages_json(manifest, files_dir=pack_dir)
    assert pack_id == "intent-clerk@1.0.0"

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(data["packages"]) == 1
    assert data["packages"][0]["id"] == "intent-clerk"
    assert len(data["packages"][0]["sha256"]) == 64
    assert (files_root / data["packages"][0]["stored_filename"]).is_file()


def test_register_in_packages_json_binds_valid_source_commit(tmp_path, monkeypatch):
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
    files_root = tmp_path / "catalog_data" / "files"
    files_root.mkdir(parents=True)
    pack_dir = _make_pack_files(tmp_path)
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))

    register_in_packages_json(
        manifest,
        files_dir=pack_dir,
        source_commit_sha="a" * 40,
    )

    row = json.loads(catalog_path.read_text(encoding="utf-8"))["packages"][0]
    assert row["source_commit_sha"] == "a" * 40


def test_register_in_packages_json_replaces_legacy_duplicate(tmp_path, monkeypatch):
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "packages": [{"id": "intent-clerk@1.0.0", "name": "old"}],
            }
        ),
        encoding="utf-8",
    )
    files_root = tmp_path / "catalog_data" / "files"
    files_root.mkdir(parents=True)
    pack_dir = _make_pack_files(tmp_path)
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    manifest = {
        "name": "intent-clerk",
        "version": "1.0.0",
        "department": "engineering",
        "prompt_template": "x",
        "skills": [],
        "tools": [],
        "acceptance_criteria": [],
    }
    assert register_in_packages_json(manifest, files_dir=pack_dir) == "intent-clerk@1.0.0"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert [(row["id"], row["version"]) for row in data["packages"]] == [("intent-clerk", "1.0.0")]


def test_build_xcemp_archive_is_deterministic_and_installable(tmp_path, monkeypatch):
    files_root = tmp_path / "catalog_data" / "files"
    files_root.mkdir(parents=True)
    pack_dir = _make_pack_files(tmp_path)
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    archive = build_xcemp_archive(manifest, files_dir=pack_dir)
    first = archive.read_bytes()
    assert build_xcemp_archive(manifest, files_dir=pack_dir).read_bytes() == first
    with zipfile.ZipFile(archive) as bundle:
        assert "intent-clerk/manifest.json" in bundle.namelist()


def test_build_pack_from_commit_end_to_end(tmp_path, monkeypatch):
    """模拟 PR 合并：从 commit diff 提取 → 校验 → 注册 → 触发审核。"""
    # 准备 fake commit diff
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
    files_root = tmp_path / "catalog_data" / "files"
    files_root.mkdir(parents=True)
    pack_dir = _make_pack_files(files_root)
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    # 模拟 git diff --name-only 输出
    diff_files = [
        f"成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/files/intent-clerk@1.0.0/{f.name}"
        for f in pack_dir.iterdir()
    ]

    with (
        patch(
            "modstore_server.build_employee_pack._get_commit_diff_files",
            return_value=diff_files,
        ),
        patch("modstore_server.build_employee_pack._read_pack_file") as mock_read,
    ):

        def fake_read(path, repo_root):
            rel = path.split("intent-clerk@1.0.0/", 1)[1]
            return (pack_dir / rel).read_text(encoding="utf-8")

        mock_read.side_effect = fake_read

        with patch(
            "modstore_server.build_employee_pack.evaluate_employee_pack",
            return_value=("low", "auto-approved"),
        ):
            result = build_pack_from_commit(commit_sha="abc123", repo_root=tmp_path)

    assert result["pack_id"] == "intent-clerk@1.0.0"
    assert result["approved"] is True
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(data["packages"]) == 1


def test_build_pack_from_commit_no_employee_files(tmp_path, monkeypatch):
    """commit diff 不含 employee_pack 文件时跳过。"""
    with patch(
        "modstore_server.build_employee_pack._get_commit_diff_files",
        return_value=[
            "FHD/app/foo.py",
            "README.md",
        ],
    ):
        result = build_pack_from_commit(commit_sha="abc123", repo_root=tmp_path)
    assert result["skipped"] is True
