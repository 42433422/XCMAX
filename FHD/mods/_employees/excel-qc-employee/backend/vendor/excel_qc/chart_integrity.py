"""Independently check chart sources against the template and ordered plan."""

from collections import Counter
from copy import deepcopy

from openpyxl.chart import Reference
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils.cell import quote_sheetname

from .plan_coordinates import insertions, plan_phases, reference_sheet, shift_formula_rows
from .three_dimensional import affected_three_dimensional


def _sources(chart):
    result = []

    def visit(node, path):
        if node.tag.rsplit("}", 1)[-1] == "f":
            result.append((path, node.text))
        siblings = Counter()
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            index = siblings[tag]
            siblings[tag] += 1
            visit(child, path + ((tag, index),))

    # openpyxl's serializer sets plot_area/idx_base; leave the workbook untouched.
    visit(deepcopy(chart)._write(), ())
    return tuple(result)


def _affected(value, owner, target, row, count, sheets):
    expression = "=" + str(value).lstrip("=")
    if affected_three_dimensional(expression, sheets, target, row):
        return True
    if shift_formula_rows(expression, owner, [(target, row, count)]) != expression:
        return True
    tokens = Tokenizer(expression).items
    calls = [
        token.value[:-1].upper()
        for token in tokens
        if token.type == "FUNC" and token.subtype == "OPEN"
    ]
    if not calls:
        return False
    if "INDIRECT" in calls:
        return True
    owners = []
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        sheet, prefix, _ = reference_sheet(token.value, owner)
        if not prefix:
            owners.append(True)  # An unqualified name may also have workbook scope.
        elif sheet is not None:
            owners.append(sheet.casefold() == target.casefold())
        elif "[" in prefix or "]" in prefix:
            owners.append(False)
        else:
            owners.append(affected_three_dimensional(prefix + "A1", sheets, target, 1))
    return not owners or any(owners)


def _declared_sources(phase):
    prefix = quote_sheetname(phase["source_sheet"]) + "!"
    values = [
        str(Reference(range_string=prefix + phase[key].upper()))
        for key in ("categories", "bar_values", "categories", "line_values")
    ]
    return tuple(((), value) for value in values)


def check_inserted_charts(wb, template_wb, plan, finding):
    try:
        # Each entry is (original reference paths, declared addition). Original
        # roles/order must stay intact; native-chart QC validates new chart roles.
        expected = {
            sheet.title: [(_sources(chart), False) for chart in sheet._charts]
            for sheet in template_wb.worksheets
        }
        sheets = list(template_wb.sheetnames)
        for phase in plan_phases(plan):
            for target, row, count in insertions({"phases": [phase]}):
                for owner, charts in expected.items():
                    for sources, _ in charts:
                        if any(
                            _affected(value, owner, target, row, count, sheets)
                            for _, value in sources
                        ):
                            finding.fail(
                                "图表来源引用受插行影响，暂不支持迁移", sheet=owner, target=target
                            )
            kind = phase.get("phase")
            if kind in {"remove_sheets", "retain_sheets"}:
                named = {str(name).strip() for name in phase.get("names") or []}
                sheets = [name for name in sheets if (name in named) == (kind == "retain_sheets")]
                expected = {name: charts for name, charts in expected.items() if name in sheets}
            elif kind == "create_combo_chart":
                owner = phase["sheet"]
                if owner in expected:
                    finding.fail("声明图表没有使用新的工作表", sheet=owner)
                    continue
                expected[owner] = [(_declared_sources(phase), True)]
                sheets.append(owner)
        for sheet in wb.worksheets:
            charts = expected.get(sheet.title, [])
            if len(charts) != len(sheet._charts):
                finding.fail("图表缺失或出现未声明新增", sheet=sheet.title)
                continue
            for chart, (original, declared) in zip(sheet._charts, charts):
                actual = _sources(chart)
                matches = (
                    Counter(value for _, value in actual) == Counter(value for _, value in original)
                    if declared
                    else actual == original
                )
                if not matches:
                    finding.fail("图表来源引用改变、缺失或出现未声明追加", sheet=sheet.title)
        for name, charts in expected.items():
            if charts and name not in wb.sheetnames:
                finding.fail("图表所属工作表未经声明删除", sheet=name)
    except (KeyError, TypeError, ValueError, AttributeError, TokenizerError) as exc:
        finding.fail("图表来源引用无法独立核验", reason=str(exc))
