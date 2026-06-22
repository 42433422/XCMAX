"""
深度分析：核心业务功能中 Neuro 栈的实际使用情况

统计口径（与迁移后代码对齐）：
- **总线直连**：NeuroBus.publish、publish_event、NeuroEvent、subscribe 等
- **观测桥接**：instrument_*_class、neuro_trace_*、publish_neuro_event、neuro_notify_*、
  intent_integration、HTTP neuro trace 等

默认以仓库根目录为 ``ROOT``（脚本所在目录），避免硬编码盘符。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 与 NeuroBus / 域 emit 直接交互
_RE_BUS_DIRECT = re.compile(
    r"(?:"
    r"publish_event\s*\(|\.publish\s*\(|get_neuro_bus\s*\(\)|NeuroBus\s*\(|NeuroEvent\s*\("
    r"|subscribe_event|register_handler|\.emit\s*\(|get_intent_domain\s*\(|get_\w+_domain\s*\(\)\.emit"
    r")",
    re.MULTILINE,
)

# 迁移后 Application / Services / HTTP 观测路径
_RE_TRACE_BRIDGE = re.compile(
    r"(?:"
    r"instrument_application_service_class\s*\(|instrument_approval_service_class\s*\("
    r"|instrument_service_layer_class\s*\("
    r"|neuro_trace_app_service_call\s*\(|neuro_trace_service_call\s*\("
    r"|publish_neuro_event\s*\(|neuro_notify_\w+\s*\("
    r"|from\s+app\.neuro_bus\.application_neuro_bridge\s+import"
    r"|from\s+app\.neuro_bus\.integrations\.|try_neuro_reflex_intent\s*\("
    r"|neuro_http_trace_middleware|neuro_http_trace"
    r"|get_neurobus_health|/api/neurobus"
    r")",
    re.MULTILINE,
)

_RE_IMPORTS_NEURO = re.compile(r"from\s+app\.neuro_bus|import\s+app\.neuro_bus", re.MULTILINE)


def check_file_for_neuro_usage(file_path: Path) -> dict | None:
    """检查文件是否使用 Neuro 栈（总线直连或桥接观测）。"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    has_bus_direct = bool(_RE_BUS_DIRECT.search(content))
    has_trace_bridge = bool(_RE_TRACE_BRIDGE.search(content))
    imports_neuro = bool(_RE_IMPORTS_NEURO.search(content))
    actually_uses = has_bus_direct or has_trace_bridge

    return {
        "imports_neuro": imports_neuro,
        "actually_uses": actually_uses,
        "has_bus_direct": has_bus_direct,
        "has_trace_bridge": has_trace_bridge,
        "has_publish_style": bool(
            re.search(r"publish_event\s*\(|\.publish\s*\(|publish_neuro_event\s*\(", content)
        ),
    }


