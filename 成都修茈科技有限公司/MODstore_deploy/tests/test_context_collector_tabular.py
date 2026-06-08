"""tabular_upload_preview: CSV/TSV/XLSX column grounding for script_agent context."""

from __future__ import annotations

from io import BytesIO

from modstore_server.script_agent.context_collector import tabular_upload_preview


def test_tabular_csv_preview():
    raw = "担保余额（征信）,备注\n100,测试\n".encode("utf-8-sig")
    out = tabular_upload_preview(
        [{"filename": "sample.csv", "content": raw}],
        max_files=2,
    )
    assert "sample.csv" in out
    assert "担保余额（征信）" in out
    assert "CSV/TSV/XLSX" in out


def test_tabular_xlsx_preview():
    try:
        from openpyxl import Workbook
    except ImportError:
        return

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["担保余额（征信显示版本）", "备注"])
    ws.append(["123", "row2"])

    buf = BytesIO()
    wb.save(buf)
    data = buf.getvalue()

    out = tabular_upload_preview(
        [{"filename": "credit.xlsx", "content": data}],
        max_files=2,
    )
    assert "credit.xlsx" in out
    assert "担保余额（征信显示版本）" in out
    assert "Excel 首工作表" in out


def test_strip_llm_reasoning_in_extract_code_roundtrip():
    from modstore_server.script_agent.llm_client import extract_code_block

    raw = """Here is code:

```python
print(1)
```
"""
    assert "print(1)" in extract_code_block(raw)

    rt_open = "<think>"
    rt_close = "</think>"
    raw2 = f"```python\n{rt_open}ignore me{rt_close}\nx = 2\n```\n"
    out = extract_code_block(raw2)
    assert "ignore me" not in out
    assert "x = 2" in out
