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


def _basic(password="test-password", *, username="editor"):
    value = base64.b64encode(f"{username}:{password}".encode()).decode()
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


@pytest.mark.parametrize("configured,supplied,expected", [("管理员", "管理员", 200), ("editor", "管理员", 401)])
def test_admin_usernames_support_utf8(site, monkeypatch, configured, supplied, expected):
    monkeypatch.setenv("XC_SITE_ADMIN_USERNAME", configured)
    with site.app.test_client() as client:
        for path in ("/admin", "/admin/news"):
            assert client.get(path, headers=_basic(username=supplied)).status_code == expected


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


def test_proxy_failure_does_not_expose_upstream_exception(site, monkeypatch, caplog):
    private_detail = (
        "http://operator:private-password@internal.invalid/api?token=private-token"
    )

    def unavailable(*_args, **_kwargs):
        raise site.requests.ConnectionError(private_detail)

    monkeypatch.setattr(site.requests, "request", unavailable)
    with site.app.test_client() as client:
        response = client.get("/api/private", headers={"Origin": "https://xiu-ci.com"})
    assert response.status_code == 502
    assert response.json == {"detail": "服务暂时不可用，请稍后重试。"}
    assert response.headers["Access-Control-Allow-Origin"] == "https://xiu-ci.com"
    assert "ConnectionError" in caplog.text
    assert private_detail not in caplog.text
    assert "private-password" not in response.get_data(as_text=True)


def _upstream_response(site, headers, *, status=200):
    upstream = site.requests.Response()
    upstream.status_code = status
    upstream.raw = io.BytesIO(b"upstream payload")
    upstream.headers.update(headers)
    return upstream


@pytest.mark.parametrize(
    "name,value",
    [
        ("X-Unsafe\r\nSet-Cookie", "injected=1"),
        ("X-Unsafe: Set-Cookie", "injected=1"),
        ("X Unsafe", "injected=1"),
        ("Location", "/safe\r\nSet-Cookie: injected=1"),
        ("Location", "/safe\nX-Injected: yes"),
        ("X-Unsafe", "hidden\x00value"),
    ],
)
def test_proxy_rejects_malformed_response_headers(site, monkeypatch, name, value):
    upstream = _upstream_response(site, {name: value, "X-Upstream-Safe": "kept"})
    monkeypatch.setattr(site.requests, "request", lambda *_args, **_kwargs: upstream)
    with site.app.test_client() as client:
        response = client.get("/api/proxy-header-check")
        assert response.data == b"upstream payload"
    assert name not in response.headers
    assert "Set-Cookie" not in response.headers
    assert response.headers["X-Upstream-Safe"] == "kept"


def test_proxy_preserves_payment_redirect_and_auth_headers(site, monkeypatch):
    location = "xcagi://payment/complete?order_id=public-order&result=success"
    upstream = _upstream_response(
        site,
        {
            "Location": location,
            "Set-Cookie": "session=public-test; HttpOnly; Secure; SameSite=Lax",
            "Content-Type": "text/plain",
            "Connection": "close",
            "Content-Length": "999",
            "Access-Control-Allow-Origin": "https://untrusted.invalid",
        },
        status=307,
    )
    calls = []

    def forward(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return upstream

    monkeypatch.setattr(site.requests, "request", forward)
    with site.app.test_client() as client:
        response = client.post(
            "/api/payment/complete?order=public-order",
            data=b"payment body",
            headers={
                "Authorization": "Bearer public-test",
                "Origin": "https://xiu-ci.com",
            },
        )
        assert response.data == b"upstream payload"
    assert response.status_code == 307
    assert response.headers["Location"] == location
    assert response.headers["Set-Cookie"].startswith("session=public-test;")
    assert response.headers["Access-Control-Allow-Origin"] == "https://xiu-ci.com"
    assert "Connection" not in response.headers
    assert "Content-Length" not in response.headers
    assert len(calls) == 1
    method, url, options = calls[0]
    assert method == "POST" and url.endswith("/api/payment/complete?order=public-order")
    assert options["allow_redirects"] is False
    assert options["headers"]["Authorization"] == "Bearer public-test"
    assert options["data"] == b"payment body"
