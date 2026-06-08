"""旧版 .doc (OLE) 转换与提取。"""

from pathlib import Path

import pytest

from modstore_server.legacy_doc_convert import (
    ensure_docx_for_extract,
    is_ole_compound_file,
    is_zip_docx,
    needs_legacy_conversion,
)

WECHAT_DOC = Path(
    "/Users/a4243342/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_tfxzqdqt87oa22_62ce/temp/drag/3.doc"
)


def test_ole_detection():
    if not WECHAT_DOC.is_file():
        pytest.skip("WeChat 3.doc not available")
    assert is_ole_compound_file(WECHAT_DOC)
    assert needs_legacy_conversion(WECHAT_DOC)
    assert not is_zip_docx(WECHAT_DOC)


def test_ensure_docx_on_legacy_doc(tmp_path: Path):
    if not WECHAT_DOC.is_file():
        pytest.skip("WeChat 3.doc not available")
    out, meta = ensure_docx_for_extract(WECHAT_DOC, tmp_path / "work")
    assert meta.get("converted") is True
    assert meta.get("method") in ("libreoffice", "textutil")
    assert is_zip_docx(out)
    assert out.stat().st_size > 1000
