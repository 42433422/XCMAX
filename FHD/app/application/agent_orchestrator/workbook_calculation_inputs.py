"""Calculation-input equivalence using the existing openpyxl and OOXML parsers."""

from __future__ import annotations

import io
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from lxml import etree
from openpyxl.formula import Tokenizer
from openpyxl.formula.translate import Translator, TranslatorError
from openpyxl.utils.cell import get_column_letter, range_boundaries, range_to_tuple

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _bounds(ref: str) -> tuple[int, int, int, int]:
    left, top, right, bottom = range_boundaries(ref)
    if left is None or top is None or right is None or bottom is None:
        raise ValueError("structured reference requires a bounded cell range")
    return left, top, right, bottom


def _evaluation_input(
    content: bytes, sheets: list[tuple[str, str]], tables: list[tuple[str, str, Element]]
) -> tuple[bytes, dict[tuple[str, str], str]]:
    """Use Excel's explicit current-row spelling in a private Calc input.

    Tokenizer preserves literals; table ownership comes from the frozen OOXML.
    This expands syntax only, never calculates values or changes the deliverable.
    All untouched ZIP members remain byte-for-byte identical.
    """
    aliases, local = {}, {}
    for sheet, path, table in tables:
        name = table.get("displayName", "")
        if not name or name.casefold() in local:
            raise ValueError("ambiguous structured-reference owner")
        mapping = {}
        for column in table.findall(f"{_NS}tableColumns/{_NS}tableColumn"):
            escaped = "".join(
                ("'" if char in "[]#'@" else "") + char for char in column.get("name", "")
            )
            full = f"{name}[[#This Row],[{escaped}]]"
            for short in (f"[@{escaped}]", f"[@[{escaped}]]"):
                mapping[short.casefold()] = full
                aliases[(name + short).casefold()] = full
        local[name.casefold()] = sheet, _bounds(table.get("ref", "")), mapping, path

    def rewrite(text: str, owner: dict[str, str]) -> str:
        tokens = Tokenizer("=" + text)
        changed = False
        for token in tokens.items:
            if (token.type, token.subtype) == ("OPERAND", "RANGE"):
                replacement = aliases.get(token.value.casefold()) or owner.get(
                    token.value.casefold()
                )
                if replacement:
                    token.value, changed = replacement, True
        return tokens.render().removeprefix("=") if changed else text

    patches, substitutions = {}, {}
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    with ZipFile(io.BytesIO(content)) as archive:
        for sheet, path in sheets:
            root = etree.fromstring(archive.read(path), parser)
            changed = False
            for cell in root.iter(f"{_NS}c"):
                formula = cell.find(f"{_NS}f")
                if formula is None or not formula.text:
                    continue
                ref = cell.get("r", "").upper()
                col, row, _, _ = _bounds(ref)
                owners = [
                    mapping
                    for title, (left, top, right, bottom), mapping, _ in local.values()
                    if title == sheet and left <= col <= right and top <= row <= bottom
                ]
                if len(owners) > 1:
                    raise ValueError("overlapping structured-reference owners")
                text = rewrite(formula.text, owners[0] if owners else {})
                if text != formula.text:
                    if formula.get("t", "normal") != "normal":
                        raise ValueError("shared or array reference compilation unsupported")
                    formula.text, changed = text, True
                    substitutions[sheet, ref] = "=" + text
            if changed:
                patches[path] = etree.tostring(root, encoding="utf-8", xml_declaration=True)
        for _, _, mapping, path in local.values():
            root = etree.fromstring(archive.read(path), parser)
            changed = False
            for formula in root.iter(f"{_NS}calculatedColumnFormula"):
                text = rewrite(formula.text or "", mapping)
                if text != formula.text:
                    formula.text, changed = text, True
            if changed:
                patches[path] = etree.tostring(root, encoding="utf-8", xml_declaration=True)
        if not patches:
            return content, substitutions
        target = io.BytesIO()
        with ZipFile(target, "w") as output:
            for item in archive.infolist():
                output.writestr(item, patches.get(item.filename, archive.read(item.filename)))
        return target.getvalue(), substitutions


def _formula_semantics(formula: str) -> str:
    # Calc serializes logical constants as zero-argument calls. Tokenize with
    # openpyxl so text, cell/name references and calls with arguments stay exact.
    tokens, values, index = Tokenizer(formula).items, [], 0
    while index < len(tokens):
        token = tokens[index]
        if (
            token.type == "FUNC"
            and token.subtype == "OPEN"
            and token.value.upper() in {"TRUE(", "FALSE("}
            and index + 1 < len(tokens)
            and (tokens[index + 1].type, tokens[index + 1].subtype) == ("FUNC", "CLOSE")
        ):
            values.append(token.value[:-1].upper())
            index += 2
        else:
            values.append(
                token.value.upper()
                if (token.type, token.subtype) == ("OPERAND", "LOGICAL")
                else token.value
            )
            index += 1
    return "=" + "".join(values)


