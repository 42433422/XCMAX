"""mobile-tri-platform 域适配器：校验移动三端 SSOT、token 与性能监控入口。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT, load_registry  # noqa: E402

MOBILE_SSOT_DOC = ROOT / "docs" / "mobile_tri_platform_ssot.md"
SSOT_INDEX = ROOT / "docs" / "SSOT_INDEX.md"
TOKENS = ROOT / "config" / "mobile_design_tokens.json"

ANDROID_THEME = ROOT / "mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/theme/Theme.kt"
ANDROID_TYPE = ROOT / "mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/theme/Type.kt"
ANDROID_SHAPE = ROOT / "mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/theme/Shape.kt"
ANDROID_ANALYTICS = ROOT / "mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/observability/XcagiAnalytics.kt"

IOS_PARITY = ROOT / "mobile-ios/PARITY_MATRIX.md"
IOS_PROJECT_YML = ROOT / "mobile-ios/project.yml"
IOS_THEME = ROOT / "mobile-ios/XCAGIMobile/DesignSystem/Theme.swift"
IOS_PERF = ROOT / "mobile-ios/XCAGIMobile/Observability/MobilePerformanceMonitor.swift"

HARMONY_PARITY = ROOT / "mobile-harmony/docs/PARITY_MATRIX.md"
HARMONY_TOKENS = ROOT / "mobile-harmony/entry/src/main/ets/design/DesignTokens.ets"
HARMONY_PERF = ROOT / "mobile-harmony/entry/src/main/ets/state/PerformanceMonitor.ets"

REQUIRED_DOC_SNIPPETS = (
    "唯一真相源",
    "Android 为主线",
    "KMM 可引入，但只共享网络层/模型层",
    "设计 token 统一",
    "性能监控统一指标名",
    "mobile.api.latency",
    "mobile.sse.first_token",
)

EXPECTED_COLOR_VALUES = {
    ("colors", "brand", "primary"): "#6366F1",
    ("colors", "brand", "primary_light"): "#818CF8",
    ("colors", "brand", "primary_dark"): "#4F46E5",
    ("colors", "status", "success"): "#10B981",
    ("colors", "status", "warning"): "#F59E0B",
    ("colors", "status", "danger"): "#EF4444",
}

EXPECTED_SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 20,
    "xxl": 24,
    "xxxl": 32,
}

EXPECTED_RADIUS = {
    "extra_small": 4,
    "small": 8,
    "medium": 12,
    "large": 16,
    "extra_large": 20,
}


def _read_text(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"缺少文件: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"缺少 JSON: {path.relative_to(ROOT)}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path.relative_to(ROOT)} JSON 无效: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path.relative_to(ROOT)} 顶层必须是 object")
        return {}
    return data


def _nested_get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _check_registry(errors: list[str]) -> None:
    domains = load_registry()
    domain = next((d for d in domains if d.get("name") == "mobile-tri-platform"), None)
    if not domain:
        errors.append("config/ssot.yaml 未登记 mobile-tri-platform 域")
        return
    if domain.get("ssot") != "FHD/docs/mobile_tri_platform_ssot.md":
        errors.append("mobile-tri-platform.ssot 必须指向 FHD/docs/mobile_tri_platform_ssot.md")
    if "mobile_tri_platform.py check" not in str(domain.get("check") or ""):
        errors.append("mobile-tri-platform.check 必须调用 mobile_tri_platform.py check")
    derived = set(domain.get("derived") or [])
    for rel in (
        "FHD/config/mobile_design_tokens.json",
        "FHD/mobile-ios/project.yml",
        "FHD/mobile-ios/XCAGIMobile/Observability/MobilePerformanceMonitor.swift",
        "FHD/mobile-harmony/entry/src/main/ets/design/DesignTokens.ets",
        "FHD/mobile-harmony/entry/src/main/ets/state/PerformanceMonitor.ets",
    ):
        if rel not in derived:
            errors.append(f"mobile-tri-platform.derived 缺少 {rel}")


def _check_doc(errors: list[str]) -> None:
    text = _read_text(MOBILE_SSOT_DOC, errors)
    if text:
        for snippet in REQUIRED_DOC_SNIPPETS:
            if snippet not in text:
                errors.append(f"mobile_tri_platform_ssot.md 缺少片段: {snippet}")

    index_text = _read_text(SSOT_INDEX, errors)
    if "mobile_tri_platform_ssot.md" not in index_text:
        errors.append("SSOT_INDEX.md 未登记 mobile_tri_platform_ssot.md")


def _check_tokens(errors: list[str]) -> None:
    data = _load_json(TOKENS, errors)
    if not data:
        return

    for path, expected in EXPECTED_COLOR_VALUES.items():
        got = _nested_get(data, path)
        if got != expected:
            errors.append(f"mobile_design_tokens.json {'.'.join(path)}={got!r}，应为 {expected!r}")

    spacing = data.get("spacing")
    if spacing != EXPECTED_SPACING:
        errors.append(f"mobile_design_tokens.json spacing={spacing!r}，应为 {EXPECTED_SPACING!r}")

    radius = data.get("radius")
    if radius != EXPECTED_RADIUS:
        errors.append(f"mobile_design_tokens.json radius={radius!r}，应为 {EXPECTED_RADIUS!r}")

    typography = data.get("typography")
    if not isinstance(typography, dict) or "display_large" not in typography or "label_small" not in typography:
        errors.append("mobile_design_tokens.json typography 缺少 display_large/label_small")


def _check_platform_files(errors: list[str]) -> None:
    android_theme = _read_text(ANDROID_THEME, errors)
    if android_theme and "Color(0xFF6366F1)" not in android_theme:
        errors.append("Android Theme.kt 未保留 token primary #6366F1")
    android_type = _read_text(ANDROID_TYPE, errors)
    if android_type and "displayLarge = TextStyle(fontSize = 28.sp" not in android_type:
        errors.append("Android Type.kt 未保留 displayLarge 28sp")
    android_shape = _read_text(ANDROID_SHAPE, errors)
    if android_shape and "val xl = 20.dp" not in android_shape:
        errors.append("Android Shape.kt 未保留 Spacing.xl = 20.dp")
    android_analytics = _read_text(ANDROID_ANALYTICS, errors)
    if android_analytics and "logPerformanceMetric" not in android_analytics:
        errors.append("Android XcagiAnalytics.kt 缺少 logPerformanceMetric")

    ios_parity = _read_text(IOS_PARITY, errors)
    if ios_parity and "对标 `mobile-android`" not in ios_parity:
        errors.append("iOS PARITY_MATRIX.md 未声明对标 mobile-android")
    ios_project_yml = _read_text(IOS_PROJECT_YML, errors)
    if ios_project_yml and "MetricKit/os.log" not in ios_project_yml:
        errors.append("iOS project.yml 未声明 MetricKit/os.log 系统框架")
    ios_theme = _read_text(IOS_THEME, errors)
    if ios_theme:
        for snippet in ("brandFallback = Color(red: 0.388", "static let xxxl: CGFloat = 32"):
            if snippet not in ios_theme:
                errors.append(f"iOS Theme.swift 缺少 token 片段: {snippet}")
    ios_perf = _read_text(IOS_PERF, errors)
    if ios_perf and ("MetricKit" not in ios_perf or "MXMetricManagerSubscriber" not in ios_perf):
        errors.append("iOS MobilePerformanceMonitor.swift 必须接 MetricKit")

    harmony_parity = _read_text(HARMONY_PARITY, errors)
    if harmony_parity and "对标 `mobile-android`" not in harmony_parity:
        errors.append("Harmony PARITY_MATRIX.md 未声明对标 mobile-android")
    harmony_tokens = _read_text(HARMONY_TOKENS, errors)
    if harmony_tokens and ("static readonly primary: string = '#6366F1'" not in harmony_tokens):
        errors.append("Harmony DesignTokens.ets 未保留 token primary #6366F1")
    harmony_perf = _read_text(HARMONY_PERF, errors)
    if harmony_perf and "mobile.api.latency" not in harmony_perf:
        errors.append("Harmony PerformanceMonitor.ets 缺少统一性能指标名")


def check_drift() -> int:
    errors: list[str] = []
    _check_registry(errors)
    _check_doc(errors)
    _check_tokens(errors)
    _check_platform_files(errors)

    if errors:
        print(f"mobile-tri-platform: {len(errors)} 处漂移", flush=True)
        for error in errors[:50]:
            print(f"  - {error}", flush=True)
        if len(errors) > 50:
            print(f"  ... 还有 {len(errors) - 50} 条", flush=True)
        return 1
    print("mobile-tri-platform: OK（Android 主线 / KMM 边界 / 三端 token / 性能监控入口一致）", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("mobile-tri-platform: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