def _pct(used: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return used / total * 100.0


def analyze_application_services() -> list[dict]:
    """分析 app/application 下 *_app_service.py"""
    print("\n" + "=" * 80)
    print("Application Services 层 Neuro 使用情况（总线直连 + 桥接观测）")
    print("=" * 80)

    app_service_dir = ROOT / "app" / "application"
    services_analyzed: list[dict] = []

    app_candidates = set(app_service_dir.glob("**/*_app_service.py"))
    extra_app = ROOT / "app" / "application" / "workflow" / "approval_service.py"
    if extra_app.is_file():
        app_candidates.add(extra_app)

    for file in sorted(app_candidates):
        if "test" in str(file).lower():
            continue
        result = check_file_for_neuro_usage(file)
        if not result:
            continue
        rel_path = os.path.relpath(file, ROOT)
        services_analyzed.append(
            {
                "file": rel_path,
                "imports": result["imports_neuro"],
                "uses": result["actually_uses"],
                "bus": result["has_bus_direct"],
                "bridge": result["has_trace_bridge"],
            }
        )

    print(f"\n{'文件名':<52} {'导入':<5} {'使用':<5} {'总线':<5} {'桥接':<5}")
    print("-" * 80)

    uses_count = 0
    for svc in services_analyzed:
        print(
            f"{svc['file']:<52} "
            f"{'Y' if svc['imports'] else '-':<5} "
            f"{'Y' if svc['uses'] else '-':<5} "
            f"{'Y' if svc['bus'] else '-':<5} "
            f"{'Y' if svc['bridge'] else '-':<5}"
        )
        if svc["uses"]:
            uses_count += 1

    n = len(services_analyzed)
    print("-" * 80)
    print(f"总计：{n} 个 Application Services")
    print(f"已接入 Neuro（任一路径）：{uses_count} 个 ({_pct(uses_count, n):.1f}%)")
    return services_analyzed


def _iter_route_like_files() -> list[Path]:
    """主站 FastAPI 路由 + 遗留 backend 路由。"""
    files: list[Path] = []
    seen: set[str] = set()

    def add_many(base: Path, pattern: str) -> None:
        if not base.is_dir():
            return
        for p in base.glob(pattern):
            if not p.is_file():
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            if "test" in p.name.lower():
                continue
            seen.add(key)
            files.append(p)

    add_many(ROOT / "app" / "fastapi_routes", "**/*.py")
    add_many(ROOT / "app" / "control", "**/*.py")
    add_many(ROOT / "backend", "**/*.py")

    fa = ROOT / "app" / "fastapi_app.py"
    if fa.is_file():
        files.append(fa)

    compat = ROOT / "app" / "fastapi_compat_routes"
    if compat.is_dir():
        add_many(compat, "**/*.py")

    return sorted(set(files))


def analyze_routes() -> list[dict]:
    """分析含 @router / @app 路由定义或 Neuro 中间件的文件。"""
    print("\n" + "=" * 80)
    print("Routes / FastAPI 入口 Neuro 使用情况")
    print("=" * 80)

    route_decorator = re.compile(
        r"@app\.(get|post|put|delete|patch|route)\b|@router\.(get|post|put|delete|patch)\b",
        re.IGNORECASE,
    )

    routes_analyzed: list[dict] = []
    for file in _iter_route_like_files():
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not route_decorator.search(content) and file.name != "fastapi_app.py":
            continue

        result = check_file_for_neuro_usage(file)
        if not result:
            continue
        rel_path = os.path.relpath(file, ROOT)
        routes_analyzed.append(
            {
                "file": rel_path,
                "imports": result["imports_neuro"],
                "uses": result["actually_uses"],
                "bus": result["has_bus_direct"],
                "bridge": result["has_trace_bridge"],
            }
        )

    print(f"\n{'文件名':<58} {'导入':<5} {'使用':<5} {'总线':<5} {'桥接':<5}")
    print("-" * 80)

    uses_count = 0
    for route in routes_analyzed:
        print(
            f"{route['file']:<58} "
            f"{'Y' if route['imports'] else '-':<5} "
            f"{'Y' if route['uses'] else '-':<5} "
            f"{'Y' if route['bus'] else '-':<5} "
            f"{'Y' if route['bridge'] else '-':<5}"
        )
        if route["uses"]:
            uses_count += 1

    n = len(routes_analyzed)
    print("-" * 80)
    print(f"总计：{n} 个路由相关文件（含 fastapi_app 中间件）")
    print(f"已接入 Neuro：{uses_count} 个 ({_pct(uses_count, n):.1f}%)")
    return routes_analyzed


def analyze_app_services_layer() -> list[dict]:
    """分析 app/services 下业务服务（非 tests）。"""
    print("\n" + "=" * 80)
    print("app/services 层 Neuro 使用情况")
    print("=" * 80)

    svc_dir = ROOT / "app" / "services"
    rows: list[dict] = []
    for file in sorted(svc_dir.glob("**/*.py")):
        if file.name.startswith("test_") or "test" in file.parts:
            continue
        result = check_file_for_neuro_usage(file)
        if not result:
            continue
        rel = os.path.relpath(file, ROOT)
        rows.append(
            {
                "file": rel,
                "uses": result["actually_uses"],
                "bus": result["has_bus_direct"],
                "bridge": result["has_trace_bridge"],
            }
        )

    uses = sum(1 for r in rows if r["uses"])
    n = len(rows)
    print(f"扫描 {n} 个模块；已接入：{uses} ({_pct(uses, n):.1f}%)")
    for r in rows:
        if r["uses"]:
            print(f"  Y  {r['file']}")
    return rows


def analyze_core_business_logic() -> None:
    """抽样核心业务文件（与旧版兼容）。"""
    print("\n" + "=" * 80)
    print("核心业务文件抽样")
    print("=" * 80)

    core_rel = [
        "app/services/products_service.py",
        "app/services/shipment_number_mode_service.py",
        "app/services/ocr_service.py",
        "app/services/conversation_service.py",
        "app/services/intent_service.py",
        "app/services/ai_conversation_service.py",
        "app/services/hybrid_intent_service.py",
        "app/domain/services/shipment_rules_engine.py",
        "app/domain/services/pricing_engine.py",
    ]

    print(f"\n{'文件':<55} {'使用':<5} {'总线':<5} {'桥接':<5}")
    print("-" * 80)
    for rel in core_rel:
        p = ROOT / rel
        if not p.is_file():
            continue
        r = check_file_for_neuro_usage(p)
        if not r:
            continue
        print(
            f"{rel:<55} "
            f"{'Y' if r['actually_uses'] else '-':<5} "
            f"{'Y' if r['has_bus_direct'] else '-':<5} "
            f"{'Y' if r['has_trace_bridge'] else '-':<5}"
        )


def print_conclusion(app_services: list[dict], routes: list[dict], svc_rows: list[dict]) -> None:
    print("\n" + "=" * 80)
    print("结论（静态扫描：总线直连 ∪ 桥接观测）")
    print("=" * 80)

    app_uses = sum(1 for s in app_services if s["uses"])
    route_uses = sum(1 for r in routes if r["uses"])
    svc_uses = sum(1 for r in svc_rows if r["uses"])

    na = len(app_services)
    nr = len(routes)
    ns = len(svc_rows)

    print(
        f"""
1. Application Services（*_app_service.py + workflow/approval_service.py）
   - 文件数：{na}
   - 已接入：{app_uses} ({_pct(app_uses, na):.1f}%)

2. Routes / fastapi_app（主站 + backend 抽样）
   - 文件数：{nr}
   - 已接入：{route_uses} ({_pct(route_uses, nr):.1f}%)

3. app/services 全量
   - 模块数：{ns}
   - 已接入：{svc_uses} ({_pct(svc_uses, ns):.1f}%)

说明：旧脚本将「仅 import neuro_bus」算作未使用，且未扫描 app/fastapi_routes；
迁移后大量路径通过 ``instrument_*_class`` / ``publish_neuro_event`` / HTTP 中间件接入。
"""
    )


if __name__ == "__main__":
    app_services = analyze_application_services()
    routes = analyze_routes()
    svc_rows = analyze_app_services_layer()
    analyze_core_business_logic()
    print_conclusion(app_services, routes, svc_rows)
