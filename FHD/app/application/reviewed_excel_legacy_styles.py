"""Explicit BIFF8-to-OOXML cell-style mapping for data-test derivatives only."""

from openpyxl.styles import Alignment, Border, Color, Font, PatternFill, Protection, Side

from app.application.elt.errors import ReviewedExcelError

_PATTERNS = [
    None,
    "solid",
    "mediumGray",
    "darkGray",
    "lightGray",
    "darkHorizontal",
    "darkVertical",
    "darkDown",
    "darkUp",
    "darkGrid",
    "darkTrellis",
    "lightHorizontal",
    "lightVertical",
    "lightDown",
    "lightUp",
    "lightGrid",
    "lightTrellis",
    "gray125",
    "gray0625",
]
_BORDERS = [
    None,
    "thin",
    "medium",
    "dashed",
    "dotted",
    "thick",
    "double",
    "hair",
    "mediumDashed",
    "dashDot",
    "mediumDashDot",
    "dashDotDot",
    "mediumDashDotDot",
    "slantDashDot",
]
_HORIZ = [
    "general",
    "left",
    "center",
    "right",
    "fill",
    "justify",
    "centerContinuous",
    "distributed",
]
_VERT = ["top", "center", "bottom", "justify", "distributed"]
_UNDERLINE = {0: None, 1: "single", 2: "double", 0x21: "singleAccounting", 0x22: "doubleAccounting"}


def legacy_color(book, index):
    if index in (64, 65, 32767):
        return Color(auto=True)
    rgb = book.colour_map.get(index)
    if rgb is None:
        raise ReviewedExcelError("旧 XLS 包含不能确认的调色板颜色")
    return Color(rgb="FF" + "".join(f"{value:02X}" for value in rgb))


def legacy_style(book, index):
    xf = book.xf_list[index]
    font = book.font_list[xf.font_index]
    alignment, border = xf.alignment, xf.border
    # BIFF Font.bls is authoritative. xlrd.font.bold reflects a bit which the
    # BIFF8 specification marks unused; using it loses real 700-weight fonts.
    if font.weight not in (400, 700):
        raise ReviewedExcelError("旧 XLS 字体字重不能精确映射（仅支持 400/700）")
    try:
        mapped_font = Font(
            name=font.name,
            sz=font.height / 20,
            b=font.weight == 700,
            i=bool(font.italic),
            strike=bool(font.struck_out),
            u=_UNDERLINE[font.underline_type],
            color=legacy_color(book, font.colour_index),
            charset=font.character_set,
            family=font.family,
            outline=bool(font.outline),
            shadow=bool(font.shadow),
            vertAlign={0: None, 1: "superscript", 2: "subscript"}[font.escapement],
        )
        sides = {}
        for old, new in [
            ("left", "left"),
            ("right", "right"),
            ("top", "top"),
            ("bottom", "bottom"),
            ("diag", "diagonal"),
        ]:
            line = getattr(border, old + "_line_style")
            sides[new] = Side(
                style=_BORDERS[line],
                color=legacy_color(book, getattr(border, old + "_colour_index")) if line else None,
            )
        mapped_border = Border(
            **sides, diagonalUp=bool(border.diag_up), diagonalDown=bool(border.diag_down)
        )
        fill = PatternFill(patternType=_PATTERNS[xf.background.fill_pattern])
        if xf.background.fill_pattern:
            fill.fgColor = legacy_color(book, xf.background.pattern_colour_index)
            fill.bgColor = legacy_color(book, xf.background.background_colour_index)
        mapped_alignment = Alignment(
            horizontal=_HORIZ[alignment.hor_align],
            vertical=_VERT[alignment.vert_align],
            textRotation=alignment.rotation,
            wrapText=bool(alignment.text_wrapped),
            shrinkToFit=bool(alignment.shrink_to_fit),
            indent=alignment.indent_level,
            readingOrder=alignment.text_direction,
        )
        protection = Protection(
            locked=bool(xf.protection.cell_locked), hidden=bool(xf.protection.formula_hidden)
        )
        return (
            mapped_font,
            fill,
            mapped_border,
            mapped_alignment,
            book.format_map[xf.format_key].format_str,
            protection,
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise ReviewedExcelError("旧 XLS 存在尚不能精确映射的单元格格式") from exc


def assign_style(target, mapped):
    (
        target.font,
        target.fill,
        target.border,
        target.alignment,
        target.number_format,
        target.protection,
    ) = mapped
