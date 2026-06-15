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
    # v10 SSOT：Android versionName 与 VERSION.md「XCAGI 总版本」锚点对齐（非独立 APK 行）。
    m = re.search(r"\|\s*\*\*XCAGI 总版本\*\*\s*\|\s*`([^`]+)`", version_md)
    assert m, "VERSION.md missing XCAGI 总版本 row"
    want = m.group(1).strip()
    assert f'versionName = "{want}"' in gradle
    assert f'versionCode = {int(want.split(".")[0])}' in gradle
