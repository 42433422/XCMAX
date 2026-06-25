"""Second-wave coverage for template_store_impl.

Targets previously-uncovered branches:
- _discover_excel_templates: non-file entry skip, dedup-by-norm-path skip, OSError swallow
- _discover_word_templates: non-file entry skip, dedup-by-norm-path skip, OSError swallow
- _db_templates: DB row -> dict mapping (word/excel category, missing path), OSError -> []
- get_default_for_type: DB candidate found path (sort + return newest)
- resolve_template_file: db:<id> hit, db:<id> miss, db:<id> non-int ValueError
- save_template_file: DB UPDATE+INSERT success path, DB OSError swallowed
- save_template: RECOVERABLE_ERRORS except branch
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore

MODULE = "app.infrastructure.templates.template_store_impl"


@pytest.fixture
def store(tmp_path):
    return FileSystemTemplateStore(str(tmp_path))


def _ctx_db(mock_db):
    """Wrap a MagicMock as a get_db() context manager."""
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    return mock_db


# ---------------------------------------------------------------------------
# _discover_excel_templates — uncovered branches 100, 104, 123-124
# ---------------------------------------------------------------------------


class TestDiscoverExcelBranches:
    def test_non_file_entry_is_skipped(self, tmp_path):
        """A directory whose name ends in .xlsx must be skipped (line 100)."""
        (tmp_path / "fakedir.xlsx").mkdir()
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._discover_excel_templates()
        assert templates == []

    def test_same_abspath_deduped(self, store):
        """If two candidate folders resolve to the same file, the second is
        skipped via the seen_paths guard (line 104)."""
        real = os.path.join(store._base_dir, "dup.xlsx")
        with open(real, "wb") as fh:
            fh.write(b"PK")

        original_isdir = os.path.isdir

        # Make the resources/templates candidate folder also list dup.xlsx but
        # resolve to the very same absolute path -> triggers seen_paths skip.
        def fake_listdir(folder):
            return ["dup.xlsx"]

        def fake_isdir(p):
            # base_dir and resources/templates both report as dirs
            return True

        def fake_abspath(p):
            # collapse every dup.xlsx candidate to one canonical path
            if p.endswith("dup.xlsx"):
                return real
            return os.path.abspath(p)

        with (
            patch(f"{MODULE}.os.listdir", side_effect=fake_listdir),
            patch(f"{MODULE}.os.path.isdir", side_effect=fake_isdir),
            patch(f"{MODULE}.os.path.isfile", return_value=True),
            patch(f"{MODULE}.os.path.abspath", side_effect=fake_abspath),
        ):
            templates = store._discover_excel_templates()
        # All three candidate folders collapse to the same abspath -> 1 entry.
        assert len(templates) == 1
        assert templates[0]["filename"] == "dup.xlsx"

    def test_listdir_oserror_is_swallowed(self, store):
        """os.listdir raising OSError must be caught and the folder skipped
        (lines 123-124), returning [] rather than propagating."""
        with (
            patch(f"{MODULE}.os.path.isdir", return_value=True),
            patch(f"{MODULE}.os.listdir", side_effect=OSError("boom")),
        ):
            templates = store._discover_excel_templates()
        assert templates == []


# ---------------------------------------------------------------------------
# _discover_word_templates — uncovered branches 149, 152, 172-173
# ---------------------------------------------------------------------------


class TestDiscoverWordBranches:
    def test_non_file_docx_skipped(self, tmp_path):
        (tmp_path / "notafile.docx").mkdir()
        store = FileSystemTemplateStore(str(tmp_path))
        templates = store._discover_word_templates()
        assert templates == []

    def test_same_abspath_deduped(self, store):
        real = os.path.join(store._base_dir, "dup.docx")
        with open(real, "wb") as fh:
            fh.write(b"PK")

        def fake_abspath(p):
            if p.endswith("dup.docx"):
                return real
            return os.path.abspath(p)

        with (
            patch(f"{MODULE}.os.listdir", return_value=["dup.docx"]),
            patch(f"{MODULE}.os.path.isdir", return_value=True),
            patch(f"{MODULE}.os.path.isfile", return_value=True),
            patch(f"{MODULE}.os.path.abspath", side_effect=fake_abspath),
        ):
            templates = store._discover_word_templates()
        assert len(templates) == 1
        assert templates[0]["filename"] == "dup.docx"
        assert templates[0]["category"] == "word"

    def test_listdir_oserror_is_swallowed(self, store):
        with (
            patch(f"{MODULE}.os.path.isdir", return_value=True),
            patch(f"{MODULE}.os.listdir", side_effect=OSError("nope")),
        ):
            templates = store._discover_word_templates()
        assert templates == []


# ---------------------------------------------------------------------------
# _db_templates — uncovered 185-186, 188, 195-225
# ---------------------------------------------------------------------------


class TestDbTemplates:
    def test_maps_rows_excel_and_word(self, store, tmp_path):
        existing = tmp_path / "real.xlsx"
        existing.write_bytes(b"PK")

        rows = [
            # word category derived from .docx extension + existing path
            SimpleNamespace(
                id=1,
                template_key="k1",
                template_name="WordTpl",
                template_type="Word",
                original_file_path=str(tmp_path / "missing.docx"),
                is_active=1,
            ),
            # excel category via _map_category, real existing file
            SimpleNamespace(
                id=2,
                template_key="k2",
                template_name="ExcelTpl",
                template_type="发货单",
                original_file_path=str(existing),
                is_active=1,
            ),
            # no path at all -> filename None, exists False
            SimpleNamespace(
                id=3,
                template_key="k3",
                template_name="NoPath",
                template_type="客户",
                original_file_path=None,
                is_active=None,
            ),
        ]
        mock_db = _ctx_db(MagicMock())
        mock_db.execute.return_value.fetchall.return_value = rows

        with patch(f"{MODULE}.get_db", return_value=mock_db):
            out = store._db_templates()

        assert [t["id"] for t in out] == ["db:1", "db:2", "db:3"]

        word = out[0]
        assert word["category"] == "word"
        assert word["filename"] == "missing.docx"
        assert word["exists"] is False  # file does not exist
        assert word["preview_capable"] is False

        excel = out[1]
        assert excel["category"] == "excel"
        assert excel["exists"] is True
        assert excel["preview_capable"] is True
        assert excel["filename"] == "real.xlsx"

        nopath = out[2]
        assert nopath["path"] is None
        assert nopath["filename"] is None
        assert nopath["exists"] is False
        assert nopath["source"] == "db"

    def test_oserror_returns_empty(self, store):
        """When DB access raises a recoverable error, return [] (195-196)."""
        with patch(f"{MODULE}.get_db", side_effect=OSError("db gone")):
            assert store._db_templates() == []


# ---------------------------------------------------------------------------
# get_default_for_type — uncovered 267-268 (DB candidate found path)
# ---------------------------------------------------------------------------


class TestGetDefaultForTypeDbHit:
    def test_returns_newest_existing_db_candidate(self, store, tmp_path):
        f1 = tmp_path / "old.xlsx"
        f1.write_bytes(b"PK")
        f2 = tmp_path / "new.xlsx"
        f2.write_bytes(b"PK")
        fake = [
            {
                "id": "db:1",
                "db_id": 1,
                "template_type": "发货单",
                "is_active": 1,
                "path": str(f1),
                "name": "old",
            },
            {
                "id": "db:5",
                "db_id": 5,
                "template_type": "发货单",
                "is_active": 1,
                "path": str(f2),
                "name": "new",
            },
        ]
        with patch.object(FileSystemTemplateStore, "_db_templates", return_value=fake):
            result = store.get_default_for_type("发货单")
        assert result is not None
        # Sorted by db_id desc -> highest id (5) wins.
        assert result["db_id"] == 5
        assert result["name"] == "new"


# ---------------------------------------------------------------------------
# resolve_template_file — uncovered 281-288, 295-297
# ---------------------------------------------------------------------------


class TestResolveTemplateFileDb:
    def test_db_id_resolves_existing_path(self, store, tmp_path):
        f = tmp_path / "tpl.xlsx"
        f.write_bytes(b"PK")
        row = SimpleNamespace(original_file_path=str(f))
        mock_db = _ctx_db(MagicMock())
        mock_db.execute.return_value.fetchone.return_value = row

        with patch(f"{MODULE}.get_db", return_value=mock_db):
            result = store.resolve_template_file("db:7")
        assert result == str(f)

    def test_db_id_row_path_missing_returns_none(self, store, tmp_path):
        """Row found but file no longer on disk -> not returned; falls through
        to legacy which has nothing -> None (exercises 295 false branch)."""
        row = SimpleNamespace(original_file_path=str(tmp_path / "gone.xlsx"))
        mock_db = _ctx_db(MagicMock())
        mock_db.execute.return_value.fetchone.return_value = row

        with patch(f"{MODULE}.get_db", return_value=mock_db):
            result = store.resolve_template_file("db:7")
        assert result is None

    def test_db_id_no_row_returns_none(self, store):
        mock_db = _ctx_db(MagicMock())
        mock_db.execute.return_value.fetchone.return_value = None
        with patch(f"{MODULE}.get_db", return_value=mock_db):
            result = store.resolve_template_file("db:42")
        assert result is None

    def test_db_id_oserror_swallowed_then_none(self, store):
        """DB raising recoverable error -> except pass (297) -> falls through to
        legacy -> None."""
        with patch(f"{MODULE}.get_db", side_effect=OSError("db down")):
            result = store.resolve_template_file("db:9")
        assert result is None

    def test_db_id_non_int_value_error(self, store):
        """'db:abc' -> int() raises ValueError -> db_id None -> skips DB block
        (lines 283-284), and no legacy match -> None."""
        # get_db must NOT be called since db_id is None.
        with patch(f"{MODULE}.get_db", side_effect=AssertionError("must not query")):
            result = store.resolve_template_file("db:abc")
        assert result is None


# ---------------------------------------------------------------------------
# save_template_file — uncovered DB UPDATE/INSERT path 362, 392 + except
# ---------------------------------------------------------------------------


class TestSaveTemplateFileDb:
    def test_db_update_insert_commit_executed(self, tmp_path):
        source = tmp_path / "src.xlsx"
        source.write_bytes(b"PK")
        store = FileSystemTemplateStore(str(tmp_path))

        mock_db = _ctx_db(MagicMock())
        with patch(f"{MODULE}.get_db", return_value=mock_db):
            result = store.save_template_file("src.xlsx", "out.xlsx", True)

        assert result["success"] is True
        assert result["saved"] is True
        # UPDATE + INSERT both issued, then commit.
        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()
        # File actually copied to target.
        assert (tmp_path / "out.xlsx").exists()

    def test_db_error_swallowed_still_saves_file(self, tmp_path):
        source = tmp_path / "src.xlsx"
        source.write_bytes(b"PK")
        store = FileSystemTemplateStore(str(tmp_path))

        with patch(f"{MODULE}.get_db", side_effect=OSError("no table")):
            result = store.save_template_file("src.xlsx", "out2.xlsx", True)

        # DB recording failed but file copy + success response are preserved.
        assert result["success"] is True
        assert result["saved"] is True
        assert (tmp_path / "out2.xlsx").exists()


# ---------------------------------------------------------------------------
# save_template — uncovered except RECOVERABLE_ERRORS 452-454
# ---------------------------------------------------------------------------


class TestSaveTemplateError:
    def test_db_error_returns_failure(self, store):
        with patch(f"{MODULE}.get_db", side_effect=OSError("insert failed")):
            result = store.save_template({"template_name": "X"})
        assert result["success"] is False
        assert "insert failed" in result["message"]
