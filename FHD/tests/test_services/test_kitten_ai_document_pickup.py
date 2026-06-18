"""Tests for app.services.kitten_ai_document.pickup — document pickup store/pop."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.kitten_ai_document.pickup import (
    _pickup_base_dir,
    _prune_disk,
    _sanitize_token,
    pop_document_pickup,
    store_document_pickup,
)

# ---------------------------------------------------------------------------
# _sanitize_token
# ---------------------------------------------------------------------------


class TestSanitizeToken:
    def test_valid_token(self):
        assert _sanitize_token("abc123XYZ") == "abc123XYZ"

    def test_valid_with_underscore_hyphen(self):
        assert _sanitize_token("abc_123-XYZ") == "abc_123-XYZ"

    def test_strips_whitespace(self):
        assert _sanitize_token("  abc  ") == "abc"

    def test_rejects_path_traversal(self):
        assert _sanitize_token("../etc/passwd") is None

    def test_rejects_absolute_path(self):
        assert _sanitize_token("/etc/passwd") is None

    def test_rejects_backslash(self):
        assert _sanitize_token("dir\\file") is None

    def test_empty_string(self):
        assert _sanitize_token("") is None

    def test_none_returns_none(self):
        assert _sanitize_token(None) is None

    def test_too_long_token(self):
        assert _sanitize_token("a" * 129) is None


# ---------------------------------------------------------------------------
# _pickup_base_dir
# ---------------------------------------------------------------------------


class TestPickupBaseDir:
    def test_returns_writable_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"KITTEN_PICKUP_DIR": tmp}):
                # Reset cached value
                import app.services.kitten_ai_document.pickup as mod

                mod._CACHED_BASE = None
                result = _pickup_base_dir()
            assert isinstance(result, Path)
            assert result.exists()
            mod._CACHED_BASE = None

    def test_fallback_to_temp(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITTEN_PICKUP_DIR", None)
            os.environ.pop("WORKSPACE_ROOT", None)
            import app.services.kitten_ai_document.pickup as mod

            mod._CACHED_BASE = None
            result = _pickup_base_dir()
            assert isinstance(result, Path)
            mod._CACHED_BASE = None


# ---------------------------------------------------------------------------
# _prune_disk
# ---------------------------------------------------------------------------


class TestPruneDisk:
    def test_removes_expired_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # Create an expired entry
            expired_dir = base / "expired_tok"
            expired_dir.mkdir()
            meta = {"ts": time.time() - 99999, "file_name": "old.bin", "mime": "text/plain"}
            (expired_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            (expired_dir / "data.bin").write_bytes(b"old data")

            _prune_disk(base)
            assert not expired_dir.exists()

    def test_keeps_fresh_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fresh_dir = base / "fresh_tok"
            fresh_dir.mkdir()
            meta = {"ts": time.time(), "file_name": "new.bin", "mime": "text/plain"}
            (fresh_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            (fresh_dir / "data.bin").write_bytes(b"new data")

            _prune_disk(base)
            assert fresh_dir.exists()


# ---------------------------------------------------------------------------
# store_document_pickup / pop_document_pickup
# ---------------------------------------------------------------------------


class TestStoreAndPopDocumentPickup:
    def test_store_and_pop_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"KITTEN_PICKUP_DIR": tmp}):
                import app.services.kitten_ai_document.pickup as mod

                mod._CACHED_BASE = None

                content = b"hello world document"
                token = store_document_pickup(content, "report.pdf", "application/pdf")
                assert isinstance(token, str)
                assert len(token) > 0

                result = pop_document_pickup(token)
                assert result is not None
                popped_content, fname, mime = result
                assert popped_content == content
                assert fname == "report.pdf"
                assert mime == "application/pdf"

                mod._CACHED_BASE = None

    def test_pop_nonexistent_token_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"KITTEN_PICKUP_DIR": tmp}):
                import app.services.kitten_ai_document.pickup as mod

                mod._CACHED_BASE = None

                result = pop_document_pickup("nonexistent_token_12345")
                assert result is None

                mod._CACHED_BASE = None

    def test_pop_empty_token_returns_none(self):
        result = pop_document_pickup("")
        assert result is None

    def test_pop_invalid_token_returns_none(self):
        result = pop_document_pickup("../../etc/passwd")
        assert result is None

    def test_pop_twice_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"KITTEN_PICKUP_DIR": tmp}):
                import app.services.kitten_ai_document.pickup as mod

                mod._CACHED_BASE = None

                token = store_document_pickup(b"data", "f.txt", "text/plain")
                result1 = pop_document_pickup(token)
                assert result1 is not None
                result2 = pop_document_pickup(token)
                assert result2 is None

                mod._CACHED_BASE = None

    def test_store_large_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"KITTEN_PICKUP_DIR": tmp}):
                import app.services.kitten_ai_document.pickup as mod

                mod._CACHED_BASE = None

                content = b"x" * 1024 * 100  # 100KB
                token = store_document_pickup(content, "big.bin", "application/octet-stream")
                result = pop_document_pickup(token)
                assert result is not None
                assert len(result[0]) == 1024 * 100

                mod._CACHED_BASE = None
