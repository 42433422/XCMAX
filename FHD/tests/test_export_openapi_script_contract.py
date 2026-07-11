from __future__ import annotations

from pathlib import Path


def test_export_openapi_forces_full_route_registration_and_is_cwd_independent():
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "dev" / "export_openapi.py"
    ).read_text(encoding="utf-8")

    assert "sys.path.insert(0, str(FHD_ROOT))" in source
    assert 'os.environ["XCAGI_DESKTOP_FAST_START"] = "0"' in source
