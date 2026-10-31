"""Preserve supported, source-bound conditional formats and filters in sheet slices.

Coordinates are never translated or clipped. An entire multi-range duplicate
comparison set belongs to one document or is rejected; disjoint objects are
explicitly excluded from that derivative, not removed from the source.
"""

from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree as XML
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree as SAFE
from defusedxml.common import DefusedXmlException

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_drawing import (
    R,
    S,
    _relations,
    drawing_bounds,
    rectangles_cover,
)
from app.application.reviewed_excel_evidence import bounded_range

_WPS_FOLLOW = "{http://www.wps.cn/officeDocument/2017/etCustomData}filterBottomFollowUsedRange"


def _fail(message):
    raise ReviewedExcelError("区域规则无法保真提取：" + message)


def _xml(data):
    try:
        return SAFE.fromstring(data, forbid_dtd=True)
    except (XML.ParseError, DefusedXmlException) as exc:
        raise ReviewedExcelError("区域规则 XML 不安全或损坏") from exc


def _package(body):
    if not body or len(body) > 20 * 1024 * 1024:
        _fail("文件大小超限")
    try:
        archive = ZipFile(BytesIO(body))
    except BadZipFile as exc:
        raise ReviewedExcelError("区域规则 ZIP 损坏") from exc
    entries = archive.infolist()
    if (
        len(entries) > 5000
        or len({e.filename for e in entries}) != len(entries)
        or sum(e.file_size for e in entries) > 100 * 1024 * 1024
    ):
        archive.close()
        _fail("ZIP 部件重复或解压大小超限")
    return archive


def _sheet(archive, name):
    root = _xml(archive.read("xl/workbook.xml"))
    links = _relations(archive, "xl/workbook.xml")
    matches = [s for s in root.findall(f"{{{S}}}sheets/{{{S}}}sheet") if s.get("name") == name]
    if len(matches) != 1:
        _fail("工作表身份不唯一")
    link = links.get(matches[0].get(f"{{{R}}}id"))
    if not link or link[0] != f"{R}/worksheet":
        _fail("工作表关系无效")
    return link[1], _xml(archive.read(link[1]))


def _fingerprint(node):
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        (node.text or "").strip(),
        tuple(_fingerprint(c) for c in node),
    )


def _bounds(value):
    try:
        bounds = bounded_range(value)
        if not (1 <= bounds[0] <= bounds[2] <= 16384 and 1 <= bounds[1] <= bounds[3] <= 1048576):
            _fail("规则范围越界")
        return bounds
    except (ValueError, TypeError):
        _fail("规则范围无效")


def _intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _blank_snapshot(body, sheet_name, tail):
    """Bounded read-only proof: no missing business data, objects or effective style."""
    from openpyxl import load_workbook

    from app.application.reviewed_excel_template import inspect_workbook

    if (tail[2] - tail[0] + 1) * (tail[3] - tail[1] + 1) > 20_000:
        _fail("空白上下文证明超出安全预算")
    review = inspect_workbook(body)
    for drawing in review.get("drawing_evidence", []):
        if drawing["sheet"] == sheet_name and _intersects(drawing_bounds(drawing), tail):
            _fail("空白上下文包含绘图")
    wb = load_workbook(BytesIO(body), data_only=False, keep_links=True, rich_text=True)
    try:
        ws = wb[sheet_name]
        if wb.defined_names or ws.defined_names or ws.data_validations.count or ws.tables:
            _fail("空白上下文存在尚未验证的区域依赖")
        if any(_intersects(_bounds(str(merge)), tail) for merge in ws.merged_cells.ranges):
            _fail("空白上下文包含合并单元格")
        for row in range(tail[1], tail[3] + 1):
            for col in range(tail[0], tail[2] + 1):
                cell = ws._cells.get((row, col))
                if cell is not None and (
                    cell.value is not None or cell.has_style or cell.comment or cell.hyperlink
                ):
                    _fail("空白上下文含值、公式、样式或关联对象")
        rows = []
        for index, dim in ws.row_dimensions.items():
            if tail[1] <= index <= tail[3]:
                # Cell/column inspection alone misses inherited row formats.
                # Only an entire-row FONT is admissible, with exact style/font
                # and geometry readback. Borders/fills/alignment/etc still fail.
                font_state = None
                if dim.has_style:
                    if any(list(dim._style)[1:]):
                        _fail("空白上下文继承非字体行样式")
                    font_state = (tuple(dim._style), _fingerprint(dim.font.to_tree()))
                rows.append(
                    (index, dim.height, dim.hidden, dim.outlineLevel, dim.collapsed, font_state)
                )
        cols = []
        for dim in ws.column_dimensions.values():
            if dim.min <= tail[2] and tail[0] <= dim.max:
                if dim.has_style:
                    _fail("空白上下文继承列样式")
                cols.append(
                    (dim.min, dim.max, dim.width, dim.hidden, dim.outlineLevel, dim.collapsed)
                )
        return {
            "rows": rows,
            "columns": cols,
            "sheet_format": dict(ws.sheet_format),
            "tail": tail,
        }
    finally:
        wb.close()


