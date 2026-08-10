#!/usr/bin/env python3
"""XCAGI vendored langgraph-checkpoint-postgres 来源与许可证锁定验证脚本 (LG-W0-04).

本脚本为「git tag -> SHA」来源校验（区别于 sdist 来源）：锁定的是上游 langgraph 仓库 tag v1.2.10
@ commit 41341457342327166d72fc11952ab28fb61ec0bf（见同目录 PROVENANCE.json）。

职责:
  1. 校验本目录下所有 vendored 文件 (langgraph/ 包 + LICENSE) 的 SHA-256 与 MANIFEST.sha256 一致。
  2. 校验 LICENSE 为 MIT (含关键字检查)。
  3. 校验 vendored 副本与上游「锁定 commit」的 libs/checkpoint-postgres/langgraph + LICENSE 字节级一致
     （原样吸收），跳过 __pycache__/pyc 本地产物。

用法:
  python verify_vendor.py            # 本地清单 + LICENSE + 上游锁定 commit 比对
  python verify_vendor.py --offline  # 仅本地清单 + LICENSE, 跳过上游比对
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

# MANIFEST 需要覆盖的顶层条目 (langgraph/ 包目录下所有文件 + LICENSE)
TOPNODE = ["langgraph", "LICENSE"]

# 上游 langgraph 本地 git 检出（仅用于通过 git archive 取「锁定 commit」的源码）
REPO = Path("/tmp/langgraph_retort")
# 锁定 commit 对应上游 libs/checkpoint-postgres 下的相对路径
UPSTREAM_PATHS = ["libs/checkpoint-postgres/langgraph", "libs/checkpoint-postgres/LICENSE"]

# 本地产物目录/文件：不入 MANIFEST，也不参与上游比对
EXCLUDE_DIRS = {"__pycache__", ".venv", "build", "dist"}
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


def _extract_pinned(sha: str, dst: Path) -> tuple[bool, str]:
    """用 git archive 导出 PROVENANCE 锁定的 commit 的 libs/checkpoint-postgres/langgraph + LICENSE 到 dst。

    若锁定 commit 对象不在本地仓库，先尝试从 origin fetch（depth 1）。返回 (成功, 错误信息)。
    """
    if not (REPO / ".git").exists():
        return False, f"上游 git 检出缺失: {REPO}"

    def _try_archive() -> bool:
        try:
            proc = subprocess.run(
                ["git", "-C", str(REPO), "archive", "--format=tar", sha, *UPSTREAM_PATHS],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if proc.returncode == 0:
                with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
                    # filter="data" 需 Python >=3.12；旧版本降级为无过滤解包（来源为可信锁定 commit）
                    kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
                    tar.extractall(dst, **kwargs)
                return True
            return False
        except Exception:  # noqa: BLE001
            return False

    if _try_archive():
        return True, ""
    # 尝试 fetch 后再 archive
    fetch = subprocess.run(
        ["git", "-C", str(REPO), "fetch", "--depth", "1", "origin", sha],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if fetch.returncode != 0:
        return False, f"git fetch {sha} 失败（网络/远端不可达）"
    if not _try_archive():
        return False, f"git archive {sha} 失败"
    return True, ""


def verify_upstream(prov: dict) -> bool:
    """校验 vendored 副本与上游锁定 commit 的 libs/checkpoint-postgres/langgraph + LICENSE 字节级一致。"""
    sha = prov["upstream_commit_sha"]
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        ok, err = _extract_pinned(sha, base)
        if not ok:
            print(f"[FAIL] 无法从上游获取锁定 commit: {err}")
            return False
        upstream_base = base / "libs" / "checkpoint-postgres"
        upstream_lg = upstream_base / "langgraph"
        if not upstream_lg.is_dir():
            print("[FAIL] 锁定 commit 缺少 libs/checkpoint-postgres/langgraph")
            return False

        mismatches: list[str] = []
        for rel, digest in collect_files().items():
            if rel == "LICENSE":
                upstream = upstream_base / "LICENSE"
            else:
                # rel 形如 langgraph/...，对应上游 libs/checkpoint-postgres/langgraph/...
                upstream = upstream_base / rel
            if not upstream.is_file():
                mismatches.append(f"{rel} (上游缺失)")
                continue
            if sha256_of(upstream) != digest:
                mismatches.append(rel)

    ok = not mismatches
    if ok:
        print(f"[OK] 与上游锁定 commit {sha[:12]} 的 libs/checkpoint-postgres 字节级一致")
    else:
        for m in mismatches:
            print(f"[FAIL] 与上游不一致: {m}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", action="store_true", help="重新生成 MANIFEST.sha256")
    parser.add_argument("--offline", action="store_true", help="跳过上游锁定 commit 比对")
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