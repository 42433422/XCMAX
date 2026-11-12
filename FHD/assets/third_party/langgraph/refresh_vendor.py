#!/usr/bin/env python3
"""langgraph vendor 源码刷新脚本 (W0-01).

从 PROVENANCE.json 锁定的上游 tag/SHA 拉取核心包源码与 LICENSE 落盘到
FHD/third_party/langgraph/。全部用 Python 原生实现:

  - 克隆与校验在 tempfile.TemporaryDirectory 中完成, 结束自动清理, 不在仓库残留。
  - 源码落盘用 pathlib + shutil.copytree(..., dirs_exist_ok=True) 幂等合并,
    不使用 shell 的 rm -rf / cp -R。
  - 先校验克隆 HEAD == 锁定 SHA, 不符即失败退出。

用法:
  python refresh_vendor.py            # 刷新源码并重新生成 MANIFEST.sha256
  python refresh_vendor.py --no-gen   # 仅刷新源码, 不重新生成 MANIFEST

退出码: 0=成功; 1=失败。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVENANCE = HERE / "PROVENANCE.json"
PKG_DEST = HERE / "langgraph"
LICENSE_DEST = HERE / "LICENSE"
UPSTREAM_PKG_REL = Path("libs/langgraph/langgraph")  # 上游核心包路径


def load_provenance() -> dict:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def refresh(prov: dict) -> bool:
    repo = prov["upstream_repo"]
    tag = prov["locked_tag"]
    sha = prov["locked_sha"]

    with tempfile.TemporaryDirectory(prefix="lg-refresh-") as tmp:
        src = Path(tmp) / "src"
        print(f"[..] 浅克隆 {repo} @ {tag} (TemporaryDirectory 自动清理)")
        if subprocess.run(["git", "clone", "--depth", "1", "--branch", tag, repo, str(src)]).returncode != 0:
            print("[FAIL] git clone 失败")
            return False

        head = subprocess.run(
            ["git", "-C", str(src), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        if head != sha:
            print(f"[FAIL] tag {tag} HEAD={head} != 锁定 SHA {sha}")
            return False
        print(f"[OK] tag {tag} -> {head} == 锁定 SHA")

        pkg_src = src / UPSTREAM_PKG_REL
        if not pkg_src.is_dir():
            print(f"[FAIL] 上游路径不存在: {UPSTREAM_PKG_REL}")
            return False

        # 幂等合并: 覆盖同名文件; 由 MANIFEST.sha256 校验兜底 dest 中多余文件
        shutil.copytree(pkg_src, PKG_DEST, dirs_exist_ok=True)
        shutil.copy2(src / "LICENSE", LICENSE_DEST)
        print(f"[OK] vendor 源码已合并: {PKG_DEST.relative_to(HERE)}/ + {LICENSE_DEST.name}")
        return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gen", action="store_true", help="刷新源码后不重新生成 MANIFEST")
    args = parser.parse_args()

    prov = load_provenance()
    if not refresh(prov):
        return 1
    if not args.no_gen:
        if subprocess.run([sys.executable, str(HERE / "verify_vendor.py"), "--gen"]).returncode != 0:
            return 1
    print("REFRESH DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
