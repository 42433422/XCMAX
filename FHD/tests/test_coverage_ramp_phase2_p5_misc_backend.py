"""COVERAGE_RAMP Phase 2 (p2-p5): misc helpers, mods package hash, neuro_bus domain base,
application session_account_meta, infrastructure mods manifest parse."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.application.session_account_meta import (
    company_brand_from_user_blob,
    normalize_account_kind,
)
from app.fastapi_routes.domains.misc.helpers import (
    _http_exception_to_json,
    _message_to_dict,
    _session_to_dict,
)
from app.infrastructure.mods.manifest import parse_manifest
from app.infrastructure.mods.package import compute_directory_hash, compute_file_hash
from app.neuro_bus.domains.base import DomainChannel, DomainHandler


def _http_request(**headers: str) -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": hdrs,
        "query_string": b"",
        "client": ("10.0.0.1", 8080),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# misc helpers
# ---------------------------------------------------------------------------


def test_http_exception_to_json_dict_detail() -> None:
    resp = _http_exception_to_json(HTTPException(status_code=400, detail={"message": "bad"}))
    assert resp.status_code == 400


def test_http_exception_to_json_string_detail() -> None:
    resp = _http_exception_to_json(HTTPException(status_code=401, detail="unauthorized"))
    body = json.loads(resp.body)
    assert body["message"] == "unauthorized"


@pytest.mark.parametrize(
    "session,expected_title",
    [
        ({"session_id": "s1", "user_id": "u1", "title": "聊天"}, "聊天"),
        (("x", "s2", "u2", None, "", 0, None, None), "新会话"),
    ],
)
def test_session_to_dict_shapes(session, expected_title: str) -> None:
    out = _session_to_dict(session)
    assert out["title"] == expected_title


@pytest.mark.parametrize(
    "message,role",
    [
        ({"id": 1, "role": "user", "content": "hi"}, "user"),
        ((1, "s", "u", "assistant", "hello", "", "", None), "assistant"),
    ],
)
def test_message_to_dict_shapes(message, role: str) -> None:
    out = _message_to_dict(message)
    assert out["role"] == role


# ---------------------------------------------------------------------------
# mods package + manifest
# ---------------------------------------------------------------------------


def test_compute_file_hash(tmp_path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    h1 = compute_file_hash(str(f))
    h2 = compute_file_hash(str(f))
    assert h1 == h2
    assert len(h1) == 64


def test_compute_directory_hash(tmp_path) -> None:
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("c", encoding="utf-8")
    h = compute_directory_hash(str(tmp_path))
    assert len(h) == 64


def test_parse_manifest_missing_returns_none(tmp_path) -> None:
    assert parse_manifest(str(tmp_path / "missing")) is None


def test_parse_manifest_valid(tmp_path) -> None:
    mod_dir = tmp_path / "demo-mod"
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "demo-mod",
                "name": "Demo",
                "version": "1.0.0",
                "entry": "backend/main.py",
            }
        ),
        encoding="utf-8",
    )
    meta = parse_manifest(str(mod_dir))
    assert meta is not None
    assert meta.id == "demo-mod"


# ---------------------------------------------------------------------------
# neuro_bus domain base
# ---------------------------------------------------------------------------


def test_domain_channel_enum() -> None:
    assert DomainChannel.FAST.value == "fast"
    assert DomainChannel.RELIABLE.value == "reliable"


def test_domain_handler_dataclass() -> None:
    handler = DomainHandler(event_type="test.e", handler=lambda e: None)
    assert handler.event_type == "test.e"
    assert handler.channel == DomainChannel.STANDARD


# ---------------------------------------------------------------------------
# session_account_meta
# ---------------------------------------------------------------------------


def test_normalize_account_kind_defaults() -> None:
    assert normalize_account_kind(None) == "enterprise"
    assert normalize_account_kind("personal") == "personal"


def test_company_brand_from_user_blob() -> None:
    assert company_brand_from_user_blob({"company": "七彩"}) == "七彩"
    assert company_brand_from_user_blob({}) == ""
