import json
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Color, Font, PatternFill, Side

from app.infrastructure.excel.cell_visual_facts import (
    preview_layout, workbook_visual_context, worksheet_visual_facts,
)


def test_native_geometry_and_style_roundtrip():
    book = Workbook()
    sheet = book.active
    sheet['A1'], sheet['B1'] = '表头', 0
    for address in ('A1', 'B1', 'XFD1048576'):
        cell = sheet[address]
        cell.font = Font(name='Arial', sz=16, bold=True, italic=True, family=2, color=Color(theme=4, tint=0.25))
        cell.fill = PatternFill('solid', fgColor=Color(indexed=5))
        cell.border = Border(top=Side(style='thin', color='FF123456'), right=Side(style='medium'))
        cell.alignment = Alignment(horizontal='center', wrap_text=True)
        cell.number_format = '0.00'
    sheet.row_dimensions[1].height = 27
    sheet.row_dimensions[8].hidden = True
    sheet.column_dimensions.group('C', 'F', outline_level=2, hidden=True)
    sheet.column_dimensions['C'].width = 23
    sheet.sheet_format.defaultColWidth = 12
    sheet.merge_cells('A3:B4')
    sheet.conditional_formatting.add('A1:B1', CellIsRule(operator='greaterThan', formula=['1'], font=Font(bold=True)))
    other = book.create_sheet('Hidden')
    other.sheet_state = 'veryHidden'
    data = BytesIO()
    book.save(data)
    data.seek(0)
    with ZipFile(data) as archive:
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        raw = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        assert {c.attrib['r'] for c in raw.findall('.//s:c', ns)} == {'A1', 'B1', 'XFD1048576'}
        assert raw.find('.//s:col', ns).get('width') == '23'
        assert raw.find('.//s:mergeCell', ns).get('ref') == 'A3:B4'
    data.seek(0)
    loaded = load_workbook(data)
    try:
        sheet = loaded.active
        before = (set(sheet._cells), set(sheet.row_dimensions), set(sheet.column_dimensions), len(loaded._cell_styles))
        facts = worksheet_visual_facts(sheet)
        cells = {item['address']: item for item in facts['cells']}
        assert set(cells) == {'A1', 'B1', 'XFD1048576'}
        assert cells['XFD1048576']['blank'] and len({item['style'] for item in cells.values()}) == 1
        style = facts['styles'][cells['A1']['style']]
        assert style['font']['color'] == {'type': 'theme', 'value': 4, 'tint': 0.25}
        assert style['font']['name'] == 'Arial' and style['font']['size_pt'] == 16
        assert style['font']['bold'] and style['font']['italic'] and style['font']['family'] == 2
        assert style['fill']['foreground']['type'] == 'indexed' and style['fill']['foreground']['value'] == 5
        assert style['number_format'] == '0.00' and 'wrapText="1"' in style['alignment']['xml']
        assert style['border']['sides']['right'] == 'medium' and 'FF123456' in style['border']['xml']
        assert facts['merges'] == ['A3:B4']
        assert facts['dimensions']['rows'][0]['height_pt'] == 27
        assert facts['dimensions']['rows'][1]['hidden']
        col = facts['dimensions']['columns'][0]
        assert (col['start'], col['end'], col['width_chars'], col['hidden'], col['outline_level']) == (3, 6, 23, True, 2)
        assert facts['dimensions']['default_column_width_chars'] == 12
        assert facts['conditional_formatting'][0]['range'] == 'A1:B1'
        assert 'greaterThan' in facts['conditional_formatting'][0]['rule_xml']
        assert facts['conditional_formatting'][0]['differential_style_xml']
        assert facts['neighbor_candidates'] == [{'axis': 'horizontal', 'from': 'A1', 'to': 'B1', 'gap': 0, 'same_style': True, 'facing_borders': ['medium', None], 'continuous_sides': ['top']}]
        assert workbook_visual_context(loaded)['theme_xml']
        assert worksheet_visual_facts(loaded['Hidden'])['sheet_state'] == 'veryHidden'
        assert not facts['rendered']
        json.dumps(facts)
        preview = preview_layout(sheet, {}, str, 4, 6)
        assert preview['widths'] == [12, 12, 23, 23, 23, 23]
        assert preview['rows'][0]['height'] == 27
        assert preview['rows'][0]['cells'][0]['font_size'] == 16
        assert preview['rows'][2]['cells'][0]['rowspan'] == 2
        assert preview['truncated']
        assert before == (set(sheet._cells), set(sheet.row_dimensions), set(sheet.column_dimensions), len(loaded._cell_styles))
    finally:
        loaded.close()


def test_sparse_gaps_and_blank_preview():
    book = Workbook()
    sheet = book.active
    sheet['A1'], sheet['XFD1'] = False, 'end'
    facts = worksheet_visual_facts(sheet)
    edge = facts['neighbor_candidates'][0]
    assert edge['gap'] == 16382 and edge['facing_borders'] is None and not edge['continuous_sides']
    assert len(facts['cells']) == 2
    assert preview_layout(sheet, {}, str, 1, 2)['rows'][0]['cells'][0]['value'] == 'False'
    assert set(sheet._cells) == {(1, 1), (1, 16384)}
