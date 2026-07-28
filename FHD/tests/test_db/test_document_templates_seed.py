"""初始单据模板种子：文件同步 + templates 表幂等入库。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.db.seeds.document_templates_seed import (
    SEED_PRICE_LIST_KEY,
    SEED_SHIPMENT_KEY,
    ensure_initial_document_templates,
    sync_bundled_template_files,
)
from app.infrastructure.documents.template_registry import resolve_template_path_with_meta


def test_bundled_seed_files_exist() -> None:
    from app.db.seeds.document_templates_seed import bundled_templates_dir

    root = bundled_templates_dir()
    assert (root / "发货单模板.xlsx").is_file()
    assert (root / "尹玉华1.xlsx").is_file()
    assert (root / "price_list_default.docx").is_file()


def test_sync_bundled_template_files_copies_to_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    files = sync_bundled_template_files()
    assert Path(files["shipment_path"]).is_file()
    assert Path(files["price_list_path"]).is_file()
    assert (tmp_path / "templates" / "尹玉华1.xlsx").is_file()


def test_ensure_initial_document_templates_inserts_and_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    db = MagicMock()
    first_calls = {"n": 0}

    def _execute(stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        if "SELECT" in sql.upper() and "template_key" in sql:
            first_calls["n"] += 1
            if first_calls["n"] <= 2:
                result.fetchone.return_value = None
            else:
                row = MagicMock()
                row.id = 1
                row.original_file_path = str(tmp_path / "templates" / "发货单模板.xlsx")
                row.is_active = 1
                result.fetchone.return_value = row
        return result

    db.execute.side_effect = _execute
    cm = MagicMock()
    cm.__enter__.return_value = db
    cm.__exit__.return_value = False

    import app.db.session as db_session

    monkeypatch.setattr(db_session, "get_db", lambda: cm)
    monkeypatch.setattr(
        "app.db.seeds.document_templates_seed.init_template_tables",
        lambda *a, **k: None,
        raising=False,
    )

    with (
        patch("app.db.init_db.init_template_tables", lambda *a, **k: None),
        patch("app.db.init_db.init_template_tables_for_engine", lambda *a, **k: None),
    ):
        first = ensure_initial_document_templates()
        second = ensure_initial_document_templates()

    assert first["success"] is True
    assert set(first["inserted"]) == {SEED_SHIPMENT_KEY, SEED_PRICE_LIST_KEY}
    assert Path(first["shipment_path"]).is_file()
    assert second["success"] is True
    assert set(second["skipped"]) == {SEED_SHIPMENT_KEY, SEED_PRICE_LIST_KEY}
    assert second["inserted"] == []


def test_price_list_registry_resolves_bundled_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    sync_bundled_template_files()
    path, rel = resolve_template_path_with_meta(role="price_list_docx", slug=None)
    assert path.is_file()
    assert "price_list_default.docx" in rel
