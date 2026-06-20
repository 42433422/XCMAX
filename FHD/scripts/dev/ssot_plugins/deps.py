"""deps 域适配器：check 比较 pyproject.toml optional-dependencies 与 requirements*.txt。

SSOT: pyproject.toml [project.optional-dependencies]
  - server-api → requirements.txt
  - ml → requirements-ml.txt

check 只读比较包名集合（忽略版本号），报告差异。
sync 不自动执行（需人工 reconcile，因 requirements.txt 可能含额外运行时依赖）。
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

PYPROJECT = ROOT / "pyproject.toml"
REQ_FILE = ROOT / "requirements.txt"
REQ_ML_FILE = ROOT / "requirements-ml.txt"

# 匹配 "package-name[extra]>=1.0" 或 "package-name==1.0" 等
PKG_RE = re.compile(r"^([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?")


def _parse_toml_optional_deps(text: str) -> dict[str, set[str]]:
    """简易解析 [project.optional-dependencies] 段（避免 tomllib 3.11 依赖）。"""
    deps: dict[str, set[str]] = {}
    in_section = False
    current_extra: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project.optional-dependencies]":
            in_section = True
            continue
        if in_section and stripped.startswith("[") and stripped.endswith("]"):
            # 进入下一个 section
            if not stripped.startswith("[project.optional-dependencies"):
                in_section = False
                continue
        if not in_section:
            continue
        # extra 名 = [
        m = re.match(r"^([a-zA-Z0-9_-]+)\s*=\s*\[", stripped)
        if m:
            current_extra = m.group(1)
            deps[current_extra] = set()
            continue
        # "package>=1.0",
        if current_extra and stripped.startswith('"'):
            m2 = re.match(r'^"([^"]+)"', stripped)
            if m2:
                pkg_spec = m2.group(1)
                pm = PKG_RE.match(pkg_spec)
                if pm:
                    deps[current_extra].add(pm.group(1).lower())
    return deps


def _parse_requirements(path: Path) -> set[str]:
    """解析 requirements.txt 格式，返回包名集合（小写）。"""
    if not path.is_file():
        return set()
    pkgs: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # 去掉环境标记 e.g. package==1.0; python_version < "3.11"
        line = line.split(";")[0].strip()
        m = PKG_RE.match(line)
        if m:
            pkgs.add(m.group(1).lower())
    return pkgs


def check_drift() -> int:
    """只读检查：pyproject optional-deps vs requirements*.txt。"""
    if not PYPROJECT.is_file():
        print(f"deps: SSOT 文件不存在 {PYPROJECT}", flush=True)
        return 2

    toml_deps = _parse_toml_optional_deps(PYPROJECT.read_text(encoding="utf-8"))
    req_pkgs = _parse_requirements(REQ_FILE)
    req_ml_pkgs = _parse_requirements(REQ_ML_FILE)

    errors: list[str] = []

    # server-api vs requirements.txt
    server_api = toml_deps.get("server-api", set())
    if server_api:
        missing_in_req = server_api - req_pkgs
        extra_in_req = req_pkgs - server_api
        for p in sorted(missing_in_req):
            errors.append(f"requirements.txt 缺少 {p}（pyproject server-api 声明）")
        for p in sorted(extra_in_req):
            errors.append(f"requirements.txt 多余 {p}（pyproject server-api 未声明）")

    # ml vs requirements-ml.txt
    ml = toml_deps.get("ml", set())
    if ml:
        missing_in_ml = ml - req_ml_pkgs
        extra_in_ml = req_ml_pkgs - ml
        for p in sorted(missing_in_ml):
            errors.append(f"requirements-ml.txt 缺少 {p}（pyproject ml 声明）")
        for p in sorted(extra_in_ml):
            errors.append(f"requirements-ml.txt 多余 {p}（pyproject ml 未声明）")

    if errors:
        print(f"deps: {len(errors)} 处漂移", flush=True)
        for e in errors[:30]:
            print(f"  - {e}", flush=True)
        if len(errors) > 30:
            print(f"  ... 还有 {len(errors) - 30} 条", flush=True)
        return 1

    print(f"deps: OK（server-api {len(server_api)} 包 / ml {len(ml)} 包一致）", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("deps: 不自动 sync（需人工 reconcile requirements*.txt）", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
