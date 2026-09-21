"""冻结后端动态导入覆盖守卫（1.0.0.5 安装版 500 的回归测试）。

桌面安装包的后端是 PyInstaller 冻结产物，只能看见静态 import；但宿主能力是通过
``app/mod_sdk/host_services.py`` 的字符串映射和 ``import_module("app...")`` 字面量
动态取用的，PyInstaller 看不到它们。出现目标模块缺失时，安装版会在请求时抛
``ModuleNotFoundError`` 返回 500 —— 1.0.0.5 的
``GET /api/mod/xcagi-lan-license-bridge/status``（宿主日志：
``No module named 'app.legacy.lan'``）与客户服务桥部分路由就是这个原因。

本文件把修复固化为四条静态守卫：
1. 动态引用目标必须在源码树中存在（防死映射，如 wechat 域退役后的遗留）；
2. 动态引用目标必须被 ``scripts/package/xcagi_backend.spec`` 收集，或在 app/、XCAGI/
   内有静态 import（PyInstaller 能沿静态图找到）；Mod 目录是随包数据、不参与静态分析，
   但其 ``import_module("app...")`` 字面量同样计入本守卫（宿主策略明确不随包的 Mod 除外）；
3. 代码从 ``host_services`` 取用的名字必须有对应导出或模块级定义；
4. 映射的属性目标必须真实定义（跳过 ``globals().update`` / ``import *`` /
   ``__getattr__`` 之类的动态再导出模块）。
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
SPEC_PATH = FHD / "scripts" / "package" / "xcagi_backend.spec"
HOST_SERVICES_PATH = FHD / "app" / "mod_sdk" / "host_services.py"
ANALYSIS_ROOTS = ("app", "XCAGI")
CALLER_ROOTS = ("app", "XCAGI", "mods")
# Mod 是随包数据，不参与 PyInstaller 静态分析；它们的 importlib 字面量同样要在冻结包内解析，
# 因此并入动态引用扫描。例外：宿主打包策略明确不随包发布的 Mod
# （scripts/package/stage-bundled-mods.sh 的 EXCLUDE_ALWAYS）。
DYNAMIC_LITERAL_ROOTS = ("app", "XCAGI", "mods")
BUNDLE_EXCLUDED_MODS = frozenset({"_employees"})
_APP_MODULE_RE = re.compile(r"^(?:appdirs|app(?:\.[A-Za-z_]\w*)+)$")
_DYNAMIC_REEXPORT_MARKERS = ("globals().update", "import *", "__getattr__")

# 有意为之的可选模块探测：目标模块可能不存在，调用点用 except 兜底，不属于死映射。
# 其余动态引用目标必须真实存在，否则视为退役遗留（如 wechat 域）。
_OPTIONAL_DYNAMIC_TARGETS = frozenset(
    {
        # 测试数据库管理器由测试环境按需注入（app/db/__init__.py 内 try/except）。
        "app.db.test_db_manager",
        # 遗留自然语言 pandas 转换器（已退役），调用点已按错误路径兜底。
        "app.legacy.excel_text_to_pandas",
    }
)


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return None


def _iter_py_files(roots: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        for path in (FHD / root).rglob("*.py"):
            if "__pycache__" not in path.parts:
                paths.append(path)
    return paths


def _iter_dynamic_literal_files() -> list[Path]:
    return [
        path
        for path in _iter_py_files(DYNAMIC_LITERAL_ROOTS)
        if not (BUNDLE_EXCLUDED_MODS & set(path.parts))
    ]


def _module_path(module: str) -> Path | None:
    rel = Path(*module.split("."))
    for candidate in ((FHD / rel).with_suffix(".py"), FHD / rel / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def _exports() -> dict[str, tuple[str, str]]:
    tree = _parse(HOST_SERVICES_PATH)
    assert tree is not None, "host_services.py 不可解析"
    exports: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Tuple)
                and len(value.elts) == 2
                and all(
                    isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    for elt in value.elts
                )
            ):
                exports[key.value] = (value.elts[0].value, value.elts[1].value)
    assert len(exports) > 100, f"host_services 导出表异常（{len(exports)} 项）"
    return exports


@lru_cache(maxsize=1)
def _dynamic_targets() -> dict[str, str]:
    """module -> 引用处（用于失败信息）。"""
    targets: dict[str, str] = {}
    for name, (module, _attr) in _exports().items():
        targets[module] = f"host_services 导出 {name!r}"
    for path in _iter_dynamic_literal_files():
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else (func.id if isinstance(func, ast.Name) else "")
            )
            if func_name not in ("import_module", "__import__"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            module = node.args[0].value
            if isinstance(module, str) and module.startswith("app"):
                targets.setdefault(module, f"importlib 字面量：{path.relative_to(FHD)}")
    return targets


@lru_cache(maxsize=1)
def _spec_entries() -> frozenset[str]:
    tree = _parse(SPEC_PATH)
    assert tree is not None, "xcagi_backend.spec 不可解析"
    entries = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _APP_MODULE_RE.match(node.value)
    }
    assert entries, "spec 未声明任何 app 模块收集项"
    return frozenset(entries)


@lru_cache(maxsize=1)
def _statically_imported() -> frozenset[str]:
    resolved: set[str] = set()
    for path in _iter_py_files(ANALYSIS_ROOTS):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                resolved.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                resolved.add(node.module)
                resolved.update(
                    f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
                )
    return frozenset(resolved)


def _covered_by_spec(module: str) -> bool:
    return any(module == entry or module.startswith(entry + ".") for entry in _spec_entries())


def _top_level_names(path: Path) -> set[str] | None:
    tree = _parse(path)
    if tree is None:
        return None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return names


def test_dynamic_targets_exist_in_source_tree():
    missing = {
        module: ref
        for module, ref in _dynamic_targets().items()
        if _module_path(module) is None and module not in _OPTIONAL_DYNAMIC_TARGETS
    }
    assert not missing, "动态引用指向已不存在的模块：\n" + "\n".join(
        f"  {module} <- {ref}" for module, ref in sorted(missing.items())
    )


def test_dynamic_targets_covered_by_frozen_spec_or_static_import():
    static = _statically_imported()
    uncovered = {
        module: ref
        for module, ref in _dynamic_targets().items()
        if _module_path(module) is not None
        and module not in static
        and not _covered_by_spec(module)
    }
    assert not uncovered, (
        "以下模块只能被动态取用，但冻结包 spec 未收集、静态图里也不可见，"
        "安装版会在请求时 ModuleNotFoundError：\n"
        + "\n".join(f"  {module} <- {ref}" for module, ref in sorted(uncovered.items()))
        + "\n请在 scripts/package/xcagi_backend.spec 的 collect_submodules/hiddenimports 中补齐"
    )


def test_export_attr_targets_are_defined():
    problems: list[str] = []
    for name, (module, attr) in sorted(_exports().items()):
        path = _module_path(module)
        if path is None or not attr:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if any(marker in source for marker in _DYNAMIC_REEXPORT_MARKERS):
            continue
        names = _top_level_names(path)
        if names is not None and attr not in names:
            problems.append(f"{name} -> {module}.{attr}")
    assert not problems, "导出映射指向未定义的属性：\n" + "\n".join(
        f"  {item}" for item in problems
    )


def test_host_services_names_imported_by_callers_are_provided():
    exports = _exports()
    host_names = _top_level_names(HOST_SERVICES_PATH) or set()
    problems: list[str] = []
    for path in _iter_py_files(CALLER_ROOTS):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "app.mod_sdk.host_services" or node.level:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if alias.name in exports or alias.name in host_names:
                    continue
                problems.append(f"{alias.name} <- {path.relative_to(FHD)}")
    assert not problems, (
        "调用方从 host_services 取的名字既无导出也无定义，运行时必然失败：\n"
        + "\n".join(f"  {item}" for item in sorted(set(problems)))
    )
