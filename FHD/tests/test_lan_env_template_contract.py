from __future__ import annotations

from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[1]


def _env_value(path: Path, name: str) -> str | None:
    prefix = f"{name}="
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def test_lan_guard_defaults_off_for_development_and_on_for_production():
    assert _env_value(FHD_ROOT / ".env.example", "LAN_GUARD_ENABLED") == "0"
    assert _env_value(FHD_ROOT / ".env.production.example", "LAN_GUARD_ENABLED") == "1"


def test_production_template_requires_distinct_lan_bootstrap_material():
    production = FHD_ROOT / ".env.production.example"
    assert _env_value(production, "LAN_LICENSE_SECRET") == ""
    assert _env_value(production, "LAN_ADMIN_BOOTSTRAP_KEY") == ""
    assert _env_value(production, "LAN_COOKIE_SECURE") == "1"
