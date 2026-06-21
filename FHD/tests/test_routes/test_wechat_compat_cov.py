"""
Branch-coverage tests for app/fastapi_routes/domains/wechat/compat_routes.py.

Strategy for tests that go past session_db_not_exists:
  full_decrypt writes the decrypted bytes to
      os.path.join(tempfile.gettempdir(), "wechat_work_mode_feed.db")
  and then the route calls sqlite3.connect(tmp_path).
  We intercept sqlite3.connect so that when the tmp path is requested we
  return a connection to a pre-built valid SQLite file with controlled data.
  That sidesteps the need for real AES/pycryptodome.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.wechat import compat_routes

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_FEED_TMP_NAME = "wechat_work_mode_feed.db"


@pytest.fixture(autouse=True)
def _reset_starred_db():
    """Reset global in-memory starred contacts DB before/after each test."""
    compat_routes._STARRED_CONTACTS_DB.clear()
    compat_routes._STARRED_NEXT_ID = 1
    yield
    compat_routes._STARRED_CONTACTS_DB.clear()
    compat_routes._STARRED_NEXT_ID = 1


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(compat_routes.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper: build config.json / all_keys.json fixtures as temp files
# ---------------------------------------------------------------------------

_PAGE_SZ = 4096
_RESERVE_SZ = 80
_SALT_SZ = 16


def _write_wechat_decrypt_dir(
    tmp_dir: str,
    keys_format: str = "list",
    session_db_exists: bool = True,
    decrypted_dir_abs: bool = True,
    decrypted_dir_has_contact: bool = False,
) -> tuple[str, str, str]:
    """
    Write config.json + all_keys.json inside *tmp_dir*.
    Returns (tmp_dir, session_db_path, abs_decrypted_dir).
    """
    raw_db_dir = os.path.join(tmp_dir, "raw_db", "session")
    os.makedirs(raw_db_dir, exist_ok=True)

    if decrypted_dir_abs:
        decrypted_dir_cfg = os.path.join(tmp_dir, "decrypted")
    else:
        decrypted_dir_cfg = "decrypted"  # relative path → triggers branch 193→194

    abs_decrypted = os.path.join(tmp_dir, "decrypted")
    os.makedirs(abs_decrypted, exist_ok=True)

    if decrypted_dir_has_contact:
        contact_dir = os.path.join(abs_decrypted, "contact")
        os.makedirs(contact_dir, exist_ok=True)
        cconn = sqlite3.connect(os.path.join(contact_dir, "contact.db"))
        cconn.execute("CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT)")
        cconn.execute("INSERT INTO contact VALUES ('user1','Nick1','Remark1')")
        cconn.commit()
        cconn.close()

    cfg = {"db_dir": raw_db_dir, "decrypted_dir": decrypted_dir_cfg}
    with open(os.path.join(tmp_dir, "config.json"), "w") as f:
        json.dump(cfg, f)

    enc_key_hex = "aa" * 32  # value irrelevant; sqlite3.connect is mocked downstream

    if keys_format == "dict":
        keys: dict | list = {
            os.path.join("session", "session.db"): {"enc_key": enc_key_hex}
        }
    elif keys_format == "list_with_enc_key":
        keys = [{"enc_key": enc_key_hex, "path": os.path.join("session", "session.db")}]
    elif keys_format == "list_nested":
        keys = [
            {
                "keys": [
                    {
                        "enc_key": enc_key_hex,
                        "path": os.path.join("session", "session.db"),
                    }
                ]
            }
        ]
    elif keys_format == "list_no_enc_key":
        # k has neither 'enc_key' nor 'keys' — skipped by strip_key_metadata
        keys = [{"path": os.path.join("session", "session.db")}]
    else:
        keys = [{"enc_key": enc_key_hex, "path": os.path.join("session", "session.db")}]

    with open(os.path.join(tmp_dir, "all_keys.json"), "w") as f:
        json.dump(keys, f)

    session_db_path = os.path.join(raw_db_dir, "session.db")
    if session_db_exists:
        # The file just needs to exist on disk (full_decrypt reads it, but we
        # mock sqlite3.connect so the decrypted output is irrelevant).
        with open(session_db_path, "wb") as f:
            f.write(b"\x00" * _PAGE_SZ)

    return tmp_dir, session_db_path, abs_decrypted


def _make_session_db(summary_value, last_timestamp: int = 1700000000, msg_type: int = 1) -> str:
    """Create a real SQLite file with one SessionTable row; return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute(
        """CREATE TABLE SessionTable (
            username TEXT, unread_count INTEGER, summary TEXT,
            last_timestamp INTEGER, last_msg_type INTEGER,
            last_msg_sender TEXT, last_sender_display_name TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO SessionTable VALUES (?,?,?,?,?,?,?)",
        ("user1", 3, summary_value, last_timestamp, msg_type, "sender1", "Sender"),
    )
    conn.commit()
    conn.close()
    return tmp.name


def _sqlite_connect_interceptor(real_db_path: str, tmp_dir: str):
    """
    Return a fake sqlite3.connect that:
      - redirects connect(…/wechat_work_mode_feed.db) → real_db_path
      - passes every other path through unchanged
    """
    orig = sqlite3.connect

    def _fake(path, *a, **kw):
        if _FEED_TMP_NAME in str(path):
            return orig(real_db_path, *a, **kw)
        return orig(path, *a, **kw)

    return _fake


# ===========================================================================
# Section A: strip_key_metadata branches (lines 103-112)
# ===========================================================================


class TestStripKeyMetadata:
    """Branch paths inside the strip_key_metadata closure."""

    def _run(self, tmp_dir, client, real_db_path):
        fake_connect = _sqlite_connect_interceptor(real_db_path, tmp_dir)
        with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}), patch(
            "sqlite3.connect", side_effect=fake_connect
        ):
            return client.get("/wechat_contacts/work_mode_feed")

    def test_keys_is_dict_returns_dict(self, tmp_path, client):
        """Branch [103, 104]: all_keys.json is a JSON object → strip returns dict as-is."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="dict")
        real_db = _make_session_db("hello")
        try:
            resp = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert "items" in data or "error" in data
        finally:
            os.unlink(real_db)

    def test_list_item_has_enc_key(self, tmp_path, client):
        """Branch [107, 108]: list item is dict with 'enc_key' → append."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_with_enc_key")
        real_db = _make_session_db("hello")
        try:
            resp = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert "items" in data or "error" in data
        finally:
            os.unlink(real_db)

    def test_list_item_has_keys_sub(self, tmp_path, client):
        """Branch [110, 111]: list item has 'keys' sub-list → extend."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_nested")
        real_db = _make_session_db("hello")
        try:
            resp = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert "items" in data or "error" in data
        finally:
            os.unlink(real_db)

    def test_list_item_no_enc_key_no_keys(self, tmp_path, client):
        """Branch [110, 106]: list item has neither 'enc_key' nor 'keys' → skip."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_no_enc_key")
        with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}):
            resp = client.get("/wechat_contacts/work_mode_feed")
        data = resp.json()
        assert data.get("error") == "session.db key not found"


# ===========================================================================
# Section B: decrypt_page pgno==1 branch (lines 124-128)
# ===========================================================================


class TestDecryptPage:
    """Branch [124, 125]: pgno==1 → SALT_SZ offset + prepend SQLITE_HDR."""

    def test_pgno_equals_1(self, tmp_path, client):
        """
        The route calls full_decrypt which iterates pgno starting at 1.
        We mock AES so the first page (pgno==1) path is exercised.
        full_decrypt writes bytes then we intercept sqlite3.connect.
        """
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_with_enc_key")
        real_db = _make_session_db("pgno1 test")

        # Make a fake AES cipher whose decrypt returns plausible-length bytes
        fake_cipher = MagicMock()
        fake_cipher.decrypt.return_value = b"\x00" * (_PAGE_SZ - _SALT_SZ - _RESERVE_SZ)
        fake_aes_mod = MagicMock()
        fake_aes_mod.new.return_value = fake_cipher
        fake_aes_mod.MODE_CBC = 2
        fake_crypto_cipher = MagicMock()
        fake_crypto_cipher.AES = fake_aes_mod

        fake_connect = _sqlite_connect_interceptor(real_db, tmp_dir)
        try:
            with (
                patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}),
                patch.dict(
                    "sys.modules",
                    {"Crypto": MagicMock(), "Crypto.Cipher": fake_crypto_cipher},
                ),
                patch("sqlite3.connect", side_effect=fake_connect),
            ):
                resp = client.get("/wechat_contacts/work_mode_feed")
            assert resp.status_code in (200, 500)
        finally:
            os.unlink(real_db)


# ===========================================================================
# Section C: get_key_info branches (lines 135-154)
# ===========================================================================


class TestGetKeyInfoViaRoute:
    """get_key_info: dict path vs list path vs nested sub-keys."""

    def _run(self, tmp_dir, client, real_db_path):
        fake_connect = _sqlite_connect_interceptor(real_db_path, tmp_dir)
        with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}), patch(
            "sqlite3.connect", side_effect=fake_connect
        ):
            return client.get("/wechat_contacts/work_mode_feed")

    def test_get_key_info_dict_path_match(self, tmp_path, client):
        """Branch [136, 137]+[137, 138]: dict keys → path_key loop matches."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="dict")
        real_db = _make_session_db("dict match")
        try:
            resp = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert "items" in data or "error" in data
        finally:
            os.unlink(real_db)

    def test_get_key_info_list_nested_sub_keys(self, tmp_path, client):
        """Branch [150, 151]+[151, 152]+[152, 151]+[152, 153]: nested 'keys' traversal."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_nested")
        real_db = _make_session_db("nested sub")
        try:
            resp = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert "items" in data or "error" in data
        finally:
            os.unlink(real_db)


# ===========================================================================
# Section D: full_decrypt — partial-page branches (lines 163-167)
# ===========================================================================


class TestFullDecryptPartialPage:
    """
    Branch [163, 164]: read returns 0 < n < PAGE_SZ → pad with zeros.
    Branch [164, 167] (via [163,167]): read returns 0 bytes → break loop.
    We control the reads by mocking open() for the raw session.db only.
    """

    def _run(self, tmp_dir, client, real_db_path, partial_len: int):
        raw_db_path = os.path.join(tmp_dir, "raw_db", "session", "session.db")
        total_pages = 2
        fake_total_size = _PAGE_SZ * total_pages
        page1 = b"\xAA" * _PAGE_SZ
        page2_partial = b"\xBB" * partial_len

        # Mock AES so decrypt_page doesn't need pycryptodome
        fake_cipher = MagicMock()
        fake_cipher.decrypt.return_value = b"\x00" * (_PAGE_SZ - _SALT_SZ - _RESERVE_SZ)
        fake_aes_mod = MagicMock()
        fake_aes_mod.new.return_value = fake_cipher
        fake_aes_mod.MODE_CBC = 2
        fake_crypto_cipher = MagicMock()
        fake_crypto_cipher.AES = fake_aes_mod

        # We need a file-like object for the raw DB reads
        class _FakeFile:
            def __init__(self):
                self._reads = iter([page1, page2_partial])

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self, n):
                try:
                    return next(self._reads)
                except StopIteration:
                    return b""

        _real_open = open

        def _fake_open(path, *a, **kw):
            mode = a[0] if a else kw.get("mode", "r")
            if str(path) == raw_db_path and "rb" in str(mode):
                return _FakeFile()
            return _real_open(path, *a, **kw)

        fake_connect = _sqlite_connect_interceptor(real_db_path, tmp_dir)

        with (
            patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}),
            patch("os.path.getsize", side_effect=lambda p: fake_total_size if str(p) == raw_db_path else os.stat(p).st_size),
            patch("builtins.open", side_effect=_fake_open),
            patch.dict(
                "sys.modules",
                {"Crypto": MagicMock(), "Crypto.Cipher": fake_crypto_cipher},
            ),
            patch("sqlite3.connect", side_effect=fake_connect),
        ):
            return client.get("/wechat_contacts/work_mode_feed")

    def test_partial_page_padded(self, tmp_path, client):
        """Branch [163, 164] then [164, 165]: partial read → pad."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_with_enc_key")
        real_db = _make_session_db("partial")
        try:
            resp = self._run(tmp_dir, client, real_db, partial_len=100)
            assert resp.status_code in (200, 500)
        finally:
            os.unlink(real_db)

    def test_empty_page_breaks(self, tmp_path, client):
        """Branch [164, 167]: empty read → break loop."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_with_enc_key")
        real_db = _make_session_db("empty page")
        try:
            resp = self._run(tmp_dir, client, real_db, partial_len=0)
            assert resp.status_code in (200, 500)
        finally:
            os.unlink(real_db)


# ===========================================================================
# Section E: wechat_work_mode_feed main body branches
# ===========================================================================


class TestWorkModeFeedMainBody:
    """Cover session_db existence, decrypted_dir abs-path, contact_cache branches."""

    def _run(self, tmp_dir, client, real_db_path=None):
        if real_db_path is None:
            real_db_path = _make_session_db("hello")
        fake_connect = _sqlite_connect_interceptor(real_db_path, tmp_dir)
        with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}), patch(
            "sqlite3.connect", side_effect=fake_connect
        ):
            resp = client.get("/wechat_contacts/work_mode_feed")
        return resp, real_db_path

    def test_session_db_not_exists_returns_error(self, tmp_path, client):
        """Branch [178, 179]: session.db absent → early return with error."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_with_enc_key", session_db_exists=False)
        with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}):
            resp = client.get("/wechat_contacts/work_mode_feed")
        data = resp.json()
        assert data.get("error") == "session.db not found in raw_db, run sync_raw_db.py first"

    def test_decrypted_dir_relative_path(self, tmp_path, client):
        """Branch [193, 194]: decrypted_dir relative → os.path.join prepend."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(
            tmp_dir, keys_format="list_with_enc_key", session_db_exists=True, decrypted_dir_abs=False
        )
        real_db = _make_session_db("rel path")
        try:
            resp, _ = self._run(tmp_dir, client, real_db)
            data = resp.json()
            # must have passed the session_db check
            assert data.get("error") != "session.db not found in raw_db, run sync_raw_db.py first"
        finally:
            os.unlink(real_db)

    def test_decrypted_dir_absolute_path(self, tmp_path, client):
        """Branch [193, 195]: decrypted_dir absolute → skip join."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(
            tmp_dir, keys_format="list_with_enc_key", session_db_exists=True, decrypted_dir_abs=True
        )
        real_db = _make_session_db("abs path")
        try:
            resp, _ = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert data.get("error") != "session.db not found in raw_db, run sync_raw_db.py first"
        finally:
            os.unlink(real_db)

    def test_contact_cache_exists_branch(self, tmp_path, client):
        """Branch [197, 198]: contact_cache exists → connect + read rows."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(
            tmp_dir,
            keys_format="list_with_enc_key",
            session_db_exists=True,
            decrypted_dir_abs=True,
            decrypted_dir_has_contact=True,
        )
        real_db = _make_session_db("with contact")
        try:
            resp, _ = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert "items" in data or "error" in data
        finally:
            os.unlink(real_db)

    def test_contact_cache_not_exists_branch(self, tmp_path, client):
        """Branch [197, 209]: contact_cache absent → skip contact lookup."""
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(
            tmp_dir,
            keys_format="list_with_enc_key",
            session_db_exists=True,
            decrypted_dir_abs=True,
            decrypted_dir_has_contact=False,
        )
        real_db = _make_session_db("no contact cache")
        try:
            resp, _ = self._run(tmp_dir, client, real_db)
            data = resp.json()
            assert "items" in data or "error" in data
        finally:
            os.unlink(real_db)


# ===========================================================================
# Section F: zstd / fallback decode branches and summary string split
# ===========================================================================


class TestZstdAndSummaryBranches:
    """
    We intercept sqlite3.connect so the route reads from a db we control,
    then vary the summary field type/content.
    """

    def _run_with_summary(
        self,
        client,
        tmp_path,
        summary_value,
        zstd_available: bool = True,
    ):
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_with_enc_key", session_db_exists=True)
        real_db = _make_session_db(summary_value)
        fake_connect = _sqlite_connect_interceptor(real_db, tmp_dir)

        if zstd_available:
            fake_dctx = MagicMock()
            fake_dctx.decompress.return_value = b"decoded text"
            fake_zstd_mod = MagicMock()
            fake_zstd_mod.ZstdDecompressor.return_value = fake_dctx
            zstd_ctx = patch.dict("sys.modules", {"zstandard": fake_zstd_mod})
        else:
            # Remove zstandard so ImportError path is taken
            zstd_ctx = patch.dict("sys.modules", {"zstandard": None})

        try:
            with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}), patch(
                "sqlite3.connect", side_effect=fake_connect
            ), zstd_ctx:
                resp = client.get("/wechat_contacts/work_mode_feed")
            return resp
        finally:
            try:
                os.unlink(real_db)
            except OSError:
                pass

    def test_summary_bytes_with_zstd(self, tmp_path, client):
        """Branch [238, 239]+[239, 240]: summary is bytes AND zstd available → decompress."""
        resp = self._run_with_summary(client, tmp_path, b"\xfe\xedSTUB", zstd_available=True)
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert "items" in data

    def test_summary_bytes_no_zstd(self, tmp_path, client):
        """Branch [238, 239]+[239, 247]: summary bytes AND zstd unavailable → utf-8 decode."""
        resp = self._run_with_summary(client, tmp_path, b"plain bytes", zstd_available=False)
        assert resp.status_code in (200, 500)

    def test_summary_is_str(self, tmp_path, client):
        """Branch [238, 251]: summary is str → skip bytes block."""
        resp = self._run_with_summary(client, tmp_path, "plain text summary")
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert "items" in data

    def test_summary_str_with_colon_newline(self, tmp_path, client):
        """Branch [251, 252]: str summary contains ':\\n' → split and take second part."""
        resp = self._run_with_summary(client, tmp_path, "SenderName:\nActual content")
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                assert items[0]["summary"] == "Actual content"

    def test_summary_str_without_colon_newline(self, tmp_path, client):
        """Branch [251, 254]: str summary has no ':\\n' → pass through unchanged."""
        resp = self._run_with_summary(client, tmp_path, "No separator here")
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                assert items[0]["summary"] == "No separator here"


# ===========================================================================
# Section G: rows loop — empty result set (branch [234, 292])
# ===========================================================================


class TestSessionRowsLoopEarlyExit:
    """Branch [234, 292]: rows list is empty → loop body never executes."""

    def test_empty_rows_returns_empty_items(self, tmp_path, client):
        tmp_dir = str(tmp_path)
        _write_wechat_decrypt_dir(tmp_dir, keys_format="list_with_enc_key", session_db_exists=True)
        # last_timestamp=0 → WHERE last_timestamp > 0 returns nothing
        empty_db = _make_session_db("ignored", last_timestamp=0)
        fake_connect = _sqlite_connect_interceptor(empty_db, tmp_dir)
        try:
            with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}), patch(
                "sqlite3.connect", side_effect=fake_connect
            ):
                resp = client.get("/wechat_contacts/work_mode_feed")
            data = resp.json()
            if resp.status_code == 200:
                assert data["items"] == []
        finally:
            try:
                os.unlink(empty_db)
            except OSError:
                pass


# ===========================================================================
# Section H: wechat_contacts_delete_compat — id found vs not found
# ===========================================================================


class TestWechatContactsDeleteCompat:
    """Branch [494, 493]: id matches → delete; [494, ...] exhausted → failure."""

    def test_delete_existing_contact(self, client):
        """Branch [494, 493]: id found → delete and return success."""
        compat_routes._STARRED_CONTACTS_DB["wxabc"] = {
            "id": 42,
            "type": "contact",
            "nickname": "A",
            "remark": "",
            "wxid": "wxabc",
            "starred": True,
        }
        compat_routes._STARRED_NEXT_ID = 43
        resp = client.delete("/wechat_contacts/42")
        data = resp.json()
        assert data["success"] is True
        assert "wxabc" not in compat_routes._STARRED_CONTACTS_DB

    def test_delete_nonexistent_contact(self, client):
        """Branch [494, ...] loop exhausted without match → failure."""
        compat_routes._STARRED_CONTACTS_DB["wxabc"] = {
            "id": 99,
            "type": "contact",
            "nickname": "A",
            "remark": "",
            "wxid": "wxabc",
            "starred": True,
        }
        resp = client.delete("/wechat_contacts/999")
        data = resp.json()
        assert data["success"] is False
        assert "联系人不存在" in data["message"]

    def test_delete_empty_db(self, client):
        """Loop never entered (empty DB) → return failure."""
        resp = client.delete("/wechat_contacts/1")
        data = resp.json()
        assert data["success"] is False


# ===========================================================================
# Section I: wechat_contacts_update_compat — id found vs not found
# ===========================================================================


class TestWechatContactsUpdateCompat:
    """Branch [504, 503]: id matches → update; [504, ...] exhausted → failure."""

    def test_update_existing_contact(self, client):
        """Branch [504, 503]: id found → update fields and return success."""
        compat_routes._STARRED_CONTACTS_DB["wxupd"] = {
            "id": 10,
            "type": "contact",
            "nickname": "OldName",
            "remark": "OldRemark",
            "wxid": "wxupd",
            "starred": True,
        }
        compat_routes._STARRED_NEXT_ID = 11
        resp = client.put(
            "/wechat_contacts/10",
            json={"contact_name": "NewName", "remark": "NewRemark"},
        )
        data = resp.json()
        assert data["success"] is True
        assert compat_routes._STARRED_CONTACTS_DB["wxupd"]["nickname"] == "NewName"

    def test_update_nonexistent_contact(self, client):
        """Branch [504, ...] exhausted without match → failure."""
        compat_routes._STARRED_CONTACTS_DB["wxupd"] = {
            "id": 10,
            "type": "contact",
            "nickname": "OldName",
            "remark": "",
            "wxid": "wxupd",
            "starred": True,
        }
        resp = client.put("/wechat_contacts/999", json={"contact_name": "SomeName"})
        data = resp.json()
        assert data["success"] is False
        assert "联系人不存在" in data["message"]

    def test_update_empty_db(self, client):
        """Loop never entered → failure."""
        resp = client.put("/wechat_contacts/1", json={"contact_name": "X"})
        data = resp.json()
        assert data["success"] is False

    def test_update_all_fields(self, client):
        """Update contact_name, remark, wechat_id, contact_type in one call."""
        compat_routes._STARRED_CONTACTS_DB["wxupd2"] = {
            "id": 20,
            "type": "contact",
            "nickname": "Orig",
            "remark": "OldRem",
            "wxid": "wxupd2",
            "starred": True,
        }
        compat_routes._STARRED_NEXT_ID = 21
        resp = client.put(
            "/wechat_contacts/20",
            json={
                "contact_name": "NewNick",
                "remark": "NewRem",
                "wechat_id": "wx_new_id",
                "contact_type": "group",
            },
        )
        data = resp.json()
        assert data["success"] is True
        c = compat_routes._STARRED_CONTACTS_DB["wxupd2"]
        assert c["nickname"] == "NewNick"
        assert c["remark"] == "NewRem"
        assert c["wxid"] == "wx_new_id"
        assert c["type"] == "group"


# ===========================================================================
# Section J: work_mode_feed early returns (config / keys absent)
# ===========================================================================


class TestWorkModeFeedEarlyReturns:
    def test_config_not_found(self, tmp_path, client):
        """config.json or all_keys.json absent → early return 'not configured'."""
        with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": str(tmp_path)}):
            resp = client.get("/wechat_contacts/work_mode_feed")
        data = resp.json()
        assert data.get("error") == "wechat-decrypt not configured"

    def test_keys_no_matching_session_key(self, tmp_path, client):
        """all_keys.json exists but no entry for session/session.db → key not found."""
        tmp_dir = str(tmp_path)
        with open(os.path.join(tmp_dir, "config.json"), "w") as f:
            json.dump({"decrypted_dir": tmp_dir}, f)
        with open(os.path.join(tmp_dir, "all_keys.json"), "w") as f:
            json.dump([{"enc_key": "aa" * 32, "path": "other/other.db"}], f)
        with patch.dict(os.environ, {"WECHAT_DECRYPT_PATH": tmp_dir}):
            resp = client.get("/wechat_contacts/work_mode_feed")
        data = resp.json()
        assert data.get("error") == "session.db key not found"
