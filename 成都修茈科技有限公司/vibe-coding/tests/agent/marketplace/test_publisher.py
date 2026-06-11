"""Tests for :class:`MODstoreClient` + :class:`SkillPublisher`.

The HTTP layer is exercised with a stub ``urllib.request.urlopen`` so we
don't need a running MODstore. Only the contract — request shape, auth
header, JSON parsing — is verified here. End-to-end tests live in the
deployment repo.
"""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from vibe_coding._internals import (
    CodeFunctionSignature,
    CodeSkill,
    CodeSkillVersion,
)
from vibe_coding.agent.marketplace import (
    MODstoreAuthError,
    MODstoreClient,
    MODstoreError,
    PackagingError,
    PublishOptions,
    SkillPublisher,
)


# --------------------------------------------------------------- shared fixtures


@pytest.fixture
def sample_skill() -> CodeSkill:
    sig = CodeFunctionSignature(
        params=["text"], return_type="dict", required_params=["text"]
    )
    return CodeSkill(
        skill_id="reverse_string",
        name="Reverse String",
        domain="text",
        active_version=1,
        versions=[
            CodeSkillVersion(
                version=1,
                source_code="def run(text):\n    return {'r': text[::-1]}\n",
                function_name="run",
                signature=sig,
            )
        ],
    )


# -------------------------------------------------------------------- stubs


class _FakeResponse:
    def __init__(self, body: str | bytes, status: int = 200) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


@contextmanager
def _patched_urlopen(handler):
    """``handler(req) -> _FakeResponse``; called for each ``urlopen``."""
    captured: list[Any] = []

    def fake_urlopen(req, timeout=None, context=None):  # noqa: ARG001
        captured.append(req)
        return handler(req)

    with patch("urllib.request.urlopen", fake_urlopen):
        yield captured


# ----------------------------------------------------------------- client


def test_client_login_stores_access_token() -> None:
    def handler(req):
        assert req.full_url.endswith("/api/auth/login")
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"username": "alice", "password": "secret"}
        return _FakeResponse(json.dumps({"ok": True, "access_token": "tok-abc"}))

    client = MODstoreClient(base_url="https://m.example.com")
    with _patched_urlopen(handler):
        token = client.login("alice", "secret")
    assert token == "tok-abc"
    assert client.access_token == "tok-abc"


def test_client_login_raises_auth_error_on_401() -> None:
    import urllib.error

    def handler(req):
        raise urllib.error.HTTPError(
            req.full_url,
            401,
            "Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"detail":"bad password"}'),
        )

    client = MODstoreClient(base_url="https://m.example.com")
    with pytest.raises(MODstoreAuthError):
        with _patched_urlopen(handler):
            client.login("alice", "wrong")


def test_upload_catalog_sends_multipart(tmp_path: Path) -> None:
    archive = tmp_path / "demo-1.xcmod"
    archive.write_bytes(b"PK\x03\x04stub-archive-data")

    seen_payload: dict[str, Any] = {}

    def handler(req):
        ct = req.headers.get("Content-type") or req.headers.get("Content-Type") or ""
        seen_payload["content_type"] = ct
        seen_payload["auth"] = (
            req.headers.get("Authorization") or req.headers.get("authorization")
        )
        seen_payload["body_starts_with"] = bytes(req.data)[:120]
        return _FakeResponse(
            json.dumps(
                {
                    "ok": True,
                    "id": 42,
                    "pkg_id": "demo",
                    "stored_filename": "demo-1.xcmod",
                }
            )
        )

    client = MODstoreClient(base_url="https://m.example.com", access_token="t")
    with _patched_urlopen(handler):
        result = client.upload_catalog(
            archive,
            pkg_id="demo",
            version="1",
            name="Demo",
            description="d",
            price=0,
        )
    assert result.item_id == 42
    assert result.pkg_id == "demo"
    assert result.stored_filename == "demo-1.xcmod"
    assert seen_payload["content_type"].startswith("multipart/form-data; boundary=")
    assert seen_payload["auth"] == "Bearer t"
    # Boundary marker plus our pkg_id field appear early in the multipart body.
    assert b"name=\"pkg_id\"" in seen_payload["body_starts_with"]


