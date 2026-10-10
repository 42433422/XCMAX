"""能力中心证据原件：私有 COS 预签名跳转、白名单、哈希核验与站内回退。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import public_evidence_api as api

BUCKET = "xcagi-evidence-1374207682"
HOST = f"{BUCKET}.cos.ap-chengdu.myqcloud.com"
SHA = "a" * 64
KEY = "FHD/docs/evidence/e2e/demo/clip.webm"


@pytest.fixture()
def index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "evidence-index.json"
    path.write_text(
        json.dumps(
            {
                "assets": {
                    "demo-clip.webm": {"key": KEY, "sha256": SHA, "size": 1234, "source": KEY},
                    # 不在证据前缀下的键必须被拒绝，防止借索引签任意对象。
                    "evil.png": {
                        "key": "secrets/prod.env",
                        "sha256": SHA,
                        "size": 1,
                        "source": "x",
                    },
                    "../up.png": {"key": KEY, "sha256": SHA, "size": 1, "source": KEY},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XCMAX_EVIDENCE_INDEX_PATH", str(path))
    for name in ("BUCKET", "REGION", "SECRET_ID", "SECRET_KEY"):
        monkeypatch.delenv(f"XCMAX_EVIDENCE_COS_{name}", raising=False)
    api._VERIFY_CACHE.clear()
    return path


def _enable_cos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCMAX_EVIDENCE_COS_BUCKET", BUCKET)
    monkeypatch.setenv("XCMAX_EVIDENCE_COS_REGION", "ap-chengdu")
    monkeypatch.setenv("XCMAX_EVIDENCE_COS_SECRET_ID", "AKIDtestonly")
    monkeypatch.setenv("XCMAX_EVIDENCE_COS_SECRET_KEY", "secret-test-only")


def _mock_cos(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(api, "_transport", lambda: httpx.MockTransport(wrapped))
    return seen


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_signature_matches_official_sdk_vector() -> None:
    # 由 cos-python-sdk-v5 CosS3Auth 在固定时间下生成（含中文与空格键名）。
    auth = api.cos_authorization(
        "AKIDexample",
        "secretexample",
        "get",
        "FHD/docs/evidence/e2e/示例/a b.png",
        {"host": HOST},
        1759999940,
        1760001800,
    )
    assert auth.endswith("q-signature=2fbf1e08bfaaef64308c8d417a3de370e45c9a8c")
    assert "q-header-list=host" in auth


def test_unconfigured_cos_falls_back_to_local_copy(index: Path) -> None:
    resp = _client().get("/api/public/evidence/demo-clip.webm", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/capabilities/assets/evidence/demo-clip.webm"
    assert resp.headers["cache-control"] == "no-store"


def test_unregistered_or_unsafe_names_are_rejected(
    index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_cos(monkeypatch)
    seen = _mock_cos(monkeypatch, lambda r: httpx.Response(200))
    client = _client()
    assert client.get("/api/public/evidence/missing.png", follow_redirects=False).status_code == 404
    assert client.get("/api/public/evidence/evil.png", follow_redirects=False).status_code == 404
    assert client.get("/api/public/evidence/verify/evil.png").status_code == 404
    assert seen == []


def test_matching_object_redirects_to_short_lived_presigned_url(
    index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_cos(monkeypatch)
    monkeypatch.setenv("XCMAX_EVIDENCE_URL_TTL_SECONDS", "900")
    seen = _mock_cos(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            headers={"x-cos-meta-sha256": SHA, "content-length": "1234", "x-cos-version-id": "v1"},
        ),
    )
    client = _client()
    resp = client.get("/api/public/evidence/demo-clip.webm", follow_redirects=False)
    assert resp.status_code == 302
    loc = urlsplit(resp.headers["location"])
    assert loc.scheme == "https" and loc.netloc == HOST and loc.path == "/" + KEY
    assert "q-signature=" in loc.query and "q-ak=AKIDtestonly" in loc.query
    assert "secret-test-only" not in resp.headers["location"]
    start, end = [int(x) for x in loc.query.split("q-sign-time=")[1].split("&")[0].split(";")]
    assert end - start == 960  # 60 秒时钟偏差 + 900 秒有效期
    assert seen[0].method == "HEAD" and seen[0].headers["authorization"].startswith(
        "q-sign-algorithm=sha1"
    )

    # 第二次访问命中核验缓存，不再 HEAD。
    client.get("/api/public/evidence/demo-clip.webm", follow_redirects=False)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, headers={"x-cos-meta-sha256": "b" * 64, "content-length": "1234"}),
        httpx.Response(200, headers={"content-length": "1234"}),
        httpx.Response(200, headers={"x-cos-meta-sha256": SHA, "content-length": "99"}),
        httpx.Response(404),
    ],
)
def test_hash_mismatch_or_missing_object_serves_local_copy(
    index: Path, monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _enable_cos(monkeypatch)
    _mock_cos(monkeypatch, lambda r: response)
    client = _client()
    resp = client.get("/api/public/evidence/demo-clip.webm", follow_redirects=False)
    assert resp.headers["location"] == "/capabilities/assets/evidence/demo-clip.webm"
    verdict = client.get("/api/public/evidence/verify/demo-clip.webm").json()
    assert verdict["match"] is False and verdict["reason"]


def test_unreachable_cos_serves_local_copy(index: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_cos(monkeypatch)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    _mock_cos(monkeypatch, boom)
    resp = _client().get("/api/public/evidence/demo-clip.webm", follow_redirects=False)
    assert resp.headers["location"] == "/capabilities/assets/evidence/demo-clip.webm"


def test_verify_reports_index_and_object_metadata(
    index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_cos(monkeypatch)
    _mock_cos(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            headers={"x-cos-meta-sha256": SHA, "content-length": "1234", "x-cos-version-id": "v9"},
        ),
    )
    body = _client().get("/api/public/evidence/verify/demo-clip.webm").json()
    assert body["match"] is True
    assert body["expected_sha256"] == body["cos_sha256"] == SHA
    assert body["cos_size"] == 1234 and body["cos_version_id"] == "v9"


def test_status_never_exposes_credentials(index: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_cos(monkeypatch)
    resp = _client().get("/api/public/evidence/_status")
    text = resp.text
    assert resp.json()["cos_configured"] is True and resp.json()["index_assets"] == 1
    assert "secret-test-only" not in text and "AKIDtestonly" not in text


def test_committed_index_only_allows_evidence_media() -> None:
    """仓库内构建产物：每个条目都落在证据前缀下且为截图 / 录像。"""
    path = Path(__file__).resolve().parents[2] / "data" / "capabilities" / "evidence-index.json"
    assets = json.loads(path.read_text(encoding="utf-8"))["assets"]
    assert assets
    for name, entry in assets.items():
        assert api._valid_entry(name, entry), name
        assert (
            entry["key"]
            .lower()
            .endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".mov"))
        )
