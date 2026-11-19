"""HTTP regression tests for the optional legacy Flask website."""
from __future__ import annotations

import base64
import importlib.util
import io
import re
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

SITE_FILE = Path(__file__).resolve().parents[2] / "app.py"


@pytest.fixture
def site(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("xcmax_legacy_site_test", SITE_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DATA_FILE = tmp_path / "activities.json"
    module.NEWS_FILE = tmp_path / "news.json"
    module.UPLOAD_DIR = tmp_path / "uploads"
    module.app.config["TESTING"] = True
    monkeypatch.setenv("XC_SITE_ADMIN_USERNAME", "editor")
    monkeypatch.setenv(
        "XC_SITE_ADMIN_PASSWORD_HASH",
        generate_password_hash("test-password", method="pbkdf2:sha256:1000"),
    )
    return module


def _basic(password="test-password"):
    value = base64.b64encode(f"editor:{password}".encode()).decode()
    return {"Authorization": f"Basic {value}"}


def _csrf(client, path):
    response = client.get(path, headers=_basic())
    assert response.status_code == 200
    match = re.search(r'name="_csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match
    return match.group(1)


def test_admin_routes_fail_closed_without_configuration(site, monkeypatch):
    monkeypatch.delenv("XC_SITE_ADMIN_PASSWORD_HASH")
    with site.app.test_client() as client:
        assert client.get("/admin").status_code == 503
        assert client.get("/admin/news").status_code == 503
        assert client.post("/admin/news", data={"title": "no", "summary": "no"}).status_code == 503
    assert not site.NEWS_FILE.exists()


def test_management_requires_basic_auth_and_disables_caching(site):
    with site.app.test_client() as client:
        for path in ("/admin", "/admin/news"):
            assert client.get(path).status_code == 401
            assert client.get(path, headers=_basic("wrong")).status_code == 401
            response = client.get(path, headers=_basic())
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["Vary"] == "Authorization"
            assert '_csrf_token' in response.get_data(as_text=True)


def test_news_post_requires_route_scoped_csrf(site):
    with site.app.test_client() as client:
        news_token = _csrf(client, "/admin/news")
        activities_token = _csrf(client, "/admin")
        payload = {"title": "News", "summary": "Details"}
        assert client.post("/admin/news", data=payload, headers=_basic()).status_code == 403
        assert client.post(
            "/admin/news", data={**payload, "_csrf_token": activities_token}, headers=_basic()
        ).status_code == 403
        assert not site.NEWS_FILE.exists()
        result = client.post(
            "/admin/news", data={**payload, "_csrf_token": news_token}, headers=_basic()
        )
        assert result.status_code == 302
        assert site.load_news()[0]["title"] == "News"


@pytest.mark.parametrize(
    "filename,payload",
    [
        ("payload.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"),
        ("payload.html", b"<h1>content</h1>"),
        ("fake.png", b"<html>not a PNG</html>"),
        ("fake.jpg", b"not a JPEG"),
    ],
)
def test_activity_rejects_active_and_disguised_uploads(site, filename, payload):
    with site.app.test_client() as client:
        token = _csrf(client, "/admin")
        response = client.post(
            "/admin",
            data={
                "title": "Activity",
                "description": "Details",
                "_csrf_token": token,
                "image": (io.BytesIO(payload), filename),
            },
            headers=_basic(),
            content_type="multipart/form-data",
        )
        assert response.status_code == 415
        assert site.load_activities() == []
        assert not list(site.UPLOAD_DIR.iterdir())


def test_valid_bitmap_upload_and_legacy_svg_are_sandboxed(site):
    with site.app.test_client() as client:
        token = _csrf(client, "/admin")
        response = client.post(
            "/admin",
            data={
                "title": "Activity",
                "description": "Details",
                "_csrf_token": token,
                "image": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32), "safe.png"),
            },
            headers=_basic(),
            content_type="multipart/form-data",
        )
        assert response.status_code == 302
        record = site.load_activities()[0]
        served = client.get(record["image"])
        assert served.status_code == 200
        assert served.headers["X-Content-Type-Options"] == "nosniff"
        assert served.headers["Content-Security-Policy"] == "sandbox"

        (site.UPLOAD_DIR / "old.svg").write_text("<svg><script>0</script></svg>")
        old = client.get("/uploads/old.svg")
        assert old.status_code == 200
        assert old.headers["Content-Security-Policy"] == "sandbox"
