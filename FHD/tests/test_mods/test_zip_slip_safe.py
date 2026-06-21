"""VULN-2 文档化（已被缓解）：MOD 解压的 Zip-Slip 防回归证据。

``ModPackage.extract_package`` 使用 ``zipfile.ZipFile.extractall``。自 CPython 起，
``extractall`` 会对成员名做 sanitize：

* 绝对路径成员（如 ``/evil.txt``）会被剥离前导分隔符，落回 target_dir 之内；
* 含 ``..`` 的成员（如 ``../evil.txt``）会被规整，``..`` 段被丢弃，不会逃逸到
  target_dir 之外。

本测试构造一个含恶意成员（``../evil.txt`` 与绝对路径成员）的 zip，断言解压后
**target_dir 之外不会产生任何文件**，以此作为防回归证据，并记录该缓解依赖于
CPython extractall 的内置 sanitize 行为。
"""

from __future__ import annotations

import json
import os
import zipfile

import pytest

from app.infrastructure.mods.package import ModPackage, ModPackageError


def _snapshot_files(root: str) -> set[str]:
    out: set[str] = set()
    for d, _, files in os.walk(root):
        for f in files:
            out.add(os.path.realpath(os.path.join(d, f)))
    return out


def test_zip_slip_relative_and_absolute_members_stay_inside(tmp_path):
    """含 ../evil.txt 与绝对路径成员的恶意包，解压后不在 target_dir 之外产生文件。"""
    # 包含一个独立的"外部"哨兵目录，解压结束后它必须保持为空。
    outside_dir = tmp_path / "outside_zone"
    outside_dir.mkdir()
    before_outside = _snapshot_files(str(outside_dir))

    package_path = str(tmp_path / "evil.xcmod")
    manifest = {"id": "evil-mod", "version": "1.0.0"}
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        # 恶意成员 1：相对路径遍历。
        zf.writestr("../evil_relative.txt", "pwned-relative")
        # 恶意成员 2：更深层遍历，试图命中 outside_zone。
        zf.writestr("../../outside_zone/evil_deep.txt", "pwned-deep")
        # 恶意成员 3：绝对路径成员。
        zf.writestr("/evil_absolute.txt", "pwned-absolute")

    target_dir = str(tmp_path / "target")
    os.makedirs(target_dir, exist_ok=True)

    # extract_package 内部调用 extractall。CPython 会 sanitize 上述成员。
    ModPackage.extract_package(package_path, target_dir, verify_signature=False)

    target_real = os.path.realpath(target_dir)

    # 1) 解压产生的所有文件都必须落在 target_dir 之内。
    produced = _snapshot_files(target_dir)
    for path in produced:
        assert path.startswith(target_real + os.sep), f"文件逃逸到 target_dir 之外: {path}"

    # 2) target_dir 的父目录中不得新增遍历产物（除 target_dir 自身内容外）。
    parent = os.path.realpath(str(tmp_path))
    for name in os.listdir(parent):
        full = os.path.realpath(os.path.join(parent, name))
        # 允许 target_dir 与原有的 outside_zone / 包文件本身。
        if full == target_real:
            continue
        # 不应出现 evil_*.txt 之类的逃逸文件直接落在 tmp_path 下。
        assert not name.startswith("evil_"), f"遍历产物逃逸到父目录: {name}"

    # 3) 外部哨兵目录在解压后保持不变（深层遍历未命中）。
    after_outside = _snapshot_files(str(outside_dir))
    assert after_outside == before_outside, f"外部目录被写入了文件: {after_outside - before_outside}"


def test_absolute_member_lands_inside_target(tmp_path):
    """绝对路径成员被 sanitize 后落回 target_dir，证明前导分隔符被剥离。"""
    package_path = str(tmp_path / "abs.xcmod")
    manifest = {"id": "abs-mod", "version": "1.0.0"}
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("/tmp_like_evil.txt", "data")

    target_dir = str(tmp_path / "target_abs")
    os.makedirs(target_dir, exist_ok=True)
    ModPackage.extract_package(package_path, target_dir, verify_signature=False)

    target_real = os.path.realpath(target_dir)
    produced = _snapshot_files(target_dir)
    # 应能在 target_dir 内找到被 sanitize 落地的文件。
    assert any(p.endswith("tmp_like_evil.txt") for p in produced)
    for p in produced:
        assert p.startswith(target_real + os.sep)


def test_missing_manifest_after_extract_raises(tmp_path):
    """若恶意包没有合法 manifest（遍历成员被剥离后顶层无 manifest），应报错而非静默成功。"""
    package_path = str(tmp_path / "no_manifest.xcmod")
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../escaped_manifest.json", json.dumps({"id": "x", "version": "1"}))

    target_dir = str(tmp_path / "target_nm")
    os.makedirs(target_dir, exist_ok=True)
    with pytest.raises(ModPackageError):
        ModPackage.extract_package(package_path, target_dir, verify_signature=False)
