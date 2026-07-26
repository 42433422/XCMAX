"""Flutter Android 签约级交付契约（不发 APK，只验 SSOT）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_android_marked_contract_grade_in_version_md() -> None:
    text = (ROOT / "VERSION.md").read_text(encoding="utf-8")
    assert "Android" in text
    assert "签约级" in text
    assert "非签约" not in text.split("Android")[1].split("\n")[0]


def test_flutter_mobile_readme_declares_only_delivery_line() -> None:
    text = (ROOT / "mobile-flutter-poc" / "README.md").read_text(encoding="utf-8")
    assert "唯一移动端实现与交付主线" in text
    assert "Android + iOS 单代码库" in text


def test_mobile_android_guide_exists() -> None:
    assert (ROOT / "docs" / "guides" / "MOBILE_ANDROID.md").is_file()


def test_android_version_anchor_in_gradle() -> None:
    import re

    gradle = (ROOT / "mobile-flutter-poc" / "android" / "app" / "build.gradle.kts").read_text(
        encoding="utf-8"
    )
    version_md = (ROOT / "VERSION.md").read_text(encoding="utf-8")
    # versionName 跟随四段产品版本；versionCode 是商店要求的独立单调递增构建号，
    # 不得因产品版本从历史 10.0.0 切到 1.0.0.0 而倒退或强行映射主版本号。
    m = re.search(r"\|\s*\*\*XCAGI 稳定产品版本\*\*\s*\|\s*`([^`]+)`", version_md)
    assert m, "VERSION.md missing XCAGI 稳定产品版本 row"
    want = m.group(1).strip()
    assert (f'versionName = "{want}"' in gradle) or (f'?: "{want}"' in gradle), (
        "build.gradle versionName 默认必须锚定 VERSION.md 稳定产品版本"
    )
    anchor = re.search(r"ssotVersionCodeAnchor\s*=\s*(\d+)", gradle)
    assert anchor and int(anchor.group(1)) > 0, "Android versionCode anchor 必须为正整数"
