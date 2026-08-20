#!/usr/bin/env python3
"""XCAGI vendored langgraph-prebuilt 来源与许可证锁定验证脚本 (LG-W0-05).

本脚本为「git tag -> SHA」来源校验（与 xcagi_langgraph_checkpoint 的 LG-W0-03 同型）：
锁定的是上游 langgraph 仓库 tag 1.2.10 @ commit 41341457342327166d72fc11952ab28fb61ec0bf
（见同目录 PROVENANCE.json）。

职责:
  1. 校验本目录下所有 vendored 文件 (langgraph/prebuilt 包 + LICENSE) 的 SHA-256 与 MANIFEST.sha256 一致。
  2. 校验 LICENSE 为 MIT (含关键字检查)。
  3. 校验 vendored 副本与上游「tag 1.2.10 解析出的 commit」的 libs/prebuilt/langgraph/prebuilt + LICENSE
     字节级一致（原样吸收）。在线模式取回远端 tag 1.2.10，rev-parse 其指向的 commit，要求恰好等于
     锁定 SHA 41341457342327166d72fc11952ab28fb61ec0bf，再对该 commit 做 git archive 与本地比对。
     跳过本地产物（__pycache__/pyc/.venv/build/dist/*.egg-info/.pytest_cache 等）。

可移植性: 上游源码在 with tempfile.TemporaryDirectory() 作用域内临时浅克隆（取回 tag 而非固定 SHA 或
  /tmp 检出），作用域退出自动清理，不残留临时目录；离线模式（--offline）则完全跳过上游比对。

用法:
  python verify_vendor.py            # 本地清单 + LICENSE + 上游 tag->commit 比对
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

# 锁定 commit 对应上游 libs/prebuilt 下的相对路径
UPSTREAM_PATHS = ["libs/prebuilt/langgraph/prebuilt", "libs/prebuilt/LICENSE"]

# 本地产物目录/文件：不入 MANIFEST，也不参与上游比对
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".venv", "build", "dist"}
EXCLUDE_SUFFIXES = {".pyc", ".egg-info"}


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


def _clone_tag_at_sha(prov: dict, workdir: Path) -> tuple[bool, Path, str]:
    """在 workdir 内浅克隆上游并取回远端 tag，校验其解析的 commit 等于锁定 SHA。

    返回 (成功, 仓库路径, 错误信息)。workdir 由调用方的 TemporaryDirectory 作用域负责清理。
    """
    sha = prov["upstream_commit_sha"]
    tag = prov.get("upstream_tag", "1.2.10")
    repo_url = prov["upstream_repo"]
    repo = workdir / "repo"
    steps = [
        ["git", "init", "-q", str(repo)],
        ["git", "-C", str(repo), "remote", "add", "origin", repo_url],
        # 取回远端 tag 并写入本地 refs/tags/<tag>，以便后续 rev-parse 解引用该 tag
        [
            "git",
            "-C",
            str(repo),
            "fetch",
            "--depth",
            "1",
            "origin",
            f"refs/tags/{tag}:refs/tags/{tag}",
        ],
    ]
    for cmd in steps:
        proc = subprocess.run(cmd, check=False, capture_output=True)
        if proc.returncode != 0:
            return (
                False,
                repo,
                (
                    f"git 步骤失败: {' '.join(cmd)} -> "
                    f"{proc.stderr.decode(errors='replace').strip()}"
                ),
            )

    # rev-parse 该 tag 指向的 commit（^{} 解引用 annotated/lightweight tag）
    ref = f"refs/tags/{tag}^{{}}"
    rev = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=False,
        capture_output=True,
    )
    tag_commit = rev.stdout.decode(errors="replace").strip()
    if rev.returncode != 0 or tag_commit != sha:
        return (
            False,
            repo,
            (f"远端 tag {tag} 未解析到锁定 SHA: tag_commit={tag_commit!r} != {sha!r}"),
        )
    return True, repo, ""


def verify_upstream(prov: dict) -> bool:
    """取回远端 tag 1.2.10，校验其 commit 等于锁定 SHA，并字节级比对 libs/prebuilt + LICENSE。"""
    sha = prov["upstream_commit_sha"]
    tag = prov.get("upstream_tag", "1.2.10")
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        ok, repo, err = _clone_tag_at_sha(prov, base)
        if not ok:
            print(f"[FAIL] 无法从上游 tag {tag} 获取锁定 commit: {err}")
            return False

        archive = subprocess.run(
            ["git", "-C", str(repo), "archive", "--format=tar", sha, *UPSTREAM_PATHS],
            check=False,
            capture_output=True,
        )
        if archive.returncode != 0:
            print(
                f"[FAIL] git archive {sha[:12]} 失败: "
                f"{archive.stderr.decode(errors='replace').strip()}"
            )
            return False

        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            # filter="data" 需 Python >=3.12；旧版本降级为无过滤解包（来源为可信锁定 commit）
            kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
            tar.extractall(base, **kwargs)

        # tar 内已含 libs/prebuilt/ 完整树；vendored rel 直接拼接在该根之下
        upstream_lg = base / "libs" / "prebuilt"
        upstream_lic = base / "libs" / "prebuilt" / "LICENSE"
        if not upstream_lg.is_dir():
            print("[FAIL] 锁定 commit 缺少 libs/prebuilt")
            return False

        mismatches: list[str] = []
        for rel, digest in collect_files().items():
            upstream = upstream_lic if rel == "LICENSE" else upstream_lg / rel
            if not upstream.is_file():
                mismatches.append(f"{rel} (上游缺失)")
                continue
            if sha256_of(upstream) != digest:
                mismatches.append(rel)

    ok = not mismatches
    if ok:
        print(
            f"[OK] 远端 tag {tag} 解析为锁定 commit {sha[:12]}，"
            f"libs/prebuilt 字节级一致"
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
