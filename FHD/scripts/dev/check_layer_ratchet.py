# -*- coding: utf-8 -*-
"""分层债棘轮（ratchet）：只减不增地收口后端分层债。

守护两条基线（v10 线内迭代 · 配合 docs/architecture/REFACTOR_DECOMPOSITION_PLAN.md §1.4）：

1. ``app/services/**/*.py`` 文件总数 —— 冻结 ``services/`` 层，**不得新增**文件。
   新业务代码应落 ``app/domain`` / ``app/application`` / ``app/infrastructure``。
2. ``app/fastapi_routes/`` 中直接 ``import app.services.*`` 的**文件清单** —— 路由必须经
   ``application/`` 层，违规清单**只减不增**（绞杀者式收口）。

基线存于 ``scripts/dev/layer_ratchet_baseline.json``，由 ``--update-baseline`` 写入；
该模式**只允许把基线调低**（除非 ``--force``），保证棘轮单向收紧。

纯 AST 静态分析，不执行业务代码；零第三方依赖。退出码：违规 ``1`` / 正常 ``0`` / 用法错 ``2``。

用法::

    python scripts/dev/check_layer_ratchet.py            # 校验（CI）
    python scripts/dev/check_layer_ratchet.py --json
    python scripts/dev/check_layer_ratchet.py --update-baseline   # 收口后锁定新基线（只降）
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[2]
BASELINE_REL = Path("scripts") / "dev" / "layer_ratchet_baseline.json"

SERVICES_REL = Path("app") / "services"
ROUTES_REL = Path("app") / "fastapi_routes"


def _imports_app_services(path: Path) -> bool:
    """AST 判定：文件内是否存在 ``from app.services[...] import`` 或 ``import app.services[...]``。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app.services" or module.startswith("app.services."):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.services" or alias.name.startswith("app.services."):
                    return True
    return False


def measure(repo_root: Path) -> dict:
    """返回当前实测：services 文件数 + 路由违规文件清单（相对 app/ 的 posix 路径）。"""
    services_dir = repo_root / SERVICES_REL
    services_files = sorted(p for p in services_dir.rglob("*.py")) if services_dir.is_dir() else []

    routes_dir = repo_root / ROUTES_REL
    offenders: list[str] = []
    if routes_dir.is_dir():
        for py in sorted(routes_dir.rglob("*.py")):
            if _imports_app_services(py):
                offenders.append(py.relative_to(repo_root / "app").as_posix())

    return {
        "services_py_file_count": len(services_files),
        "routes_importing_services": offenders,
    }


def load_baseline(repo_root: Path) -> dict | None:
    path = repo_root / BASELINE_REL
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_baseline(repo_root: Path, data: dict) -> Path:
    path = repo_root / BASELINE_REL
    payload = {
        "_note": "分层债棘轮基线（只减不增）。由 check_layer_ratchet.py --update-baseline 维护。",
        "services_py_file_count": data["services_py_file_count"],
        "routes_importing_services": sorted(data["routes_importing_services"]),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def evaluate(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """返回 (errors, progress)。errors 非空即失败。"""
    errors: list[str] = []
    progress: list[str] = []

    cur_svc = current["services_py_file_count"]
    base_svc = baseline["services_py_file_count"]
    if cur_svc > base_svc:
        errors.append(
            f"app/services/ 文件数增加：{base_svc} → {cur_svc}（+{cur_svc - base_svc}）。"
            "新代码请落 app/domain | app/application | app/infrastructure。"
        )
    elif cur_svc < base_svc:
        progress.append(
            f"app/services/ 文件数下降：{base_svc} → {cur_svc}（-{base_svc - cur_svc}）✓ "
            "运行 --update-baseline 锁定进度。"
        )

    cur_routes = set(current["routes_importing_services"])
    base_routes = set(baseline["routes_importing_services"])
    new_offenders = sorted(cur_routes - base_routes)
    fixed = sorted(base_routes - cur_routes)
    if new_offenders:
        errors.append(
            "新增路由直连 app.services（应经 application 层）：\n"
            + "\n".join(f"    - app/{p}" for p in new_offenders)
        )
    if fixed:
        progress.append(
            f"已收口 {len(fixed)} 个路由（不再直连 app.services）✓ 运行 --update-baseline 锁定：\n"
            + "\n".join(f"    - app/{p}" for p in fixed)
        )

    return errors, progress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出实测与判定")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="把当前实测写为新基线（默认只允许调低；升高需 --force）",
    )
    parser.add_argument("--force", action="store_true", help="允许 --update-baseline 调高基线")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT_DEFAULT, help="仓库根（默认自动推断）")
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root
    if not repo_root.is_dir():
        print(f"ERROR: repo root not a directory: {repo_root}", file=sys.stderr)
        return 2

    current = measure(repo_root)

    if args.update_baseline:
        baseline = load_baseline(repo_root)
        if baseline is not None and not args.force:
            raising: list[str] = []
            if current["services_py_file_count"] > baseline["services_py_file_count"]:
                raising.append("services_py_file_count")
            if set(current["routes_importing_services"]) - set(
                baseline["routes_importing_services"]
            ):
                raising.append("routes_importing_services")
            if raising:
                print(
                    "拒绝调高基线（棘轮只减不增）：" + ", ".join(raising) + "。如确需放宽请加 --force。",
                    file=sys.stderr,
                )
                return 2
        out = write_baseline(repo_root, current)
        print(f"[layer-ratchet] 基线已写入 {out.relative_to(repo_root)}")
        print(f"[layer-ratchet]   services_py_file_count = {current['services_py_file_count']}")
        print(
            f"[layer-ratchet]   routes_importing_services = {len(current['routes_importing_services'])}"
        )
        return 0

    baseline = load_baseline(repo_root)
    if baseline is None:
        print(
            f"ERROR: 基线缺失：{BASELINE_REL}。先运行 --update-baseline 生成。",
            file=sys.stderr,
        )
        return 2

    errors, progress = evaluate(current, baseline)

    if args.json:
        print(
            json.dumps(
                {
                    "current": current,
                    "baseline": {
                        "services_py_file_count": baseline["services_py_file_count"],
                        "routes_importing_services": sorted(
                            baseline["routes_importing_services"]
                        ),
                    },
                    "errors": errors,
                    "progress": progress,
                    "ok": not errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if errors else 0

    print(f"[layer-ratchet] repo={repo_root}")
    print(
        f"[layer-ratchet] services .py: {current['services_py_file_count']} "
        f"(baseline {baseline['services_py_file_count']})"
    )
    print(
        f"[layer-ratchet] routes→app.services: {len(current['routes_importing_services'])} "
        f"(baseline {len(baseline['routes_importing_services'])})"
    )
    for p in progress:
        print(f"[layer-ratchet] PROGRESS: {p}")
    if errors:
        print(f"[layer-ratchet] {len(errors)} VIOLATION(S):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("[layer-ratchet] OK — 分层债未增长")
    return 0


if __name__ == "__main__":
    sys.exit(main())
