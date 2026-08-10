#!/usr/bin/env python3
"""langgraph 上游来源与许可证锁定验证脚本 (W0-01).

职责:
  1. 校验 PROVENANCE.json 中锁定的 tag 确实指向 locked_sha (网络 git ls-remote)。
  2. 校验本目录下所有 vendor 文件 (langgraph/ 包 + LICENSE) 的 SHA-256 与 MANIFEST.sha256 一致。
     构建/缓存/虚拟环境产物自动排除: __pycache__、*.pyc、.pytest_cache、.venv、build、dist、*.egg-info。
  3. 校验 LICENSE 为 MIT。
  4. --smoke 模式下用 vendor 包实际构建/编译/invoke 一个 StateGraph (验证可导入可用)。
     依赖 venv 建在 TemporaryDirectory 中, 跑完自动清理, 不在仓库目录残留 .venv。

用法:
  python verify_vendor.py              # 在线 tag->SHA + 文件哈希 + LICENSE
  python verify_vendor.py --offline    # 跳过网络 tag 校验
  python verify_vendor.py --smoke      # 追加 StateGraph 冒烟 (临时 venv, 自动清理)
  python verify_vendor.py --gen        # 重新生成 MANIFEST.sha256

退出码: 0=全部通过; 1=校验失败。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, TypedDict

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.sha256"
PROVENANCE = HERE / "PROVENANCE.json"

# MANIFEST 覆盖的顶层条目 (langgraph/ 包目录 + LICENSE)
TOPNODE = ["langgraph", "LICENSE"]

# 构建/缓存/虚拟环境产物, 从 MANIFEST 与校验中排除
EXCLUDE_NAMES = {"__pycache__", ".pytest_cache", ".venv", "build", "dist", ".git"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".egg-info")
EXCLUDE_SUFFIX_ANY = (".pyc", ".pyo")
EXCLUDE_STEM_EGG = "*.egg-info"


def is_excluded(rel: str) -> bool:
    """判断相对路径是否为应排除的产物。"""
    parts = Path(rel).parts
    if any(p in EXCLUDE_NAMES for p in parts):
        return True
    name = parts[-1] if parts else rel
    if name.endswith(EXCLUDE_SUFFIX_ANY) or name.endswith(".egg-info"):
        return True
    if name in ("build", "dist"):
        return True
    return False


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files() -> dict[str, str]:
    """返回 {相对路径(正斜杠): sha256}, 覆盖 TOPNODE 下所有非排除文件。"""
    result: dict[str, str] = {}
    for node in TOPNODE:
        p = HERE / node
        if p.is_file():
            if not is_excluded(node):
                result[node] = sha256_of(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not is_excluded(f.relative_to(HERE).as_posix()):
                    rel = f.relative_to(HERE).as_posix()
                    result[rel] = sha256_of(f)
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


def verify_tag_points_to_sha(prov: dict) -> bool:
    tag = prov["locked_tag"]
    expected = prov["locked_sha"]
    repo = prov["upstream_repo"]
    proc = subprocess.run(
        ["git", "ls-remote", "--tags", repo, f"refs/tags/{tag}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"[FAIL] git ls-remote 失败: {proc.stderr.strip()}")
        return False
    line = proc.stdout.strip()
    if not line:
        print(f"[FAIL] 未找到远程 tag: {tag}")
        return False
    actual = line.split()[0]
    ok = actual == expected
    print(f"[{'OK' if ok else 'FAIL'}] tag {tag} -> {actual} "
          f"{'== 锁定 SHA' if ok else f'!= 锁定 SHA {expected}'}")
    return ok


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
        print(f"[OK] MANIFEST.sha256 校验通过: {len(actual)} 个文件哈希一致 "
              f"(已排除 __pycache__/*.pyc/.pytest_cache/.venv/build/dist/*.egg-info)")
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


# ---- StateGraph 冒烟用状态/节点 (模块级, 供 langgraph 解析函数注解) ----
class _SmokeState(TypedDict):
    value: int
    routed: str


def _smoke_inc(state: _SmokeState) -> dict:
    return {"value": state["value"] + 1}


def _smoke_route(state: _SmokeState) -> Literal["inc", "end"]:
    return "end" if state["value"] >= 3 else "inc"


def smoke_state_graph() -> bool:
    """用 vendor 包实际构建/编译/invoke 一个 StateGraph。"""
    sys.path.insert(0, str(HERE))  # 优先解析到 vendor 的 langgraph 包
    try:
        from langgraph.graph import StateGraph, START, END, __file__ as _graph_file
    except Exception as e:  # pragma: no cover - 依赖缺失时的失败路径
        print(f"[FAIL] 导入 vendor langgraph 失败: {type(e).__name__}: {e}")
        return False
    print(f"[..] 冒烟使用 vendor 包: {_graph_file}")

    try:
        g = StateGraph(_SmokeState)
        g.add_node("inc", _smoke_inc)
        g.add_edge(START, "inc")
        g.add_conditional_edges(
            "inc", _smoke_route, {"inc": "inc", "end": END}
        )
        compiled = g.compile()
        out = compiled.invoke({"value": 0, "routed": ""})
        assert out["value"] == 3, f"期望 value=3, 实际 {out['value']}"
        print(f"[OK] StateGraph build/compile/invoke 通过 (invoke 结果 value={out['value']})")
        return True
    except Exception as e:  # pragma: no cover
        print(f"[FAIL] StateGraph build/compile/invoke 失败: {type(e).__name__}: {e}")
        return False


def _find_smoke_python() -> str | None:
    """找一个 Python>=3.10 的解释器用于临时 venv (langgraph 1.2.10 要求 >=3.10)。"""
    if sys.version_info >= (3, 10):
        return sys.executable
    for name in ("python3.13", "python3.12", "python3.11", "python3.10"):
        p = shutil.which(name)
        if p:
            return p
    return None


def run_smoke_in_temp_venv(prov: dict) -> bool:
    """在 TemporaryDirectory 中建 venv 装依赖跑 StateGraph 冒烟, 结束自动清理 (不再 rm -rf 仓库内 .venv)。"""
    py = _find_smoke_python()
    if not py:
        print("[FAIL] 未找到 Python>=3.10 解释器, 无法运行 StateGraph 冒烟")
        return False
    version = prov["locked_tag"]
    script = str(Path(__file__).resolve())
    venv_py = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # 冒烟不写 __pycache__/pyc 进 vendor 源码
    with tempfile.TemporaryDirectory(prefix="lg-smoke-") as tmp:
        venv = Path(tmp) / "venv"
        print(f"[..] 临时 venv: {venv} (TemporaryDirectory 自动清理)")
        if subprocess.run([py, "-m", "venv", str(venv)], env=env).returncode != 0:
            print("[FAIL] 创建临时 venv 失败")
            return False
        vpy = str(venv / venv_py)
        print(f"[..] 安装 langgraph=={version} 依赖...")
        if subprocess.run([vpy, "-m", "pip", "install", "--quiet", f"langgraph=={version}"], env=env).returncode != 0:
            print("[FAIL] 临时 venv 依赖安装失败")
            return False
        return subprocess.run([vpy, script, "--smoke-inner"], env=env).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", action="store_true", help="重新生成 MANIFEST.sha256")
    parser.add_argument("--offline", action="store_true", help="跳过网络 tag->SHA 校验")
    parser.add_argument("--smoke", action="store_true", help="追加 StateGraph 功能冒烟 (临时 venv)")
    parser.add_argument("--smoke-inner", action="store_true",
                        help="仅运行 StateGraph 冒烟 (供临时 venv 子进程内部调用)")
    args = parser.parse_args()

    if args.gen:
        write_manifest()
        return 0

    if args.smoke_inner:
        return 0 if smoke_state_graph() else 1

    prov = load_provenance()
    results = [verify_license(), verify_manifest()]
    if not args.offline:
        results.append(verify_tag_points_to_sha(prov))
    else:
        print(f"[SKIP] offline 模式, 跳过 tag->SHA 网络校验 (锁定 {prov['locked_tag']} -> {prov['locked_sha']})")
    if args.smoke:
        results.append(run_smoke_in_temp_venv(prov))

    passed = all(results)
    print("\n" + ("ALL PASS" if passed else "VERIFY FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
