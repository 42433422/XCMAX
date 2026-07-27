"""初始单据模板种子：文件同步 + templates 表幂等入库。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

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


def test_sync_and_seed_templates_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    first = ensure_initial_document_templates()
    assert first["success"] is True
    assert SEED_SHIPMENT_KEY in (first["inserted"] + first["skipped"])
    assert SEED_PRICE_LIST_KEY in (first["inserted"] + first["skipped"])
    assert Path(first["shipment_path"]).is_file()
    assert Path(first["price_list_path"]).is_file()

    second = ensure_initial_document_templates()
    assert second["success"] is True
    assert SEED_SHIPMENT_KEY in second["skipped"]
    assert SEED_PRICE_LIST_KEY in second["skipped"]
    assert second["inserted"] == []

    from app.db.session import get_db

    with get_db() as db:
        rows = db.execute(
            text(
                "SELECT template_key FROM templates "
                "WHERE template_key IN (:a, :b) ORDER BY template_key"
            ),
            {"a": SEED_PRICE_LIST_KEY, "b": SEED_SHIPMENT_KEY},
        ).fetchall()
    keys = {str(r[0]) for r in rows}
    assert keys == {SEED_PRICE_LIST_KEY, SEED_SHIPMENT_KEY}


def test_price_list_registry_resolves_bundled_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    sync_bundled_template_files()
    path, rel = resolve_template_path_with_meta(role="price_list_docx", slug=None)
    assert path.is_file()
    assert "price_list_default.docx" in rel