def test_upload_requires_token() -> None:
    client = MODstoreClient(base_url="https://m.example.com")
    with pytest.raises(MODstoreAuthError):
        client.upload_catalog(
            Path("/non/existent.xcmod"),
            pkg_id="x",
            version="1",
            name="x",
        )


def test_upload_rejects_oversize(tmp_path: Path) -> None:
    """Force the size guard via a stub ``Path.stat`` that reports >100 MiB."""

    class _BigStat:
        st_size = 200 * 1024 * 1024
        st_mode = 0o100644  # regular-file mode, so ``is_file()`` stays true

    big = tmp_path / "big.xcmod"
    big.write_bytes(b"\x00" * 10)

    real_stat = Path.stat

    def fake_stat(self, *, follow_symlinks=True):  # noqa: ARG001
        if self == big:
            return _BigStat()
        return real_stat(self, follow_symlinks=follow_symlinks)

    client = MODstoreClient(base_url="https://m.example.com", access_token="t")
    with patch.object(Path, "stat", fake_stat):
        with pytest.raises(MODstoreError):
            client.upload_catalog(big, pkg_id="x", version="1", name="x")


def test_list_catalog_round_trips() -> None:
    payload = {"items": [{"id": 1, "pkg_id": "x"}], "total": 1}

    def handler(req):
        assert "/api/admin/catalog" in req.full_url
        assert req.headers.get("Authorization") == "Bearer t"
        return _FakeResponse(json.dumps(payload))

    client = MODstoreClient(base_url="https://m.example.com", access_token="t")
    with _patched_urlopen(handler):
        out = client.list_catalog(limit=10, offset=0)
    assert out == payload


# ----------------------------------------------------------------- publisher


def test_publisher_dry_run_skips_network(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    publisher = SkillPublisher.from_token(
        base_url="https://m.example.com", admin_token="t"
    )

    def handler(req):  # noqa: ARG001
        raise AssertionError("dry_run should not call out to the network")

    with _patched_urlopen(handler):
        result = publisher.publish_skill(
            sample_skill,
            options=PublishOptions(output_dir=tmp_path),
            dry_run=True,
        )
    assert result.dry_run is True
    assert result.upload is None
    assert result.published is False
    assert result.artifact.archive_path.exists()


def test_publisher_publishes_on_real_call(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    publisher = SkillPublisher.from_token(
        base_url="https://m.example.com", admin_token="t"
    )

    def handler(req):
        return _FakeResponse(
            json.dumps(
                {
                    "ok": True,
                    "id": 7,
                    "pkg_id": "vc-reverse-string",
                    "stored_filename": "vc-reverse-string-1.0.1.xcmod",
                }
            )
        )

    with _patched_urlopen(handler):
        result = publisher.publish_skill(
            sample_skill,
            options=PublishOptions(output_dir=tmp_path, price=0.0),
        )
    assert result.published is True
    assert result.upload is not None
    assert result.upload.item_id == 7


def test_publisher_publish_workflow_requires_pkg_id(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    publisher = SkillPublisher.from_token(
        base_url="https://m.example.com", admin_token="t"
    )
    with pytest.raises(PackagingError):
        publisher.publish_workflow(
            [sample_skill],
            options=PublishOptions(output_dir=tmp_path),
            dry_run=True,
        )


def test_publisher_records_error_on_http_failure(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    import urllib.error

    publisher = SkillPublisher.from_token(
        base_url="https://m.example.com", admin_token="t"
    )

    def handler(req):
        raise urllib.error.HTTPError(
            req.full_url,
            409,
            "Conflict",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b"already exists"),
        )

    with _patched_urlopen(handler):
        result = publisher.publish_skill(
            sample_skill,
            options=PublishOptions(output_dir=tmp_path),
        )
    assert result.published is False
    assert "409" in result.error