def _filter_blank_tail(body, sheet_name, area, rectangles, conditional_formats):
    """Only a rectangular right-hand tail, never missing rows or internal holes."""
    c1, r1, c2, r2 = _bounds(area)
    tail_col = c1
    while tail_col <= c2 and rectangles_cover((tail_col, r1, tail_col, r2), rectangles):
        tail_col += 1
    if tail_col == c1 or tail_col > c2:
        _fail("过滤器跨界不是可证明的纯空尾列")
    tail = (tail_col, r1, c2, r2)
    if any(_intersects(tail, rectangle) for rectangle in rectangles):
        _fail("过滤器跨界含未选内部区域，不是纯空尾列")
    if any(
        _intersects(_bounds(area), tail)
        for cf in conditional_formats
        for area in cf.get("sqref", "").split()
    ):
        _fail("过滤器未选尾列含条件格式依赖")
    return _blank_snapshot(body, sheet_name, tail)


def _uncovered_blank_proofs(body, sheet_name, bounds, rectangles):
    """Prove every cell of bounds outside the selection is blank context; else fail closed."""
    if rectangles_cover(bounds, rectangles):
        return []
    proofs = []
    # Fully outside the selection: the whole rectangle must be blank context.
    if not any(_intersects(bounds, rectangle) for rectangle in rectangles):
        return [_blank_snapshot(body, sheet_name, bounds)]
    # Partial overlap: prefer a verified empty right-hand strip (filter-compatible).
    c1, r1, c2, r2 = bounds
    covered_prefix = c1
    while covered_prefix <= c2 and rectangles_cover(
        (covered_prefix, r1, covered_prefix, r2), rectangles
    ):
        covered_prefix += 1
    if covered_prefix > c1 and covered_prefix <= c2:
        right = (covered_prefix, r1, c2, r2)
        if not any(_intersects(right, rectangle) for rectangle in rectangles):
            proofs.append(_blank_snapshot(body, sheet_name, right))
            remainder = (c1, r1, covered_prefix - 1, r2)
            if rectangles_cover(remainder, rectangles):
                return proofs
    # Bottom empty strip when rows below the covered band are blank.
    covered_rows = r1
    while covered_rows <= r2 and rectangles_cover((c1, covered_rows, c2, covered_rows), rectangles):
        covered_rows += 1
    if covered_rows > r1 and covered_rows <= r2:
        bottom = (c1, covered_rows, c2, r2)
        if not any(_intersects(bottom, rectangle) for rectangle in rectangles):
            proofs.append(_blank_snapshot(body, sheet_name, bottom))
            remainder = (c1, r1, c2, covered_rows - 1)
            if rectangles_cover(remainder, rectangles):
                return proofs
    _fail("条件格式涉及未选中的真实数据或无法证明的空白上下文")


