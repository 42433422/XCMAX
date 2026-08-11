#!/usr/bin/env python3
"""XCAGI vendored langgraph-checkpoint 来源与许可证锁定验证脚本 (LG-W0-03).

本脚本为「git tag -> SHA」来源校验：完全自包含、可移植——不依赖任何固定的本地 git 检出目录。
它会在临时目录内自行克隆/拉取上游仓库，校验远端 tag `1.2.10`（注意：无 v 前缀）解析出的 commit
SHA 与 PROVENANCE.json 锁定的 `41341457342327166d72fc11952ab28fb61ec0bf` 一致，随后取该 commit
的 `libs/checkpoint/langgraph` + `LICENSE` 与本副本字节级比对。

职责:
  1. 校验本目录下所有 vendored 文件 (langgraph/ 包 + LICENSE) 的 SHA-256 与 MANIFEST.sha256 一致。
  2. 校验 LICENSE 为 MIT (含关键字检查)。
  3. 在线校验: 拉取上游远端 tag，校验 commit SHA，比对 <source_path>/langgraph + LICENSE 字节级一致。

用法:
  python verify_vendor.py            # 本地清单 + LICENSE + 在线上游 tag 比对
  python verify_vendor.py --offline  # 仅本地清单 + LICENSE, 跳过在线比对
  python verify_vendor.py --gen      # 重新生成 MANIFEST.sha256

退出码: 0=全部通过; 1=校验失败。
"""
from __future__ import annotations

import argparse
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
    changed = [rel for rel in actual if rel in expected and actual[rel] != expected[rel]]

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
    return subprocess.run(["git", "-C", str(cwd), *args], check=False,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _fetch_tagged_source(prov: dict, base: Path) -> tuple[bool, str]:
    """在临时目录 base 内自包含地拉取远端 tag，校验 SHA，并导出 <src>/langgraph + LICENSE。

    返回 (成功, 错误信息)。成功时 base 下生成 <src>/langgraph 与 <src>/LICENSE。
    """
    tag = prov["upstream_tag"]          # e.g. "1.2.10" (无 v 前缀)
    sha = prov["upstream_commit_sha"]
    src = prov["source_path"]           # e.g. "libs/checkpoint"
    repo = base / "upstream"
    repo.mkdir()

    if _git(["init", "-q"], repo).returncode != 0:
        return False, "git init 失败"
    if _git(["remote", "add", "origin", REMOTE], repo).returncode != 0:
        return False, "git remote add 失败"

    fetch = _git(["fetch", "--depth", "1", "origin", "tag", tag], repo)
    if fetch.returncode != 0:
        return False, f"git fetch origin tag {tag} 失败: {fetch.stderr.decode().strip()[:200]}"

    resolved = _git(["rev-parse", f"{tag}^{{commit}}"], repo).stdout.decode().strip()
    if resolved != sha:
        return False, f"远端 tag {tag} 解析为 {resolved[:12]}, 期望 {sha[:12]}"

    upstream_paths = [f"{src}/langgraph", f"{src}/LICENSE"]
    archive = _git(["archive", "--format=tar", sha, *upstream_paths], repo)
    if archive.returncode != 0:
        return False, f"git archive {sha[:12]} 失败: {archive.stderr.decode().strip()[:200]}"

    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
        tar.extractall(base, **kwargs)

    if not (base / src / "langgraph").is_dir():
        return False, f"锁定 commit 缺少 {src}/langgraph"
    return True, ""


def verify_upstream(prov: dict) -> bool:
    """校验 vendored 副本与上游远端 tag 锁定 commit 的 <src>/langgraph + LICENSE 字节级一致。"""
    src = prov["source_path"]
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        ok, err = _fetch_tagged_source(prov, base)
        if not ok:
            print(f"[FAIL] 在线拉取上游失败: {err}")
            return False

        upstream_base = base / src
        mismatches: list[str] = []
        for rel, digest in collect_files().items():
            if rel == "LICENSE":
                upstream = upstream_base / "LICENSE"
            else:
                upstream = upstream_base / rel
            if not upstream.is_file():
                mismatches.append(f"{rel} (上游缺失)")
                continue
            if sha256_of(upstream) != digest:
                mismatches.append(rel)

    ok = not mismatches
    if ok:
        print(f"[OK] 与远端 tag {prov['upstream_tag']} ({prov['upstream_commit_sha'][:12]}) 的 "
              f"{src}/langgraph 字节级一致")
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
