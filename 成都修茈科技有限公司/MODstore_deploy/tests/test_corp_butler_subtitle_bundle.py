"""Published corp-butler bundle must not render karaoke context lines."""

from __future__ import annotations

from pathlib import Path

SITE = Path(__file__).resolve().parents[2]
BUNDLE_JS = SITE / "corp-butler" / "corp-butler.js"
BUNDLE_CSS = SITE / "corp-butler" / "corp-butler.css"


def test_published_subtitle_overlay_is_current_line_only():
    js = BUNDLE_JS.read_text(encoding="utf-8")
    css = BUNDLE_CSS.read_text(encoding="utf-8")
    assert "tts-sub__line--cur" in js
    assert "tts-sub__line--prev" not in js
    assert "tts-sub__line--next" not in js
    assert "tts-sub__line--prev" not in css
    assert "tts-sub__line--next" not in css
    assert "朗读字幕" in js
    assert "关闭字幕" in js
    assert "tts-sub__zh" in js
    # 旧口播模板会把页面标题嵌进「你现在在「…」」。清洗正则本身不含这个引号写法。
    assert "你现在在「" not in js
    assert "这页重点：" not in js