def plan_range_objects(body, sheet_name, fragments):
    rectangles = [_bounds(part["range"]) for part in fragments]
    if any(part["sheet"] != sheet_name for part in fragments) or not rectangles:
        _fail("文档片段不属于同一工作表")

    def disposition(ranges):
        bounds = [_bounds(area) for area in ranges]
        if all(rectangles_cover(b, rectangles) for b in bounds):
            return "retained"
        if any(
            a <= x2 and x1 <= c and b <= y2 and y1 <= d
            for a, b, c, d in bounds
            for x1, y1, x2, y2 in rectangles
        ):
            _fail("规则或过滤范围跨越所选文档边界，不能缩小比较范围")
        return "excluded"

    with _package(body) as archive:
        _, sheet = _sheet(archive, sheet_name)
        style_root = _xml(archive.read("xl/styles.xml"))
        dxfs = style_root.find(f"{{{S}}}dxfs")
        formats = list(dxfs) if dxfs is not None else []
        nodes = {"conditionalFormatting": [], "autoFilter": []}
        originals = {name: list(sheet.findall(f"{{{S}}}{name}")) for name in nodes}
        receipt = {"sheet": sheet_name, "retained": [], "excluded": []}
        used_styles = {}
        tail_proofs = []
        for cf in originals["conditionalFormatting"]:
            if set(cf.attrib) != {"sqref"} or not len(cf) or (cf.text or "").strip():
                _fail("条件格式属性尚不支持")
            ranges = cf.get("sqref", "").split()
            if not ranges:
                _fail("条件格式缺少范围")
            bounds_list = [_bounds(area) for area in ranges]
            blank_proofs = []
            if all(rectangles_cover(b, rectangles) for b in bounds_list):
                kind = "retained"
            elif not any(
                a <= x2 and x1 <= c and b <= y2 and y1 <= d
                for a, b, c, d in bounds_list
                for x1, y1, x2, y2 in rectangles
            ):
                kind = "excluded"
            else:
                # Partial involvement: blank context outside selection may stay; real data fails.
                for area_bounds in bounds_list:
                    blank_proofs.extend(
                        _uncovered_blank_proofs(body, sheet_name, area_bounds, rectangles)
                    )
                kind = "retained"
                tail_proofs.extend(blank_proofs)
            for rule in cf:
                if (
                    rule.tag != f"{{{S}}}cfRule"
                    or rule.get("type") != "duplicateValues"
                    or len(rule)
                    or (rule.text or "").strip()
                    or set(rule.attrib) - {"type", "dxfId", "priority", "stopIfTrue"}
                    or rule.get("stopIfTrue", "0") not in {"0", "1", "true", "false"}
                ):
                    _fail("仅支持无公式、无未知扩展的 duplicateValues 条件格式")
                if (
                    not rule.get("priority", "").isdecimal()
                    or len(rule.get("priority")) > 10
                    or not 1 <= int(rule.get("priority")) <= 2147483647
                ):
                    _fail("条件格式优先级无效")
                if "dxfId" in rule.attrib:
                    raw_id = rule.get("dxfId", "")
                    if not raw_id.isdecimal() or len(raw_id) > 10 or int(raw_id) >= len(formats):
                        _fail("差异样式映射无效")
                    index = int(raw_id)
                    dxf = formats[index]
                    if (
                        dxf.attrib
                        or any(c.tag not in {f"{{{S}}}font", f"{{{S}}}fill"} for c in dxf)
                        or any(c.tag == f"{{{S}}}extLst" for c in dxf.iter())
                    ):
                        _fail("差异样式仅支持已核验字体与填充")
                    used_styles[index] = deepcopy(dxf)
                entry = {
                    "type": "duplicateValues",
                    "ranges": ranges,
                    "priority": int(rule.get("priority")),
                }
                if blank_proofs:
                    entry["reason"] = (
                        "source_verified_blank_conditional_context_preserved_without_expanding_business_fragments"
                    )
                    entry["blank_context_rects"] = [list(p["tail"]) for p in blank_proofs]
                receipt[kind].append(entry)
            if kind == "retained":
                nodes["conditionalFormatting"].append(deepcopy(cf))
        if len(originals["autoFilter"]) > 1:
            _fail("过滤器重复")
        for af in originals["autoFilter"]:
            if (
                set(af.attrib) - {"ref", _WPS_FOLLOW}
                or not af.get("ref")
                or (_WPS_FOLLOW in af.attrib and af.get(_WPS_FOLLOW) != "0")
                or any(
                    c.tag != f"{{{S}}}extLst" or c.attrib or len(c) or (c.text or "").strip()
                    for c in af
                )
            ):
                _fail("过滤条件、排序或未知过滤扩展尚未核验")
            bounds = _bounds(af.get("ref"))
            evidence = None
            if not rectangles_cover(bounds, rectangles) and any(
                _intersects(bounds, r) for r in rectangles
            ):
                evidence = _filter_blank_tail(
                    body, sheet_name, af.get("ref"), rectangles, originals["conditionalFormatting"]
                )
                tail_proofs.append(evidence)
                kind = "retained"
            else:
                kind = disposition([af.get("ref")])
            entry = {"type": "autoFilter", "ranges": [af.get("ref")]}
            if evidence is not None:
                entry["reason"] = (
                    "source_verified_empty_filter_tail_preserved_without_expanding_business_fragments"
                )
                entry["blank_tail_bounds"] = list(evidence["tail"])
                entry["preserved_row_font_only_rows"] = [
                    row[0] for row in evidence["rows"] if row[-1] is not None
                ]
                entry["verified_empty_cells"] = (bounds[3] - bounds[1] + 1) * (
                    bounds[2] - evidence["tail"][0] + 1
                )
                entry["checks"] = [
                    "no_values_or_formulas",
                    "no_cell_or_column_styles_or_nonfont_row_styles",
                    "inherited_row_font_and_geometry_exact_readback",
                    "no_merges",
                    "no_drawings",
                    "no_links_or_comments",
                    "no_other_range_dependencies",
                    "source_row_column_geometry_unchanged",
                ]
            receipt[kind].append(entry)
            if kind == "retained":
                nodes["autoFilter"].append(deepcopy(af))
        return {
            "sheet": sheet_name,
            "nodes": nodes,
            "originals": originals,
            "styles": used_styles,
            "tail_proofs": tail_proofs,
            "receipt": receipt,
        }


