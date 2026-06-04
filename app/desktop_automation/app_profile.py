"""加载 / 注册 AppProfile。"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.desktop_automation.models import AppProfile
from app.desktop_automation.paths import bundled_profiles_dir, profiles_dir

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, AppProfile] = {}


def _read_profile_file(path: Path) -> AppProfile | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = AppProfile.from_dict(data)
        if profile.app_id:
            return profile
    except Exception as exc:
        logger.warning("skip profile %s: %s", path, exc)
    return None


def _seed_bundled_profiles() -> None:
    bundled = bundled_profiles_dir()
    if not bundled.is_dir():
        return
    dest = profiles_dir()
    for src in bundled.glob("*.json"):
        target = dest / src.name
        if not target.exists():
            try:
                shutil.copy2(src, target)
            except Exception as exc:
                logger.warning("copy bundled profile %s failed: %s", src.name, exc)


def load_profile(app_id: str) -> AppProfile | None:
    _seed_bundled_profiles()
    if app_id in _REGISTRY:
        return _REGISTRY[app_id]
    for base in (profiles_dir(), bundled_profiles_dir()):
        path = base / f"{app_id}.json"
        if path.is_file():
            profile = _read_profile_file(path)
            if profile:
                _REGISTRY[app_id] = profile
                return profile
    return None


def list_profiles() -> list[AppProfile]:
    _seed_bundled_profiles()
    seen: set[str] = set()
    out: list[AppProfile] = []
    for base in (profiles_dir(), bundled_profiles_dir()):
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            profile = _read_profile_file(path)
            if profile and profile.app_id not in seen:
                seen.add(profile.app_id)
                _REGISTRY[profile.app_id] = profile
                out.append(profile)
    return out


def save_profile(profile: AppProfile) -> Path:
    path = profiles_dir() / f"{profile.app_id}.json"
    path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    _REGISTRY[profile.app_id] = profile
    return path


def register_profile(profile: AppProfile) -> None:
    save_profile(profile)
