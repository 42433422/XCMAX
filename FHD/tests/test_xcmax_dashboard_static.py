from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_app.static_mounts import mount_xcmax_dashboard_static


def test_xcmax_dashboard_pytest_coverage_compat_falls_back_to_root_file(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "XCAGI-Full-Pipeline.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "xcmax-pytest-coverage.json").write_text('{"line_rate": 0.9}', encoding="utf-8")
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path))

    app = FastAPI()
    mount_xcmax_dashboard_static(app)

    r = TestClient(app).get("/xcmax-dashboard/.cache/xcmax/xcmax-pytest-coverage.json?v=20260604d")

    assert r.status_code == 200
    assert r.json() == {"line_rate": 0.9}