def verify_range_objects(body, plan):
    for proof in plan.get("tail_proofs", []):
        if _blank_snapshot(body, plan["sheet"], proof["tail"]) != proof:
            _fail("空白上下文或源尺寸读回不一致")
    with _package(body) as archive:
        _, sheet = _sheet(archive, plan["sheet"])
        for name, expected in plan["nodes"].items():
            actual = sheet.findall(f"{{{S}}}{name}")
            if list(map(_fingerprint, actual)) != list(map(_fingerprint, expected)):
                _fail("规则/过滤器完整 XML 读回不一致")
        style_root = _xml(archive.read("xl/styles.xml"))
        dxfs = style_root.find(f"{{{S}}}dxfs")
        for index, expected in plan["styles"].items():
            if (
                dxfs is None
                or index >= len(dxfs)
                or _fingerprint(dxfs[index]) != _fingerprint(expected)
            ):
                _fail("差异样式字体/填充或索引读回不一致")


def restore_range_objects(body, plan):
    """Reinsert only admitted source nodes, preserving WPS attributes verbatim."""
    if not any(plan["originals"].values()):
        return body
    output = BytesIO()
    with _package(body) as archive:
        part, sheet = _sheet(archive, plan["sheet"])
        for name, replacements in plan["nodes"].items():
            current = sheet.findall(f"{{{S}}}{name}")
            original = plan["originals"][name]
            # CF serialization must preserve every original rule before exclusions.
            # Only the known passive WPS filter metadata is restored after openpyxl.
            if name == "conditionalFormatting" and list(map(_fingerprint, current)) != list(
                map(_fingerprint, original)
            ):
                _fail("条件格式保存时改变，未覆盖异常结果")
            if bool(current) != bool(original):
                _fail("规则/过滤器保存时缺失")
            if not current:
                continue
            position = list(sheet).index(current[0])
            for node in current:
                sheet.remove(node)
            for offset, node in enumerate(replacements):
                sheet.insert(position + offset, deepcopy(node))
        with ZipFile(output, "w") as target:
            for entry in archive.infolist():
                target.writestr(
                    entry,
                    XML.tostring(sheet, encoding="utf-8", xml_declaration=True)
                    if entry.filename == part
                    else archive.read(entry.filename),
                )
    result = output.getvalue()
    verify_range_objects(result, plan)
    return result


def require_cleanable_range_metadata(body):
    """Cleaning is separate from lossless slicing; do not silently drop WPS nodes."""
    with _package(body) as archive:
        workbook = _xml(archive.read("xl/workbook.xml"))
        for entry in workbook.findall(f"{{{S}}}sheets/{{{S}}}sheet"):
            _, sheet = _sheet(archive, entry.get("name"))
            for node in sheet.findall(f"{{{S}}}autoFilter"):
                if (
                    any(name.startswith("{") for name in node.attrib)
                    or node.find(f"{{{S}}}extLst") is not None
                ):
                    _fail(
                        "此文件筛选器含需原始 XML 保留的元数据，切片可下载；清理/模板保存尚未支持，未改写文件"
                    )
