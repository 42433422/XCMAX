#!/usr/bin/env python3
"""CI：校验 VERSION.md 表中的版本锚点与源码一致。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_MD = ROOT / "VERSION.md"

ANCHORS: list[tuple[str, Path, str]] = [
    ("Python 包（根）", ROOT / "pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    ("Python 包（XCAGI 子树）", ROOT / "XCAGI" / "pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    ("前端 SPA", ROOT / "frontend" / "package.json", r'"version"\s*:\s*"([^"]+)"'),
    ("桌面壳 npm", ROOT / "desktop" / "package.json", r'"version"\s*:\s*"([^"]+)"'),
    ("根级 npm", ROOT / "package.json", r'"version"\s*:\s*"([^"]+)"'),
    (
        "FastAPI 应用",
        ROOT / "app" / "fastapi_app" / "factory.py",
        r'version\s*=\s*"([^"]+)"',
    ),
    (
        "Mod 依赖校验基线",
        ROOT / "app" / "infrastructure" / "mods" / "manifest.py",
        r'current_version\s*=\s*"([^"]+)"',
    ),
]


def expected_version() -> str:
    text = VERSION_MD.read_text(encoding="utf-8")
    m = re.search(r"\*\*XCAGI 总版本\*\*.*?\|\s*`([^`]+)`", text)
    if not m:
        raise RuntimeError("cannot parse XCAGI 总版本 from VERSION.md")
    return m.group(1).strip()


def extract(pattern: str, content: str) -> str | None:
    for line in content.splitlines():
        m = re.search(pattern, line)
        if m:
            return m.group(1)
    return None


def _fastapi_factory_version(path: Path, want: str) -> str | None:
    content = path.read_text(encoding="utf-8")
    if "get_version()" not in content:
        return extract(r'version\s*=\s*"([^"]+)"', content)
    sys.path.insert(0, str(ROOT))
    try:
        from app.version import get_version

        return get_version()
    except Exception:
        return None


def main() -> int:
    if not VERSION_MD.is_file():
        print(f"Missing {VERSION_MD}", file=sys.stderr)
        return 2
    want = expected_version()
    errors: list[str] = []
    for label, path, pattern in ANCHORS:
        if not path.is_file():
            errors.append(f"{label}: missing file {path.relative_to(ROOT)}")
            continue
        if label == "FastAPI 应用":
            got = _fastapi_factory_version(path, want)
        else:
            got = extract(pattern, path.read_text(encoding="utf-8"))
        if got != want:
            errors.append(f"{label}: {path.relative_to(ROOT)} has {got!r}, want {want!r}")
    if errors:
        print("Version anchor drift:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"All anchors match VERSION.md ({want})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
