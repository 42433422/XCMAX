#!/usr/bin/env python3
"""XCAGI vendored langgraph-checkpoint-sqlite 来源与许可证锁定验证脚本 (LG-W0-04).

本脚本为「git tag -> SHA」来源校验（区别于 sdist 来源）：锁定的是上游 langgraph 仓库 tag 1.2.10
@ commit 41341457342327166d72fc11952ab28fb61ec0bf（见同目录 PROVENANCE.json）。

职责:
  1. 校验本目录下所有 vendored 文件 (langgraph/ 包 + LICENSE) 的 SHA-256 与 MANIFEST.sha256 一致。
  2. 校验 LICENSE 为 MIT (含关键字检查)。
  3. 在 TemporaryDirectory 内自远端 fetch 精确 tag 1.2.10，断言提交 SHA == 锁定值，并对
     vendored 副本与上游 libs/checkpoint-sqlite/langgraph + LICENSE 做字节级比对（原样吸收）。
     跳过 caches/__pycache__/.venv/build/dist/*.egg-info 等本地产物。

用法:
  python verify_vendor.py            # 本地清单 + LICENSE + 上游锁定 tag 比对（在线, 自 fetch）
  python verify_vendor.py --offline  # 仅本地清单 + LICENSE, 跳过上游比对
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

# 上游远端与精确 tag / 锁定 SHA（与 PROVENANCE.json 一致）
UPSTREAM_REPO = "https://github.com/langchain-ai/langgraph.git"
UPSTREAM_TAG = "1.2.10"
UPSTREAM_SHA = "41341457342327166d72fc11952ab28fb61ec0bf"
# 锁定 commit 对应上游 libs/checkpoint-sqlite 下的相对路径
UPSTREAM_PATHS = ["libs/checkpoint-sqlite/langgraph", "libs/checkpoint-sqlite/LICENSE"]

# 本地产物目录/文件：不入 MANIFEST，也不参与上游比对
EXCLUDE_DIRS = {"__pycache__", ".venv", "build", "dist", "caches"}
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
        if p.suffix in EXCLUDE_SUFFIXES:
            continue
        if EXCLUDE_EGGINFO in p.relative_to(root).parts:
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts):
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


def fetch_pinned(dst: Path) -> tuple[bool, str]:
    """在给定目录内自远端浅克隆精确 tag，断言提交 SHA 后返回上游源码根。

    返回 (成功, 错误信息)。成功时 dst 即 tag 1.2.10 的完整工作树。
    """
    proc = subprocess.run(
        [
            "git", "clone", "--quiet", "--depth", "1", "--branch", UPSTREAM_TAG,
            UPSTREAM_REPO, str(dst),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return False, f"git clone {UPSTREAM_TAG} 失败: {proc.stderr.decode(errors='replace').strip()}"

    rev = subprocess.run(
        ["git", "-C", str(dst), "rev-parse", "HEAD"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if rev.returncode != 0:
        return False, "无法解析 clone 后的 HEAD"
    head = rev.stdout.decode().strip()
    if head != UPSTREAM_SHA:
        return False, f"tag {UPSTREAM_TAG} HEAD={head} != 锁定 {UPSTREAM_SHA}"
    return True, ""


def verify_upstream(prov: dict) -> bool:
    """自远端 fetch 精确 tag 1.2.10，断言 SHA，并字节级比对 libs/checkpoint-sqlite/langgraph + LICENSE。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        ok, err = fetch_pinned(base)
        if not ok:
            print(f"[FAIL] 无法自远端获取上游 tag {UPSTREAM_TAG}: {err}")
            return False
        print(f"[OK] 自远端 {UPSTREAM_REPO} tag {UPSTREAM_TAG} 获取成功, SHA {UPSTREAM_SHA[:12]} 一致")

        upstream_base = base / "libs" / "checkpoint-sqlite"
        upstream_lg = upstream_base / "langgraph"
        if not upstream_lg.is_dir():
            print("[FAIL] tag 1.2.10 缺少 libs/checkpoint-sqlite/langgraph")
            return False

        mismatches: list[str] = []
        for rel, digest in collect_files().items():
            if rel == "LICENSE":
                upstream = upstream_base / "LICENSE"
            else:
                # rel 形如 langgraph/...，对应上游 libs/checkpoint-sqlite/langgraph/...
                upstream = upstream_base / rel
            if not upstream.is_file():
                mismatches.append(f"{rel} (上游缺失)")
                continue
            if sha256_of(upstream) != digest:
                mismatches.append(rel)

    ok = not mismatches
    if ok:
        print(f"[OK] 与上游 tag {UPSTREAM_TAG} ({UPSTREAM_SHA[:12]}) 的 libs/checkpoint-sqlite 字节级一致")
    else:
        for m in mismatches:
            print(f"[FAIL] 与上游不一致: {m}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", action="store_true", help="重新生成 MANIFEST.sha256")
    parser.add_argument("--offline", action="store_true", help="跳过上游锁定 tag 比对")
    args = parser.parse_args()

    if args.gen:
        write_manifest()
        return 0

    prov = load_provenance()
    results = [verify_license(), verify_manifest()]
    if not args.offline:
        results.append(verify_upstream(prov))
    else:
        print("[SKIP] offline 模式, 跳过上游锁定 tag 比对")

    passed = all(results)
    print("\n" + ("ALL PASS" if passed else "VERIFY FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
