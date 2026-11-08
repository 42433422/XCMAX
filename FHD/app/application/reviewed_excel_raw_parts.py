"""Verbatim reinsertion of sheet elements openpyxl cannot model.

openpyxl drops vendor attributes and extLst children it does not know (for example
WPS AutoFilter metadata). When a saved copy keeps such an element unchanged, the
source element bytes are spliced back; the only addition is a copy of the source
root's namespace bindings that the element uses and the new root does not give, so
it parses identically there. Whenever the element would have to change, the copy
fails closed.
"""

import re
from io import BytesIO
from xml.etree import ElementTree as XML
from zipfile import ZipFile

from defusedxml import ElementTree as SAFE
from defusedxml.common import DefusedXmlException

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_drawing import S
from app.application.reviewed_excel_range_objects import _fingerprint, _package, _sheet

_ATTRS = rb"(?:[^>\"']|\"[^\"]*\"|'[^']*')*?"
_ELEMENT = re.compile(
    rb"<(?:([A-Za-z_][\w.-]*):)?autoFilter\b" + _ATTRS + rb"(?:/>|>.*?</(?:\1:)?autoFilter\s*>)",
    re.S,
)
_ROOT = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?worksheet\b(" + _ATTRS + rb")/?>", re.S)
_DECLARATION = re.compile(rb"\sxmlns(?::([A-Za-z_][\w.-]*))?\s*=\s*(\"[^\"]*\"|'[^']*')")
_PREFIX = re.compile(rb"[<\s/]([A-Za-z_][\w.-]*):[A-Za-z_]")


def _fail(message):
    raise ReviewedExcelError("筛选器原始 XML 无法保真保留：" + message + "；未改写文件")


def _parse(data):
    try:
        return SAFE.fromstring(data, forbid_dtd=True)
    except (XML.ParseError, DefusedXmlException):
        return None


def _unmodeled(node) -> bool:
    return any(name.startswith("{") for name in node.attrib) or any(
        child.tag == f"{{{S}}}extLst" for child in node
    )


def _span(data: bytes):
    spans = list(_ELEMENT.finditer(data))
    if len(spans) > 1:
        _fail("工作表含多个筛选器")
    return spans[0] if spans else None


def _root_declarations(data: bytes) -> dict[bytes, bytes]:
    root = _ROOT.search(data)
    return {p or b"": v for p, v in _DECLARATION.findall(root.group(1))} if root else {}


def _portable(raw: bytes, inherited: dict, target: dict) -> bytes:
    """The element bytes plus the source bindings the target root does not already give."""
    span = _ELEMENT.match(raw)
    start = raw[: raw.index(b">") + 1]
    local = {p or b"" for p, _v in _DECLARATION.findall(start)}
    used = {p for p in _PREFIX.findall(raw) if p != b"xmlns"}
    if span.group(1) is None:
        used.add(b"")
    missing = sorted(p for p in used - local if p in inherited and target.get(p) != inherited[p])
    extra = b"".join((b" xmlns:" + p if p else b" xmlns") + b"=" + inherited[p] for p in missing)
    name_end = len(b"<" + (span.group(1) + b":" if span.group(1) else b"") + b"autoFilter")
    return raw[:name_end] + extra + raw[name_end:]


def preserved_filters(body: bytes) -> dict[str, tuple[bytes, dict, tuple]]:
    """Sheet name to (element bytes, root bindings, fingerprint) for unmodeled metadata."""
    kept = {}
    with _package(body) as archive:
        workbook = SAFE.fromstring(archive.read("xl/workbook.xml"), forbid_dtd=True)
        for entry in workbook.findall(f"{{{S}}}sheets/{{{S}}}sheet"):
            name = entry.get("name")
            part, sheet = _sheet(archive, name)
            nodes = sheet.findall(f"{{{S}}}autoFilter")
            if not nodes or not _unmodeled(nodes[0]):
                continue
            data = archive.read(part)
            span = _span(data)
            if span is None or len(nodes) != 1:
                _fail("筛选器不是可定位的独立元素")
            inherited = _root_declarations(data)
            standalone = _parse(_portable(span.group(0), inherited, {}))
            if standalone is None or _fingerprint(standalone) != _fingerprint(nodes[0]):
                _fail("筛选器依赖无法携带的命名空间上下文")
            kept[name] = (span.group(0), inherited, _fingerprint(nodes[0]))
    return kept


def restore_filters(result: bytes, kept: dict[str, tuple[bytes, dict, tuple]]) -> bytes:
    """Replace each saved filter with its source element when only unmodeled parts differ."""
    if not kept:
        return result
    replaced: dict[str, bytes] = {}
    with _package(result) as archive:
        for name, (element, inherited, _expected) in kept.items():
            part, sheet = _sheet(archive, name)
            saved = sheet.findall(f"{{{S}}}autoFilter")
            data = archive.read(part)
            raw = _portable(element, inherited, _root_declarations(data))
            source = _parse(_portable(element, inherited, {}))
            if len(saved) != 1 or saved[0].get("ref") != source.get("ref"):
                _fail("保存后筛选器范围改变，需要改写")
            modeled = [c for c in source if c.tag != f"{{{S}}}extLst"]
            if list(map(_fingerprint, saved[0])) != list(map(_fingerprint, modeled)):
                _fail("保存后筛选条件改变，需要改写")
            span = _span(data)
            if span is None:
                _fail("保存后筛选器不可定位")
            replaced[part] = data[: span.start()] + raw + data[span.end() :]
        output = BytesIO()
        with ZipFile(output, "w") as target:
            for entry in archive.infolist():
                target.writestr(entry, replaced.get(entry.filename) or archive.read(entry.filename))
    restored = output.getvalue()
    with _package(restored) as archive:
        for name, (_element, _inherited, fingerprint) in kept.items():
            _part, sheet = _sheet(archive, name)
            if [_fingerprint(n) for n in sheet.findall(f"{{{S}}}autoFilter")] != [fingerprint]:
                _fail("筛选器读回不一致")
    return restored
