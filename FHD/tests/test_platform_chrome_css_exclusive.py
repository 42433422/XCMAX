"""Shared CSS must not ship both mac and win chrome selectors (#1)."""

from __future__ import annotations

from pathlib import Path


from app.fastapi_app import static_mounts
from app.fastapi_routes import spa_fallback

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PLATFORM = FRONTEND / "public" / "platform"
SHARED_STYLE_GLOBS = (
    "src/styles/**/*.css",
    "src/views/**/*.css",
    "src/components/**/*.{css,vue}",
)


def _iter_shared_style_files() -> list[Path]:
    files: list[Path] = []
    for pattern in SHARED_STYLE_GLOBS:
        files.extend(FRONTEND.glob(pattern))
    return sorted({p for p in files if p.is_file()})


def test_shared_styles_do_not_embed_platform_chrome_classes() -> None:
    offenders: list[str] = []
    for path in _iter_shared_style_files():
        text = path.read_text(encoding="utf-8")
        # Vue script may still query classList; only flag style blocks / plain CSS.
        if path.suffix == ".vue":
            lower = text.lower()
            style_start = lower.find("<style")
            if style_start < 0:
                continue
            text = text[style_start:]
        if "xcagi-electron-mac" in text or "xcagi-electron-win" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"platform chrome classes leaked into shared styles: {offenders}"


def test_platform_chrome_stylesheets_are_exclusive() -> None:
    mac = (PLATFORM / "electron-mac.css").read_text(encoding="utf-8")
    win = (PLATFORM / "electron-win.css").read_text(encoding="utf-8")
    assert "xcagi-electron-mac" in mac
    assert "xcagi-electron-win" not in mac
    assert "xcagi-electron-win" in win
    assert "xcagi-electron-mac" not in win


def test_platform_public_dir_is_mounted_and_spa_excluded() -> None:
    src = Path(static_mounts.__file__).read_text(encoding="utf-8")
    assert '"platform"' in src or "'platform'" in src
    assert "platform/" in spa_fallback._EXCLUDED_PREFIXES
