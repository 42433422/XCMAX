#!/usr/bin/env python3
"""XCAGI vendored langgraph-checkpoint 来源与许可证锁定验证脚本 (LG-W0-03).

本脚本为「git tag -> SHA」来源校验：完全自包含、可移植——不依赖任何固定的本地 git 检出目录。
它会在临时目录内自行克隆/拉取上游仓库，校验远端 tag `1.2.10`（注意：无 v 前缀）解析出的 commit
SHA 与 PROVENANCE.json 锁定的 `41341457342327166d72fc11952ab28fb61ec0bf` 一致，随后取该 commit
的 `libs/checkpoint/langgraph` + `LICENSE` 与本副本字节级比对。

职责:
  1. 校验本目录下所有 vendored 文件 (langgraph/ 包 + LICENSE) 的 SHA-256 与 MANIFEST.sha256 一致。
  2. 校验 LICENSE 为 MIT (含关键字检查)。
    3. 在线校验: 拉取锁定上游 tag，校验 commit SHA，在其上应用有 SHA 锁定的
       XCAGI backport patch，再与当前 vendored langgraph 字节级比对。

用法:
  python verify_vendor.py            # 本地清单 + LICENSE + 在线上游 tag 比对
  python verify_vendor.py --offline  # 仅本地清单 + LICENSE, 跳过在线比对
  python verify_vendor.py --gen      # 重新生成 MANIFEST.sha256

退出码: 0=全部通过; 1=校验失败。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.sha256"
PROVENANCE = HERE / "PROVENANCE.json"

REMOTE = "https://github.com/langchain-ai/langgraph.git"

# MANIFEST 需要覆盖的顶层条目 (langgraph/ 包目录下所有文件 + LICENSE)
TOPNODE = ["langgraph", "LICENSE"]

# 本地产物目录/文件：不入 MANIFEST，也不参与上游比对
EXCLUDE_DIRS = {"__pycache__", ".venv", "build", "dist", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc"}
EXCLUDE_EGGINFO = ".egg-info"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if p.suffix in EXCLUDE_SUFFIXES:
            continue
        if EXCLUDE_EGGINFO in rel.parts:
            continue
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        out.append(p)
    return out


def collect_files() -> dict[str, str]:
    """返回 {相对路径(正斜杠): sha256}, 覆盖 TOPNODE 下的所有源文件。"""
    result: dict[str, str] = {}
    for node in TOPNODE:
        p = HERE / node
        if p.is_file():
            result[node] = sha256_of(p)
        elif p.is_dir():
            for f in _walk_files(p):
                result[f.relative_to(HERE).as_posix()] = sha256_of(f)
    return result


def write_manifest() -> None:
    files = collect_files()
    lines = sorted(f"{h}  {rel}\n" for rel, h in files.items())
    MANIFEST.write_text("".join(lines), encoding="utf-8")
    print(f"[gen] wrote {len(files)} entries -> {MANIFEST.name}")


def read_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        print(f"[FAIL] manifest 缺失: {MANIFEST.name}")
        sys.exit(1)
    out: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, rel = line.partition("  ")
        out[rel.strip()] = digest.strip()
    return out


def load_provenance() -> dict:
    if not PROVENANCE.exists():
        print(f"[FAIL] provenance 缺失: {PROVENANCE.name}")
        sys.exit(1)
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def verify_manifest() -> bool:
    expected = read_manifest()
    actual = collect_files()
    missing = [rel for rel in expected if rel not in actual]
    extra = [rel for rel in actual if rel not in expected]
    changed = [
        rel for rel in actual if rel in expected and actual[rel] != expected[rel]
    ]

    ok = True
    for rel in sorted(missing):
        print(f"[FAIL] 缺失文件: {rel}")
        ok = False
    for rel in sorted(extra):
        print(f"[FAIL] 多余文件未入清单: {rel}")
        ok = False
    for rel in sorted(changed):
        print(f"[FAIL] 哈希不符: {rel}")
        print(f"       expected {expected[rel]}")
        print(f"       actual   {actual[rel]}")
        ok = False
    if ok:
        print(f"[OK] MANIFEST.sha256 校验通过: {len(actual)} 个文件哈希一致")
    return ok


def verify_license() -> bool:
    lic = HERE / "LICENSE"
    if not lic.exists():
        print("[FAIL] LICENSE 缺失")
        return False
    text = lic.read_text(encoding="utf-8", errors="replace")
    ok = "MIT License" in text and "LangChain, Inc." in text
    print(f"[{'OK' if ok else 'FAIL'}] LICENSE 为 MIT (LangChain, Inc.)")
    return ok


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=False, capture_output=True
    )


def _fetch_tagged_source(prov: dict, base: Path) -> tuple[bool, str]:
    """在临时目录 base 内自包含地拉取远端 tag，校验 SHA，并导出 <src>/langgraph + LICENSE。

    返回 (成功, 错误信息)。成功时 base 下生成 <src>/langgraph 与 <src>/LICENSE。
    """
    tag = prov["upstream_tag"]  # e.g. "1.2.10" (无 v 前缀)
    sha = prov["upstream_commit_sha"]
    src = prov["source_path"]  # e.g. "libs/checkpoint"
    repo = base / "upstream"
    repo.mkdir()

    if _git(["init", "-q"], repo).returncode != 0:
        return False, "git init 失败"
    if _git(["remote", "add", "origin", REMOTE], repo).returncode != 0:
        return False, "git remote add 失败"

    fetch = _git(["fetch", "--depth", "1", "origin", "tag", tag], repo)
    if fetch.returncode != 0:
        return (
            False,
            f"git fetch origin tag {tag} 失败: {fetch.stderr.decode().strip()[:200]}",
        )

    resolved = _git(["rev-parse", f"{tag}^{{commit}}"], repo).stdout.decode().strip()
    if resolved != sha:
        return False, f"远端 tag {tag} 解析为 {resolved[:12]}, 期望 {sha[:12]}"

    upstream_paths = [f"{src}/langgraph", f"{src}/LICENSE"]
    archive = _git(["archive", "--format=tar", sha, *upstream_paths], repo)
    if archive.returncode != 0:
        return (
            False,
            f"git archive {sha[:12]} 失败: {archive.stderr.decode().strip()[:200]}",
        )

    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
        tar.extractall(base, **kwargs)

    if not (base / src / "langgraph").is_dir():
        return False, f"锁定 commit 缺少 {src}/langgraph"
    return True, ""


def verify_upstream(prov: dict) -> bool:
    """重建锁定上游基线 + XCAGI patch，并与当前 vendored 源码比对。"""
    src = prov["source_path"]
    patch_path = HERE / prov.get("patch_file", "")
    patch_sha = prov.get("patch_sha256")
    if not patch_path.is_file() or not patch_sha:
        print("[FAIL] provenance 缺少可复现的 patch 文件或 SHA-256")
        return False
    if sha256_of(patch_path) != patch_sha:
        print("[FAIL] vendor patch SHA-256 与 PROVENANCE.json 不符")
        return False

    try:
        patch_bytes = base64.b64decode(patch_path.read_bytes())
    except (ValueError, base64.binascii.Error) as exc:
        print(f"[FAIL] vendor patch base64 格式错误: {exc}")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        ok, err = _fetch_tagged_source(prov, base)
        if not ok:
            print(f"[FAIL] 在线拉取上游失败: {err}")
            return False

        upstream_base = base / src
        decoded_patch = base / "xcagi-backport.patch"
        decoded_patch.write_bytes(patch_bytes)
        for mode in ("--check",):
            check = subprocess.run(
                ["git", "apply", mode, str(decoded_patch)],
                cwd=upstream_base,
                check=False,
                capture_output=True,
                text=True,
            )
            if check.returncode != 0:
                print(f"[FAIL] vendor patch 无法应用到锁定基线: {check.stderr.strip()[:300]}")
                return False
        apply = subprocess.run(
            ["git", "apply", str(decoded_patch)],
            cwd=upstream_base,
            check=False,
            capture_output=True,
            text=True,
        )
        if apply.returncode != 0:
            print(f"[FAIL] 应用 vendor patch 失败: {apply.stderr.strip()[:300]}")
            return False

        mismatches: list[str] = []
        local = collect_files()
        upstream_files = {
            p.relative_to(upstream_base).as_posix(): sha256_of(p)
            for p in _walk_files(upstream_base / "langgraph")
        }
        upstream_files["LICENSE"] = sha256_of(upstream_base / "LICENSE")
        if local != upstream_files:
            mismatches.extend(
                sorted(
                    rel
                    for rel in set(local) | set(upstream_files)
                    if local.get(rel) != upstream_files.get(rel)
                )
            )

    ok = not mismatches
    if ok:
        print(
            f"[OK] 锁定上游 tag {prov['upstream_tag']} ({prov['upstream_commit_sha'][:12]}) "
            f"+ vendor patch ({patch_sha[:12]}) 可重建当前副本"
        )
    else:
        for m in mismatches:
            print(f"[FAIL] 与上游不一致: {m}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", action="store_true", help="重新生成 MANIFEST.sha256")
    parser.add_argument("--offline", action="store_true", help="跳过在线上游 tag 比对")
    args = parser.parse_args()

    if args.gen:
        write_manifest()
        return 0

    prov = load_provenance()
    results = [verify_license(), verify_manifest()]
    if not args.offline:
        results.append(verify_upstream(prov))
    else:
        print("[SKIP] offline 模式, 跳过在线上游 tag 比对")

    passed = all(results)
    print("\n" + ("ALL PASS" if passed else "VERIFY FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
