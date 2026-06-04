#!/usr/bin/env python3
"""
sync_requirements.py — SSOT 同步脚本

从 pyproject.toml 自动生成 requirements-*.txt 单一真相源。
所有依赖版本与 extras 分类在 pyproject.toml 中维护；本脚本只做单向生成。

用法：
    python scripts/sync_requirements.py           # 检查并更新（dry-run 不写盘）
    python scripts/sync_requirements.py --write  # 写盘
    python scripts/sync_requirements.py --check  # CI 模式：不同步则退出码 1

依赖：Python 3.11+（tomllib 标准库）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

# 优先 stdlib tomllib（3.11+），降级到 tomli（3.9+）
try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[import-untyped,no-redef]
    except ModuleNotFoundError:
        sys.exit("❌ 缺少 TOML 解析器：Python 3.11+ 需 tomllib，3.10- 请 `pip install tomli`")

# 固定 FHD/ 根目录
ROOT = Path(__file__).resolve().parent.parent

# pyproject.toml 单一真相源
PYPROJECT = ROOT / "pyproject.toml"

# 生成的输出文件（按 extras / groups 名称）
OUTPUTS: dict[str, dict] = {
    "requirements-base.txt": {
        "kind": "base",
        "extras": None,  # 使用 [project.dependencies]
        "include_base": False,
        "header": "# 基础运行时依赖（生产必装）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-ml.txt": {
        "kind": "extras",
        "extras": "ml",
        "include_base": True,
        "header": "# ML 引擎（torch / transformers / prophet）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-ml-bert.txt": {
        "kind": "extras",
        "extras": "ml-bert",
        "include_base": True,
        "header": "# AI Provider · BERT 意图（torch/transformers）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-ml-rasa.txt": {
        "kind": "extras",
        "extras": "ml-rasa",
        "include_base": True,
        "header": "# AI Provider · RASA NLU（边缘档）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-ml-tts.txt": {
        "kind": "extras",
        "extras": "ml-tts",
        "include_base": True,
        "header": "# AI Provider · TTS（edge-tts）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-ml-forecast.txt": {
        "kind": "extras",
        "extras": "ml-forecast",
        "include_base": True,
        "header": "# ML · 时序预测（statsmodels/prophet）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-desktop.txt": {
        "kind": "extras",
        "extras": "desktop",
        "include_base": True,
        "header": "# 桌面版依赖（音频/视频/ASR）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-observability.txt": {
        "kind": "extras",
        "extras": "observability",
        "include_base": True,
        "header": "# 可观测性（OpenTelemetry 4 件套）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
    "requirements-dev.txt": {
        "kind": "extras",
        "extras": "dev",
        "include_base": True,
        "header": "# 开发/测试（pytest + mypy + ruff）· 由 scripts/sync_requirements.py 从 pyproject.toml 生成\n# ⚠️ 不要手工编辑！请改 pyproject.toml 后运行 python scripts/sync_requirements.py --write\n",
    },
}

# 不在 pyproject 中维护的特殊文件（独立来源，保留手工）
MANUAL_FILES = {
    "requirements-docs.txt": (
        "# 公开文档站（MkDocs Material）— 与 ci-docs-site.yml 一致\n"
        "# 此文件不在 pyproject 中维护（独立工具链，CI 单独安装）\n"
    ),
    "requirements-desktop-automation.txt": (
        "# Mac/Windows 桌面自动化（微信 UI 发消息等）\n"
        "# 此文件不在 pyproject 中维护（按平台 marker 条件安装）\n"
    ),
}


def load_pyproject() -> dict:
    if not PYPROJECT.exists():
        sys.exit(f"❌ 找不到 {PYPROJECT}")
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


def normalize(dep: str) -> str:
    """归一化依赖字符串：去除多余空格。"""
    return dep.strip()


def collect_base(pyproject: dict) -> list[str]:
    """从 [project.dependencies] 收集 base。"""
    return [normalize(d) for d in pyproject.get("project", {}).get("dependencies", [])]


def collect_extras(pyproject: dict, group: str) -> list[str]:
    """从 [project.optional-dependencies.<group>] 收集 extras。"""
    return [
        normalize(d)
        for d in pyproject.get("project", {}).get("optional-dependencies", {}).get(group, [])
    ]


def collect_dep_group(pyproject: dict, group: str) -> list[str]:
    """从 [dependency-groups.<group>] 收集（PEP 735）。"""
    return [
        normalize(d)
        for d in pyproject.get("dependency-groups", {}).get(group, [])
    ]


def render_requirements_base() -> str:
    """生成 requirements-base.txt（base 运行时，无 -r 引用）。"""
    pyproject = load_pyproject()
    cfg = OUTPUTS["requirements-base.txt"]
    deps = collect_base(pyproject)
    body = "\n".join(deps) + "\n"
    return cfg["header"] + body


def render_requirements_extras_or_group(filename: str) -> str:
    """生成 extras 或 dep-group 类 requirements 文件。"""
    pyproject = load_pyproject()
    cfg = OUTPUTS[filename]

    if cfg["kind"] == "extras":
        deps = collect_extras(pyproject, cfg["extras"])
    elif cfg["kind"] == "group":
        deps = collect_dep_group(pyproject, cfg["extras"])
    else:
        sys.exit(f"❌ 未知 kind: {cfg['kind']}")

    lines: list[str] = []
    if cfg["include_base"]:
        lines.append("-r requirements-base.txt")
    lines.extend(deps)
    body = "\n".join(lines) + "\n"
    return cfg["header"] + body


def render_for_filename(filename: str) -> str:
    """根据文件名分派到对应渲染函数。"""
    if filename == "requirements-base.txt":
        return render_requirements_base()
    if filename in OUTPUTS:
        return render_requirements_extras_or_group(filename)
    sys.exit(f"❌ 未知文件: {filename}")


def check_or_write(write: bool, check_only: bool) -> int:
    """主流程。"""
    if check_only and write:
        sys.exit("❌ --check 与 --write 互斥")

    diffs: list[tuple[str, str, str]] = []  # (filename, expected, actual)

    # 生成的目标
    for filename in OUTPUTS:
        expected = render_for_filename(filename)
        path = ROOT / filename
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if expected != actual:
            diffs.append((filename, expected, actual))

    # 手动维护的文件：仅校验 header 一致性（不重写内容）
    for filename, expected_header in MANUAL_FILES.items():
        path = ROOT / filename
        if not path.exists():
            diffs.append((filename, expected_header, ""))
            continue
        actual = path.read_text(encoding="utf-8")
        if not actual.startswith(expected_header):
            diffs.append(
                (filename, expected_header + "<原内容保留>", actual)
            )

    if not diffs:
        print("✅ 所有 requirements-*.txt 与 pyproject.toml 同步")
        return 0

    print(f"⚠️  发现 {len(diffs)} 个不同步文件：\n")
    for filename, expected, actual in diffs:
        print(f"─── {filename} ───")
        if actual:
            print("  ↳ 当前内容与 SSOT 不一致，需重新生成")
        else:
            print("  ↳ 文件不存在，需创建")
        if not check_only:
            (ROOT / filename).write_text(expected, encoding="utf-8")
            print(f"  ✅ 已写入 {filename}")
        print()

    if check_only:
        print("❌ CI 失败：存在与 pyproject.toml 不同步的 requirements 文件")
        print("   本地修复: python scripts/sync_requirements.py --write")
        return 1

    if not write:
        print("ℹ️  dry-run 完成；如需写盘请加 --write")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="写盘（默认 dry-run）")
    g.add_argument("--check", action="store_true", help="CI 检查：不同步则退出 1")
    args = p.parse_args()
    return check_or_write(write=args.write, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
