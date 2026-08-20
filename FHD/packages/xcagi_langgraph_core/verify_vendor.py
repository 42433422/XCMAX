#!/usr/bin/env python3
"""XCAGI vendored langgraph 核心包 来源与许可证锁定验证脚本 (LG-W0-02).

锁定的是上游 langgraph 仓库远端 tag `1.2.10`（无 v 前缀）@ commit
`41341457342327166d72fc11952ab28fb61ec0bf`（见同目录 PROVENANCE.json）。

职责:
  1. 校验本目录下所有 vendored 文件 (langgraph 包 + LICENSE) 的 SHA-256 与 MANIFEST.sha256 一致。
  2. 校验 LICENSE 为 MIT (含关键字检查)。
  3. 在线模式：在临时目录 (tempfile.TemporaryDirectory) 中从远端 clone 精确 tag
     `1.2.10`（无 v 前缀），把 tag 解析为 commit 并断言等于锁定 SHA `413414...`，
     再对 `libs/langgraph/langgraph` + LICENSE 做字节级比对（原样吸收），不使用任何本地 /tmp 检出。

用法:
  python verify_vendor.py            # 本地清单 + LICENSE + 在线上游比对
  python verify_vendor.py --offline  # 仅本地清单 + LICENSE, 跳过在线比对
  python verify_vendor.py --gen      # 重新生成 MANIFEST.sha256

退出码: 0=全部通过; 1=校验失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.sha256"
PROVENANCE = HERE / "PROVENANCE.json"

# MANIFEST 需要覆盖的顶层条目 (langgraph/ 包目录下所有文件 + LICENSE)
TOPNODE = ["langgraph", "LICENSE"]

# 上游远端与锁定 tag（无 v 前缀）
UPSTREAM_REPO = "https://github.com/langchain-ai/langgraph"
EXPECTED_TAG = "1.2.10"
EXPECTED_SHA = "41341457342327166d72fc11952ab28fb61ec0bf"

# 本地产物目录/文件：不入 MANIFEST，也不参与上游比对
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".venv", "build", "dist"}
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


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )


def _clone_tag(repo: Path) -> tuple[bool, str]:
    """在临时目录浅克隆远端精确 tag (无 v 前缀)。返回 (成功, commit sha 或错误信息)。"""
    proc = _git(
        [
            "clone",
            "--depth",
            "1",
            "--branch",
            EXPECTED_TAG,
            "--single-branch",
            UPSTREAM_REPO,
            str(repo),
        ]
    )
    if proc.returncode != 0:
        return False, f"git clone tag {EXPECTED_TAG} 失败: {proc.stderr.strip()}"
    rev = _git(["rev-parse", "HEAD"], cwd=repo)
    if rev.returncode != 0:
        return False, f"git rev-parse HEAD 失败: {rev.stderr.strip()}"
    return True, rev.stdout.strip()


def verify_upstream(prov: dict) -> bool:
    """在线校验：临时目录 clone 远端 tag 1.2.10 -> 断言 SHA -> 字节级比对源码。"""
    tag = prov.get("upstream_tag", "")
    sha = prov.get("upstream_commit_sha", "")
    src = prov.get("source_path", "")

    if tag != EXPECTED_TAG:
        print(
            f"[FAIL] PROVENANCE upstream_tag 应为 {EXPECTED_TAG}（无 v 前缀），当前 {tag!r}"
        )
        return False
    if sha != EXPECTED_SHA:
        print(
            f"[FAIL] PROVENANCE upstream_commit_sha 应为 {EXPECTED_SHA}，当前 {sha!r}"
        )
        return False

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        repo = base / "repo"
        ok, resolved = _clone_tag(repo)
        if not ok:
            print(f"[FAIL] {resolved}")
            return False
        if resolved != sha:
            print(
                f"[FAIL] 远端 tag {EXPECTED_TAG} 解析为 {resolved[:12]}，与锁定 SHA {sha[:12]} 不一致"
            )
            return False
        print(f"[OK] 远端 tag {EXPECTED_TAG} -> commit {resolved}")

        upstream_root = repo / src  # 内含 langgraph/ 与 LICENSE
        if not (upstream_root / "langgraph").is_dir():
            print(f"[FAIL] 远端 {src}/langgraph 缺失")
            return False

        mismatches: list[str] = []
        for rel, digest in collect_files().items():
            upstream = (
                upstream_root / "LICENSE" if rel == "LICENSE" else upstream_root / rel
            )
            if not upstream.is_file():
                mismatches.append(f"{rel} (上游缺失)")
                continue
            if sha256_of(upstream) != digest:
                mismatches.append(rel)

    ok = not mismatches
    if ok:
        print(
            f"[OK] 与远端 tag {EXPECTED_TAG} ({sha[:12]}) 的 {src}/langgraph + LICENSE 字节级一致"
        )
    else:
        for m in mismatches:
            print(f"[FAIL] 与上游不一致: {m}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", action="store_true", help="重新生成 MANIFEST.sha256")
    parser.add_argument(
        "--offline", action="store_true", help="跳过上游吸收源字节级比对"
    )
    args = parser.parse_args()

    if args.gen:
        write_manifest()
        return 0

    prov = load_provenance()
    results = [verify_license(), verify_manifest()]
    if not args.offline:
        results.append(verify_upstream(prov))
    else:
        print("[SKIP] offline 模式, 跳过上游锁定 commit 比对")

    passed = all(results)
    print("\n" + ("ALL PASS" if passed else "VERIFY FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
