"""Android 签约级交付文档契约（不发 APK，只验 SSOT）。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_android_marked_contract_grade_in_version_md() -> None:
    text = (ROOT / "VERSION.md").read_text(encoding="utf-8")
    assert "Android" in text
    assert "签约级" in text
    assert "非签约" not in text.split("Android")[1].split("\n")[0]


def test_mobile_android_readme_contract_grade() -> None:
    text = (ROOT / "mobile-android" / "README.md").read_text(encoding="utf-8")
    assert "签约级" in text
    assert "非签约级" not in text


def test_mobile_android_guide_exists() -> None:
    assert (ROOT / "docs" / "guides" / "MOBILE_ANDROID.md").is_file()


def test_android_version_anchor_in_gradle() -> None:
    import re

    gradle = (ROOT / "mobile-android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    version_md = (ROOT / "VERSION.md").read_text(encoding="utf-8")
    # v10 SSOT：Android 默认 versionName/versionCode 与 VERSION.md「XCAGI 总版本」锚点对齐。
    # versionCode/versionName 现可由 CI 注入(-PandroidVersionCode / env)以 stamp 真实递增版本;
    # 无注入时 versionName 必须回落到 v10 锚点；versionCode 可以是开发时间戳，
    # 但 Gradle 文件仍必须显式记录 VERSION.md 主版本锚点，避免 SSOT 漂移。
    m = re.search(r"\|\s*\*\*XCAGI 总版本\*\*\s*\|\s*`([^`]+)`", version_md)
    assert m, "VERSION.md missing XCAGI 总版本 row"
    want = m.group(1).strip()
    major = int(want.split(".")[0])
    assert (f'versionName = "{want}"' in gradle) or (f'?: "{want}"' in gradle), (
        "build.gradle versionName 默认必须锚定 VERSION.md 总版本"
    )
    assert (
        (f"versionCode = {major}" in gradle)
        or re.search(rf"\?:\s*{major}\b", gradle)
        or re.search(rf"ssotVersionCodeAnchor\s*=\s*{major}\b", gradle)
    ), (
        "build.gradle versionCode 默认必须锚定 VERSION.md 总版本主版本号"
    )