def _table_semantics(node: Element) -> tuple:
    """Keep ordered columns, formulas and metadata without ZIP identity or XML spelling."""
    tag = node.tag.removeprefix(_NS)
    defaults = {
        "table": {
            "headerRowCount": "1",
            "totalsRowCount": "0",
            "totalsRowShown": "1",
            "tableType": "worksheet",
        },
        "tableColumn": {"totalsRowFunction": "none"},
        "calculatedColumnFormula": {"array": "0"},
        "totalsRowFormula": {"array": "0"},
        "tableStyleInfo": {
            "showFirstColumn": "0",
            "showLastColumn": "0",
            "showRowStripes": "0",
            "showColumnStripes": "0",
        },
    }
    attributes = {**defaults.get(tag, {}), **node.attrib}
    if tag == "table":
        attributes.pop("id", None)  # Package-local IDs can change during conversion.
        attributes.setdefault("name", attributes.get("displayName", ""))
        attributes["ref"] = attributes.get("ref", "").replace("$", "").upper()
        for key in ("headerRowCount", "totalsRowCount"):
            attributes[key] = str(int(attributes[key]))
    elif tag == "tableColumns":
        attributes.pop("count", None)  # The actual ordered children define the columns.
    for key in (
        "totalsRowShown",
        "insertRow",
        "insertRowShift",
        "published",
        "array",
        "showFirstColumn",
        "showLastColumn",
        "showRowStripes",
        "showColumnStripes",
    ):
        if attributes.get(key) in {"true", "1"}:
            attributes[key] = "1"
        elif attributes.get(key) in {"false", "0"}:
            attributes[key] = "0"
    text = node.text or ""
    return (
        node.tag,
        tuple(sorted(attributes.items())),
        text if text.strip() else "",
        tuple(_table_semantics(child) for child in node),
    )


def _materialized_table(table: Element, sheet: str, formulas: dict) -> None:
    """Canonicalize exporter-only declarations after proving every current cell.

    The delivered OOXML is never changed. A calculated-column declaration is
    redundant for a frozen calculation only when all its data cells contain the
    exact translated formula. Missing/changed formulas keep the declaration in
    the fingerprint, so a converter dropping it still fails closed.
    """
    left, top, right, bottom = _bounds(table.get("ref", ""))
    headers = int(table.get("headerRowCount", "1"))
    totals = int(table.get("totalsRowCount", "0"))
    if headers not in (0, 1) or totals not in (0, 1):
        return
    first, last = top + headers, bottom - totals
    for index, column in enumerate(table.findall(f"{_NS}tableColumns/{_NS}tableColumn")):
        declaration = column.find(f"{_NS}calculatedColumnFormula")
        if declaration is None or not declaration.text or not 0 < last - first + 1 <= len(formulas):
            continue
        if index >= right - left + 1 or any(
            key != "array" or value not in {"0", "false"}
            for key, value in declaration.attrib.items()
        ):
            continue
        letter = get_column_letter(left + index)
        expression = (
            declaration.text if declaration.text.startswith("=") else "=" + declaration.text
        )
        translator = Translator(expression, origin=f"{letter}{first}")
        try:
            complete = all(
                (actual := formulas.get((sheet, f"{letter}{row}"))) is not None
                and _formula_semantics(actual)
                == _formula_semantics(translator.translate_formula(f"{letter}{row}"))
                for row in range(first, last + 1)
            )
        except TranslatorError:
            complete = False
        if complete:
            column.remove(declaration)
    filtering = table.find(f"{_NS}autoFilter")
    if filtering is not None and not len(filtering) and set(filtering.attrib) == {"ref"}:
        # With no predicates, including an unused totals row changes only the
        # dropdown's extent. The data area, totals and row visibility remain bound.
        if range_boundaries(filtering.get("ref", "")) in (
            (left, top, right, bottom),
            (left, top, right, last),
        ):
            filtering.set("ref", f"{get_column_letter(left)}{top}:{get_column_letter(right)}{last}")


def _name_semantics(expression: str) -> tuple:
    """Resolve only sheet quoting; retain scope, operators and $ reference flags."""
    values = []
    for token in Tokenizer("=" + expression.removeprefix("=")).items:
        value = token.value
        if (token.type, token.subtype) == ("OPERAND", "RANGE") and "!" in value:
            try:
                sheet, _ = range_to_tuple(value)
                value = (sheet, value.rsplit("!", 1)[1])
            except ValueError:
                pass
        values.append((token.type, token.subtype, value))
    return tuple(values)
