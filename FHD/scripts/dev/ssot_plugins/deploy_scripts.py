"""deploy-scripts 域适配器：lint scripts/deploy/ 下的 shell 脚本规范。

检查规则：
1. .sh 文件必须有 shebang（#!/bin/bash 或 #!/usr/bin/env bash）—— lib/ 目录除外（库文件被 source）
2. .sh 文件应有 set -euo pipefail（或至少 set -e）—— lib/ 目录除外
3. 不应硬编码产品版本号（四段 x.y.z.w 出现在 .sh 中视为可疑）—— 仅警告，不阻断

版本号 vs IP 地址识别：
- 部署脚本中合法出现 IP（127.0.0.1、119.27.178.147 等），不是版本号
- 用上下文关键字（HOST/IP/curl/http/@127./DATABASE_URL 等）排除 IP 误报
- fallback 版本号（如 1.0.0.0）仍会被报告，提醒开发者考虑动态读取
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT  # noqa: E402

DEPLOY_ROOT = ROOT / "scripts" / "deploy"
HARDCODED_VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\.\d+\b")
# IP 上下文关键字：行中含这些片段时，四段数字视为 IP 而非版本号。
# 覆盖：HOST 变量、curl http://、@127.（数据库连接串替换）、DATABASE_URL/VECTOR_DB_URL 等。
_IP_CONTEXT_RE = re.compile(
    r"(?:HOST|IP|curl|http|@127\.|127\.0\.0\.1|0\.0\.0\.0|DATABASE_URL|VECTOR_DB_URL|host\.docker\.internal)"
)


def _is_lib_file(rel: Path) -> bool:
    """lib/ 目录下的 .sh 是库文件（被 source），不需要 shebang/set -e。"""
    return "lib" in rel.parts


def check_drift() -> int:
    """只读检查：deploy 脚本规范。"""
    if not DEPLOY_ROOT.is_dir():
        print(f"deploy-scripts: 目录不存在 {DEPLOY_ROOT}", flush=True)
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    sh_files = sorted(DEPLOY_ROOT.rglob("*.sh"))

    for path in sh_files:
        rel = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"{rel}: 读取失败 {e}")
            continue

        lines = text.splitlines()
        is_lib = _is_lib_file(path.relative_to(DEPLOY_ROOT))

        # 规则 1：shebang（lib/ 除外）
        if not is_lib and (not lines or not lines[0].startswith("#!")):
            errors.append(f"{rel}: 缺少 shebang")

        # 规则 2：set -euo pipefail 或 set -e（lib/ 除外）
        if not is_lib:
            has_set_e = any("set -e" in line for line in lines[:20])
            if not has_set_e:
                errors.append(f"{rel}: 缺少 'set -e'（建议 set -euo pipefail）")

        # 规则 3：硬编码版本号（仅警告）
        # _IP_CONTEXT_RE 跳过含 IP 上下文关键字的行（127.0.0.1、119.27.178.147 等合法 IP）
        for i, line in enumerate(lines, 1):
            if (
                HARDCODED_VERSION_RE.search(line)
                and not _IP_CONTEXT_RE.search(line)
                and not line.strip().startswith("#")
            ):
                warnings.append(f"{rel}:L{i}: 硬编码四段产品版本号")

    if warnings:
        print(
            f"deploy-scripts: {len(warnings)} 条警告（硬编码版本号，可能是版本检查脚本）",
            flush=True,
        )
        for w in warnings:
            print(f"  ⚠ {w}", flush=True)

    if errors:
        print(f"deploy-scripts: {len(errors)} 个问题", flush=True)
        for error in errors:
            print(f"  - {error}", flush=True)
        return 1

    print(
        f"deploy-scripts: OK（{len(sh_files)} 个 .sh 脚本规范，{len(warnings)} 条警告）", flush=True
    )
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("deploy-scripts: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
