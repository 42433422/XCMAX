"""Low-level Word table-row primitives for price-list exports."""

from __future__ import annotations

import copy
from typing import Any

from docx.oxml.ns import qn


def tbl_row_count(table: Any) -> int:
    return len([child for child in table._tbl if child.tag == qn("w:tr")])


def clear_tr_text_content(row_element: Any) -> None:
    for element in row_element.iter():
        if element.tag == qn("w:t"):
            element.text = ""


def append_tr_clone_from_last(table: Any) -> None:
    table_element = table._tbl
    rows = [child for child in table_element if child.tag == qn("w:tr")]
    if not rows:
        return
    new_row = copy.deepcopy(rows[-1])
    clear_tr_text_content(new_row)
    table_element.append(new_row)


def header_text(cell: Any) -> str:
    return (cell.text or "").strip()
