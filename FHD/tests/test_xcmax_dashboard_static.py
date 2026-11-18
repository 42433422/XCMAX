from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_app.static_mounts import mount_xcmax_dashboard_static


def test_xcmax_dashboard_pytest_coverage_compat_falls_back_to_root_file(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "XCAGI-Full-Pipeline.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "xcmax-pytest-coverage.json").write_text('{"line_rate": 0.9}', encoding="utf-8")
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")

    app = FastAPI()
    mount_xcmax_dashboard_static(app)

    r = TestClient(app).get("/xcmax-dashboard/.cache/xcmax/xcmax-pytest-coverage.json?v=20260604d")

    assert r.status_code == 200
    assert r.json() == {"line_rate": 0.9}


@pytest.fixture
def dashboard(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "XCAGI-Full-Pipeline.html").write_text("<html>dashboard</html>")
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(root))
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    app = FastAPI()
    mount_xcmax_dashboard_static(app)
    with TestClient(app) as client:
        yield client, root


@pytest.mark.parametrize(
    "path",
    [
        "XCAGI-Full-Pipeline.html",
        "XCAGI-Five-Line.html",
        "docs/xcagi-dashboard/app.js",
        "docs/xcagi-dashboard/dashboard.css",
        "docs/xcagi-dashboard/vendor/dagre.min.js",
        "FHD/config/six_line_employee_map.json",
        ".cache/xcmax/xcmax-tree-data.json",
        "FHD/docs/evidence/mod/01-listing.png",
    ],
)
def test_dashboard_public_assets_remain_available(dashboard, path):
    client, root = dashboard
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"public dashboard fixture")
    response = client.get(f"/xcmax-dashboard/{path}?v=cache-key")
    assert response.status_code == 200
    assert response.content == b"public dashboard fixture"


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".git/config",
        "FHD/app/config.py",
        "FHD/data/accounts.sqlite",
        "uploads/customer.xlsx",
        "downloads/customer.csv",
        "private.json",
        "docs/xcagi-dashboard/private.json",
        "docs/xcagi-dashboard/vendor/private.js",
        ".cache/xcmax/private.json",
        "FHD/config/private.json",
        "FHD/docs/evidence/mod/private.png",
    ],
)
def test_dashboard_never_publishes_unlisted_repository_files(dashboard, path):
    client, root = dashboard
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"synthetic private fixture")
    response = client.get(f"/xcmax-dashboard/{path}")
    assert response.status_code == 404
    assert b"synthetic private fixture" not in response.content


@pytest.mark.parametrize(
    "path",
    [
        "docs/xcagi-dashboard/%2e%2e/%2e%2e/.env",
        "docs%2f..%2f.env",
        "docs%5c..%5c.env",
        "%2e%2e/repo-sibling/private.json",
        "docs/xcagi-dashboard/../../FHD/data/accounts.sqlite",
    ],
)
def test_dashboard_encoded_and_sibling_paths_cannot_escape(dashboard, path):
    client, root = dashboard
    (root / ".env").write_text("synthetic private fixture")
    sibling = root.parent / "repo-sibling"
    sibling.mkdir()
    (sibling / "private.json").write_text("synthetic sibling fixture")
    assert client.get(f"/xcmax-dashboard/{path}").status_code == 404


@pytest.mark.parametrize("outside", [False, True])
@pytest.mark.parametrize("directory_link", [False, True])
def test_dashboard_rejects_symlinks_even_within_the_repository(dashboard, outside, directory_link):
    client, root = dashboard
    secret_dir = (root.parent if outside else root) / "private"
    secret_dir.mkdir()
    secret = secret_dir / "app.js"
    secret.write_text("synthetic private fixture")
    assets = root / "docs/xcagi-dashboard"
    assets.parent.mkdir()
    if directory_link:
        assets.symlink_to(secret_dir, target_is_directory=True)
    else:
        assets.mkdir()
        (assets / "app.js").symlink_to(secret)
    assert client.get("/xcmax-dashboard/docs/xcagi-dashboard/app.js").status_code == 404


def test_dashboard_coverage_compat_cannot_follow_symlinks(dashboard):
    client, root = dashboard
    secret = root / "private.json"
    secret.write_text('{"synthetic_private": true}')
    (root / "xcmax-pytest-coverage.json").symlink_to(secret)
    response = client.get("/xcmax-dashboard/.cache/xcmax/xcmax-pytest-coverage.json")
    assert response.status_code == 404
    assert "synthetic_private" not in response.text
