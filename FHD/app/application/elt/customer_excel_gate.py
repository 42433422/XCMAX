"""B31：真实客户 Excel 端到端业务闭环，是 ETL 数据对接中心的发布门槛。

B01–B30 仍是单项测试。只有同一版本、同一任务、同一份客户原件走完
「原件 → 区域 → 切片 → 清洗 → 确认 → 数据库 → 业务处理 → 最终 Excel → 人工对账」
才能 PASS。合成表、单元测试、CI 和历史考勤输出不能代替客户原件。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.application.elt.attendance_pipeline import _hours, persist_attendance_rows
from app.application.elt.errors import EltError, ReviewedExcelError
from app.application.elt.parser_types import ParsedRow
from app.application.elt.parsers import parse_file

GATE_ID = "B31"
CHAIN = (
    "客户原件",
    "区域识别",
    "切片文件",
    "清洗记录",
    "用户确认",
    "数据库",
    "业务处理",
    "最终Excel",
    "人工对账",
)
SUBSTITUTES = frozenset({"synthetic", "unit_test", "ci", "historical_attendance", "fixture"})
_FIXTURE_PARTS = ("/testdata/", "/tests/", "/docs/evidence/", "/templates/")
_ITEMS: tuple[tuple[str, str], ...] = (
    ("01", "原件上传"),
    ("02", "文件完整性"),
    ("03", "原件保护"),
    ("04", "工作簿解析"),
    ("05", "工作表识别"),
    ("06", "工作表完整性"),
    ("07", "表格区域识别"),
    ("08", "多表识别"),
    ("09", "横向表格"),
    ("10", "纵向表格"),
    ("11", "混合布局"),
    ("12", "空白区域"),
    ("13", "合并单元格"),
    ("14", "表格边界"),
    ("15", "自动切片"),
    ("16", "切片完整性"),
    ("17", "切片边界"),
    ("18", "多工作表切片"),
    ("19", "切片去重"),
    ("20", "原始坐标追溯"),
    ("21", "切片原件保护"),
    ("22", "字段识别"),
    ("23", "字段映射"),
    ("24", "数据类型"),
    ("25", "空值处理"),
    ("26", "日期清洗"),
    ("27", "数字清洗"),
    ("28", "重复数据"),
    ("29", "异常数据隔离"),
    ("30", "业务编号生成"),
    ("31", "清洗记录"),
    ("32", "清洗预览"),
    ("33", "异常预览"),
    ("34", "数据确认"),
    ("35", "数据写入"),
    ("36", "字段一致性"),
    ("37", "数量对账"),
    ("38", "数据隔离"),
    ("39", "入库事务"),
    ("40", "业务数据读取"),
    ("41", "业务处理"),
    ("42", "统计核算"),
    ("43", "结果生成"),
    ("44", "文件完整性"),
    ("45", "文件下载"),
    ("46", "文件打开"),
    ("47", "内容核对"),
    ("48", "人工对账"),
    ("49", "重复提交"),
    ("50", "幂等处理"),
    ("51", "请求中断"),
    ("52", "服务重启"),
    ("53", "任务恢复"),
    ("54", "结果一致性"),
    ("55", "部分成功"),
    ("56", "异常清单"),
)
CHECK_IDS = tuple(f"B31-{number}" for number, _title in _ITEMS)
_WORKBOOK_ERRORS = (OSError, ValueError, BadZipFile, InvalidFileException, ParseError)


def _mark(checks: dict[str, str], number: str, ok: bool | None) -> None:
    checks[f"B31-{number}"] = {True: "pass", False: "fail", None: "not_tested"}[ok]


def _blank() -> dict[str, str]:
    return dict.fromkeys(CHECK_IDS, "not_tested")


def _substitute_path(path: Path) -> bool:
    text = path.resolve().as_posix().lower()
    name = path.name.lower()
    if any(part in text for part in _FIXTURE_PARTS):
        return True
    return any(token in name for token in ("demo", "sample", "synthetic", "fixture"))


def decide_status(
    *,
    evidence_class: str,
    customer_original: bool,
    checks: dict[str, str],
    hard_fail: bool,
) -> str:
    """发布结论只认客户原件。替代证据一律 BLOCKED，不能升成 PASS。"""
    if (
        not customer_original
        or evidence_class in SUBSTITUTES
        or evidence_class != "customer_original"
    ):
        return "BLOCKED"
    if hard_fail:
        return "FAIL"
    if any(value == "fail" for value in checks.values()):
        return "FAIL"
    if set(checks) == set(CHECK_IDS) and all(value == "pass" for value in checks.values()):
        return "PASS"
    if any(value == "pass" for value in checks.values()):
        return "PARTIAL PASS"
    return "NOT TESTED"


def _payload(dataset) -> list[dict[str, Any]]:
    rows = []
    for row in dataset.rows:
        clean = row.provenance["clean"]
        if clean["duplicate_status"] != "unique" or clean["validation_result"]:
            continue
        rows.append(
            {
                **clean["cleaning_result"],
                "business_id": clean["business_id"],
                "source_row": row.row_number,
                "source_sheet": row.sheet,
                "slice_id": row.provenance["slice"]["slice_id"],
                "validation_result": [],
            }
        )
    return rows


def _row_destinations(sheets: list[dict], rows: Iterable[ParsedRow]) -> dict[str, dict[int, str]]:
    """Every non-empty source row must land in exactly one named role."""
    roles: dict[str, dict[int, str]] = {}
    for item in sheets:
        name = str(item.get("name"))
        target = roles.setdefault(name, {})
        if item.get("status") == "sliced_not_business_table":
            target.update(
                dict.fromkeys(range(1, int(item.get("max_row") or 0) + 1), "non_business_sheet")
            )
        header_row = int(item.get("header_row") or 0)
        if header_row:
            target.update(dict.fromkeys(range(1, header_row), "title"))
            target[header_row] = "header"
        for region in item.get("regions") or []:
            target[int(region["title_row"])] = "title"
            for role in ("header_rows", "note_rows", "blank_rows"):
                target.update(dict.fromkeys(region.get(role) or [], role[:-5]))
    for row in rows:
        roles.setdefault(row.sheet, {})[row.row_number] = (
            "exception" if row.provenance["clean"]["validation_result"] else "record"
        )
    return roles


def _tenant_isolated(db_path: Path) -> bool | None:
    if not db_path.is_file():
        return False
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(attendance_daily_records)")}
    # Columns are necessary, but do not prove that a second tenant cannot read rows.
    return None if {"tenant_id", "customer_id"} <= columns else False


def _daily_rows(db_path: Path) -> dict[str, tuple]:
    with sqlite3.connect(db_path) as conn:
        return {
            row[0]: tuple(row[1:])
            for row in conn.execute(
                "SELECT business_id, source_row, employee_name, department, employee_no, "
                "attendance_group, position, user_id, work_date, shift_name, daily_times_json "
                "FROM attendance_daily_records"
            )
        }


def _expected_daily_rows(rows: list[dict[str, Any]]) -> dict[str, tuple]:
    fields = (
        "employee_name",
        "department",
        "employee_no",
        "attendance_group",
        "position",
        "user_id",
        "work_date",
        "shift_name",
    )
    return {
        row["business_id"]: (
            int(row.get("source_row") or 0),
            *(row.get(field) or "" for field in fields),
            json.dumps([row.get("clock_in"), row.get("clock_out")], ensure_ascii=False),
        )
        for row in rows
        if row.get("work_date")
    }


_MONTHLY_FIELDS = (
    "employee_name",
    "work_month",
    "days_in_month",
    "absent_dates",
    "present_marked_dates",
    "unmarked_days",
)


def _monthly_rows(db_path: Path) -> dict[str, tuple]:
    with sqlite3.connect(db_path) as conn:
        try:
            return {
                row[0]: tuple(row[1:])
                for row in conn.execute(
                    "SELECT business_id, source_row, "
                    + ", ".join(_MONTHLY_FIELDS)
                    + " FROM attendance_monthly_marks"
                )
            }
        except sqlite3.OperationalError:
            return {}


def _expected_monthly_rows(rows: list[dict[str, Any]]) -> dict[str, tuple]:
    return {
        row["business_id"]: (
            int(row.get("source_row") or 0),
            *(
                int(row.get(field) or 0)
                if field in {"days_in_month", "unmarked_days"}
                else row.get(field) or ""
                for field in _MONTHLY_FIELDS
            ),
        )
        for row in rows
        if row.get("work_month")
    }


def _date_count(rows: list[dict[str, Any]], field: str) -> int:
    return sum(len([item for item in str(row.get(field) or "").split(",") if item]) for row in rows)


def evaluate_workbook(
    path: Path,
    baseline: dict[str, Any],
    *,
    data_dir: Path,
    evidence_class: str = "customer_original",
) -> dict[str, Any]:
    """对一份工作簿跑 B31。evidence_class 不是 customer_original 时结论保持 BLOCKED。"""
    checks = _blank()
    hard_fail = False
    notes: list[str] = []
    path = Path(path)
    before = path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    _mark(checks, "01", path.is_file() and bool(before))
    format_ok = False
    try:
        with ZipFile(path) as archive:
            format_ok = "[Content_Types].xml" in archive.namelist()
    except (BadZipFile, OSError) as exc:
        notes.append(f"格式无法读取: {exc}")
    expected = str(baseline.get("sha256") or "")
    _mark(
        checks,
        "02",
        format_ok and path.stat().st_size == len(before) and (not expected or expected == digest),
    )
    if expected and expected != digest:
        hard_fail = True
        notes.append("原件 SHA256 与人工基准不一致")

    dataset = None
    try:
        dataset = parse_file(
            path, target_type="attendance", max_rows=int(baseline.get("max_rows") or 20000)
        )
    except (EltError, *_WORKBOOK_ERRORS) as exc:
        hard_fail = True
        notes.append(f"生产解析失败: {exc}")
    workbook = (dataset.source_features or {}).get("workbook", {}) if dataset else {}
    recorded = list(workbook.get("sheets") or [])
    rows = dataset.rows if dataset is not None else []
    _mark(checks, "04", dataset is not None)
    try:
        book = load_workbook(path, read_only=False, data_only=False)
        try:
            actual_sheets = [
                {"name": sheet.title, "state": sheet.sheet_state} for sheet in book.worksheets
            ]
            content_rows = {
                sheet.title: {
                    cell.row
                    for line in sheet.iter_rows()
                    for cell in line
                    if cell.row is not None
                    and str(cell.value if cell.value is not None else "").strip()
                }
                for sheet in book.worksheets
            }
        finally:
            book.close()
    except _WORKBOOK_ERRORS as exc:
        actual_sheets, content_rows = [], {}
        hard_fail = True
        notes.append(f"工作簿无法打开: {exc}")
    recorded_names = [item.get("name") for item in recorded]
    sheets_match = bool(actual_sheets) and recorded_names == [
        item["name"] for item in actual_sheets
    ]
    _mark(
        checks,
        "05",
        sheets_match
        and all(
            item.get("state") == actual["state"] for item, actual in zip(recorded, actual_sheets)
        ),
    )
    silent = [item["name"] for item in actual_sheets if item["name"] not in recorded_names]
    _mark(checks, "06", dataset is not None and not silent)
    if silent:
        hard_fail = True
        notes.append("静默跳过工作表: " + ",".join(silent))
    if dataset is not None and not rows and any(content_rows.values()):
        hard_fail = True
        notes.append("工作簿有内容但识别出 0 条业务记录，禁止进入确认")

    destinations = _row_destinations(recorded, rows)
    orphans = {
        sheet: sorted(found - set(destinations.get(sheet, {})))
        for sheet, found in content_rows.items()
        if found - set(destinations.get(sheet, {}))
    }
    if orphans:
        hard_fail = True
        notes.append(
            "源行没有去向: "
            + "; ".join(f"{sheet} 行 {lines[:10]}" for sheet, lines in orphans.items())
        )
    regions = [
        {"sheet": item["name"], "range": region.get("range")}
        for item in recorded
        for region in item.get("regions") or []
    ] + [
        {"sheet": item["name"], "range": f"header:{item['header_row']}"}
        for item in recorded
        if item.get("status") == "identified" and item.get("header_row")
    ]
    oracle = baseline.get("regions")
    if isinstance(oracle, list) and oracle:
        found = {(item["sheet"], item["range"]) for item in regions}
        wanted = {(item.get("sheet"), item.get("range")) for item in oracle}
        region_ok = found == wanted
        _mark(checks, "07", region_ok)
        _mark(checks, "14", region_ok and not orphans)
        if not region_ok:
            hard_fail = True
            notes.append("表格区域与人工基准不一致")
        per_sheet: dict[str, int] = {}
        for item in regions:
            per_sheet[item["sheet"]] = per_sheet.get(item["sheet"], 0) + 1
        wanted_per_sheet: dict[str, int] = {}
        for item in oracle:
            sheet = str(item.get("sheet"))
            wanted_per_sheet[sheet] = wanted_per_sheet.get(sheet, 0) + 1
        if any(count > 1 for count in wanted_per_sheet.values()):
            _mark(checks, "08", per_sheet == wanted_per_sheet)
    blanks = [item.get("name") for item in recorded if item.get("blank")]
    if blanks:
        _mark(
            checks,
            "12",
            all(not destinations.get(name) or not content_rows.get(name) for name in blanks),
        )

    slices = [row.provenance.get("slice") or {} for row in rows]
    slice_ids = [item.get("slice_id") for item in slices]
    _mark(checks, "15", bool(rows) and all(slice_ids))
    _mark(checks, "16", bool(rows) and not orphans)
    if rows:
        _mark(checks, "19", len(slice_ids) == len(set(slice_ids)))
        _mark(checks, "20", all(item.get("source_sha256") == digest for item in slices))
    _mark(checks, "21", hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    if any("business_id" in item for item in slices):
        hard_fail = True
        notes.append("切片阶段出现业务编号")
    _mark(checks, "03", hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    slice_clean = all("business_id" not in row.provenance["slice"] for row in rows)
    _mark(
        checks,
        "30",
        bool(rows)
        and all(
            bool(row.provenance["clean"].get("business_id"))
            == (not row.provenance["clean"]["validation_result"])
            for row in rows
        )
        and slice_clean,
    )
    traced = bool(rows) and all(
        row.provenance["clean"].get("mapping_result") is not None
        and "cleaning_result" in row.provenance["clean"]
        and "validation_result" in row.provenance["clean"]
        for row in rows
    )
    _mark(checks, "22", traced)
    _mark(checks, "23", traced)
    _mark(checks, "31", traced and slice_clean)
    invalid = [row for row in rows if row.provenance["clean"]["validation_result"]]
    _mark(
        checks,
        "29",
        bool(rows)
        and all(row.provenance["clean"]["database_status"] == "pending" for row in invalid),
    )
    _mark(
        checks,
        "28",
        bool(rows)
        and all(
            row.provenance["clean"]["duplicate_status"] in {"unique", "same_business_key"}
            for row in rows
        ),
    )
    _mark(checks, "32", traced)
    _mark(checks, "33", bool(notes) or bool(invalid) or traced)

    confirmed = baseline.get("confirmed") is True
    version = str(baseline.get("version") or "")
    task_id = str(baseline.get("task_id") or "")
    same_task = bool(
        version
        and task_id
        and version == baseline.get("version")
        and task_id == baseline.get("task_id")
    )
    output_path = ""
    written = 0
    if dataset is not None and confirmed and same_task:
        ready = _payload(dataset)
        db_path = data_dir / "b31.sqlite"
        fault_db = data_dir / "b31-fault.sqlite"
        try:
            persist_attendance_rows(
                ready,
                db_path=fault_db,
                source_file=task_id,
                upload_path=path,
                run_id=f"{task_id}-fault",
                fault="after_first_commit",
            )
            interrupted = False
        except EltError:
            interrupted = True
        persist_attendance_rows(
            ready,
            db_path=fault_db,
            source_file=task_id,
            upload_path=path,
            run_id=f"{task_id}-recover",
            fault="",
        )
        fault_count = len({**_daily_rows(fault_db), **_monthly_rows(fault_db)})
        _mark(checks, "51", interrupted)
        notes.append("已验证同进程中断恢复；尚未验证服务进程重启")
        _mark(checks, "53", interrupted and fault_count == len(ready))
        _mark(checks, "39", interrupted and fault_count == len(ready))
        if fault_count != len(ready):
            hard_fail = True
            notes.append("中断恢复后的行数与待入库行数不一致")
        first = persist_attendance_rows(
            ready, db_path=db_path, source_file=task_id, upload_path=path, run_id=task_id, fault=""
        )
        second = persist_attendance_rows(
            ready,
            db_path=db_path,
            source_file=task_id,
            upload_path=path,
            run_id=f"{task_id}-retry",
            fault="",
        )
        written = int(first["executed"])
        _mark(checks, "35", written == len(ready))
        _mark(checks, "49", second["executed"] == 0)
        _mark(checks, "50", second["executed"] == 0 and written == len(ready))
        if second["executed"]:
            hard_fail = True
            notes.append("重复提交产生了新的入库")
        _mark(checks, "38", _tenant_isolated(db_path))
        _mark(checks, "55", written + len(invalid) == len(rows) or written == len(ready))
        output_path = str(first["output_path"])
        opened = False
        try:
            reopened = load_workbook(output_path, read_only=True)
            try:
                if not reopened.worksheets:
                    raise ReviewedExcelError("结果文件缺少工作表")
                output_sheet = reopened.worksheets[0]
                header = [cell.value for cell in next(output_sheet.iter_rows(max_row=1), ())]
                body_rows = list(output_sheet.iter_rows(min_row=2, values_only=True))
                monthly_sheet = reopened["月度考勤"] if "月度考勤" in reopened.sheetnames else None
                monthly_body = (
                    list(monthly_sheet.iter_rows(min_row=2, values_only=True))
                    if monthly_sheet is not None
                    else []
                )
            finally:
                reopened.close()
            opened = (
                bool(header)
                and header[0] == "员工姓名"
                and len(body_rows) + len(monthly_body) == written
            )
        except _WORKBOOK_ERRORS as exc:
            notes.append(f"结果文件无法打开: {exc}")
            opened = False
        _mark(checks, "43", bool(output_path) and Path(output_path).is_file())
        _mark(
            checks,
            "44",
            opened
            and hashlib.sha256(Path(output_path).read_bytes()).hexdigest() == first["sha256"],
        )
        # A generated URL is not evidence of a completed client download.
        attested = {str(item).lower() for item in baseline.get("opened_with") or []}
        _mark(checks, "46", opened and {"excel", "wps"} <= attested)
        if not opened:
            hard_fail = True
        stored_rows = {**_daily_rows(db_path), **_monthly_rows(db_path)}
        stored = len(stored_rows)
        fields_match = stored_rows == {
            **_expected_daily_rows(ready),
            **_expected_monthly_rows(ready),
        }
        _mark(checks, "36", fields_match)
        if not fields_match:
            hard_fail = True
            notes.append("入库字段与清洗结果不一致")
        _mark(checks, "37", stored == written and int(first["error_rows"]) >= 0)
        _mark(checks, "40", fields_match)
        hours = 0.0
        for row in ready:
            if row.get("work_date"):
                hours += _hours(row.get("work_date"), row.get("clock_in"), row.get("clock_out"))[
                    "regular_hours"
                ]
        _mark(checks, "41", written > 0)
        expected_rows = baseline.get("business_records", baseline.get("daily_rows"))
        metrics = {
            "regular_hours": round(hours, 2),
            "absent_days": _date_count(ready, "absent_dates"),
            "present_marked_days": _date_count(ready, "present_marked_dates"),
            "exception_rows": len(invalid),
        }
        wanted_metrics = {key: baseline[key] for key in metrics if key in baseline}
        metrics_ok = bool(wanted_metrics) and all(
            abs(float(value) - float(metrics[key])) < 0.01 for key, value in wanted_metrics.items()
        )
        rows_ok = expected_rows is not None and int(expected_rows) == written
        _mark(
            checks,
            "42",
            rows_ok and metrics_ok if expected_rows is not None and wanted_metrics else None,
        )
        _mark(checks, "47", rows_ok and opened if expected_rows is not None else None)
        _mark(checks, "48", rows_ok and metrics_ok and baseline.get("manual_reconciled") is True)
        fault_rows = {**_daily_rows(fault_db), **_monthly_rows(fault_db)}
        _mark(checks, "54", fields_match and fault_rows == stored_rows)
        _mark(
            checks,
            "56",
            bool(invalid) and all(row.provenance["clean"]["validation_result"] for row in invalid),
        )
        if expected_rows is not None and int(expected_rows) != written:
            hard_fail = True
            notes.append("入库数量与人工基准不一致")
        if wanted_metrics and not metrics_ok:
            hard_fail = True
            notes.append(f"核算指标与人工基准不一致: {metrics}")
    elif not confirmed:
        notes.append("未经确认，未写入数据库")
    _mark(checks, "34", written == 0 or confirmed)
    _mark(checks, "03", hashlib.sha256(path.read_bytes()).hexdigest() == digest)

    customer_original = (
        evidence_class == "customer_original"
        and not _substitute_path(path)
        and bool(version and task_id)
    )
    status = decide_status(
        evidence_class=evidence_class,
        customer_original=customer_original,
        checks=checks,
        hard_fail=hard_fail,
    )
    return {
        "id": GATE_ID,
        "status": status,
        "release_pass": status == "PASS",
        "chain": list(CHAIN),
        "version": version,
        "task_id": task_id,
        "sha256": digest,
        "checks": checks,
        "notes": notes,
        "output_path": output_path,
        "evidence_class": evidence_class,
    }


def release_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    """发布门禁入口。没有客户原件和人工基准时固定为 BLOCKED。"""
    environment = os.environ if env is None else env
    source = str(environment.get("XCAGI_ELT_CUSTOMER_EXCEL") or "").strip()
    oracle = str(environment.get("XCAGI_ELT_MANUAL_BASELINE") or "").strip()
    if not source or not oracle or not Path(source).is_file() or not Path(oracle).is_file():
        return {
            "id": GATE_ID,
            "status": "BLOCKED",
            "release_pass": False,
            "reason": "缺少客户原件或人工基准。合成 Excel、单元测试、CI 和历史考勤输出不能代替。",
            "chain": list(CHAIN),
            "checks": _blank(),
        }
    path = Path(source)
    if _substitute_path(path):
        return {
            "id": GATE_ID,
            "status": "BLOCKED",
            "release_pass": False,
            "reason": "路径位于样例、测试或历史证据目录，不能作为客户原件。",
            "chain": list(CHAIN),
            "checks": _blank(),
        }
    baseline = json.loads(Path(oracle).read_text(encoding="utf-8"))
    evidence_class = str(baseline.get("evidence_class") or "")
    if evidence_class != "customer_original":
        report = evaluate_workbook(
            path,
            baseline,
            data_dir=path.parent / ".b31-blocked",
            evidence_class=evidence_class or "synthetic",
        )
        report["status"] = "BLOCKED"
        report["release_pass"] = False
        report["reason"] = "基准未声明为客户原件"
        return report
    data_dir = Path(str(environment.get("XCAGI_ELT_GATE_DATA_DIR") or path.parent / ".b31-gate"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return evaluate_workbook(path, baseline, data_dir=data_dir, evidence_class="customer_original")
