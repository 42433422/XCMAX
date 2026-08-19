"""Small OOXML border primitives used by price-list document rendering."""

from __future__ import annotations

import copy
from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def border_el_effective(el: Any | None) -> bool:
    if el is None:
        return False
    value = el.get(qn("w:val"))
    if not value:
        return False
    return str(value).lower() not in ("nil", "none")


def border_element_as_w_bottom(src: Any | None) -> Any | None:
    """Return a copied border element normalized to the ``w:bottom`` tag."""
    if src is None:
        return None
    if src.tag == qn("w:bottom"):
        return copy.deepcopy(src)
    out = OxmlElement("w:bottom")
    for key, value in src.attrib.items():
        out.set(key, value)
    return out
