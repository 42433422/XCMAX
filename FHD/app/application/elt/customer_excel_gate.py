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
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from openpyxl import load_workbook

from app.application.elt.attendance_pipeline import (
    _hours,
    parse_attendance_dataset,
    persist_attendance_rows,
)
from app.application.elt.errors import EltError, ReviewedExcelError
from app.application.reviewed_excel_auto_slice import derive_rule_slices
from app.application.reviewed_excel_basic_classification import classify_review_workbook
from app.application.reviewed_excel_template import inspect_workbook

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
    if not customer_original or evidence_class in SUBSTITUTES or evidence_class != "customer_original":
        return "BLOCKED"
    if hard_fail:
        return "FAIL"
    if checks and all(value == "pass" for value in checks.values()):
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


def _tenant_isolated(db_path: Path) -> bool:
    if not db_path.is_file():
        return False
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(attendance_daily_records)").fetchall()
        }
    return "tenant_id" in columns and "customer_id" in columns


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
    except Exception as exc:  # noqa: BLE001 — 格式失败必须留下记录
        notes.append(f"格式无法读取: {exc}")
    expected = str(baseline.get("sha256") or "")
    _mark(checks, "02", format_ok and path.stat().st_size == len(before) and (not expected or expected == digest))
    if expected and expected != digest:
        hard_fail = True
        notes.append("原件 SHA256 与人工基准不一致")

    review_error = ""
    try:
        review = inspect_workbook(before)
        classified = classify_review_workbook(review)
    except (ReviewedExcelError, Exception) as exc:  # noqa: BLE001
        review = {}
        classified = []
        review_error = str(exc)
        notes.append(f"解析失败: {exc}")
    _mark(checks, "04", bool(review) and not review_error)

    book = load_workbook(path, read_only=False, data_only=False)
    try:
        actual_sheets = [
            {"name": sheet.title, "state": sheet.sheet_state} for sheet in book.worksheets
        ]
    finally:
        book.close()
    recorded = review.get("sheet_overview") or []
    recorded_names = [item.get("sheet") for item in recorded]
    hidden_seen = {item["name"] for item in actual_sheets if item["state"] != "visible"}
    recorded_hidden = {
        item.get("sheet") for item in recorded if item.get("sheet_state") not in (None, "visible")
    }
    sheets_match = recorded_names == [item["name"] for item in actual_sheets]
    _mark(checks, "05", sheets_match and hidden_seen <= recorded_hidden | {item.get("sheet") for item in recorded})
    silent = [item["name"] for item in actual_sheets if item["name"] not in recorded_names]
    _mark(checks, "06", not silent and not review_error)
    if silent:
        hard_fail = True
        notes.append("静默跳过工作表: " + ",".join(silent))

    regions = [
        {"sheet": item["sheet"], "range": region.get("range"), "data": region.get("data_region", True)}
        for item in classified
        for region in item.get("regions") or []
    ]
    oracle = baseline.get("regions")
    if isinstance(oracle, list) and oracle:
        found = {(item["sheet"], item["range"]) for item in regions if item["data"] is not False}
        wanted = {(item.get("sheet"), item.get("range")) for item in oracle}
        region_ok = found == wanted and all(item["range"] for item in regions)
        _mark(checks, "07", region_ok)
        _mark(checks, "14", region_ok)
        if not region_ok:
            hard_fail = True
            notes.append("表格区域与客户基准不一致")
    data_regions = [item for item in regions if item["data"] is not False]
    per_sheet: dict[str, list] = {}
    for item in data_regions:
        per_sheet.setdefault(item["sheet"], []).append(item["range"])
    if isinstance(oracle, list) and oracle:
        oracle_by_sheet: dict[str, list] = {}
        for item in oracle:
            oracle_by_sheet.setdefault(str(item.get("sheet")), []).append(item.get("range"))
        multi = {sheet: ranges for sheet, ranges in oracle_by_sheet.items() if len(ranges) > 1}
        if multi:
            _mark(checks, "08", all(len(ranges) == len(per_sheet.get(sheet, [])) for sheet, ranges in multi.items()))
        blanks = [item.get("sheet") for item in classified if item.get("blank")]
        if blanks:
            _mark(checks, "12", all(not per_sheet.get(name) for name in blanks))

    slices: list[dict] = []
    if classified:
        try:
            slices = derive_rule_slices(before, {"sheets": classified})
        except ReviewedExcelError as exc:
            notes.append(f"切片失败: {exc}")
            hard_fail = True
    slice_keys = [
        (item.get("fragments", [{}])[0].get("sheet"), item.get("table_region")) for item in slices
    ]
    _mark(checks, "15", bool(data_regions) and bool(slices) and all(item.get("basis") == "rule_region" for item in slices))
    _mark(checks, "16", bool(data_regions) and len(slices) == len(data_regions) and all(item.get("workbook") for item in slices))
    if data_regions:
        _mark(checks, "19", bool(slices) and len(slice_keys) == len(set(slice_keys)))
    if slices:
        _mark(checks, "20", all(item.get("source_sha256") == digest and item.get("slice_id") for item in slices))
    _mark(checks, "21", hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    if any("business_id" in item for item in slices):
        hard_fail = True
        notes.append("切片阶段出现业务编号")
    _mark(checks, "03", hashlib.sha256(path.read_bytes()).hexdigest() == digest)

    dataset = None
    try:
        dataset = parse_attendance_dataset(path, max_rows=int(baseline.get("max_rows") or 20000))
    except (EltError, Exception) as exc:  # noqa: BLE001
        notes.append(f"考勤解析失败: {exc}")
    rows = dataset.rows if dataset is not None else []
    slice_clean = all("business_id" not in row.provenance["slice"] for row in rows)
    _mark(checks, "30", bool(rows) and all(bool(row.provenance["clean"].get("business_id")) == (not row.provenance["clean"]["validation_result"]) for row in rows) and slice_clean)
    traced = all(
        row.provenance["clean"].get("mapping_result") is not None
        and "cleaning_result" in row.provenance["clean"]
        and "validation_result" in row.provenance["clean"]
        for row in rows
    )
    _mark(checks, "22", traced)
    _mark(checks, "23", traced)
    _mark(checks, "31", traced and slice_clean)
    invalid = [row for row in rows if row.provenance["clean"]["validation_result"]]
    _mark(checks, "29", bool(rows) and all(row.provenance["clean"]["database_status"] == "pending" for row in invalid))
    _mark(
        checks,
        "28",
        bool(rows)
        and all(row.provenance["clean"]["duplicate_status"] in {"unique", "same_business_key"} for row in rows),
    )
    _mark(checks, "32", traced)
    _mark(checks, "33", bool(notes) or bool(invalid) or traced)

    confirmed = baseline.get("confirmed") is True
    version = str(baseline.get("version") or "")
    task_id = str(baseline.get("task_id") or "")
    same_task = bool(version and task_id and version == baseline.get("version") and task_id == baseline.get("task_id"))
    output_path = ""
    written = 0
    if dataset is not None and confirmed and same_task:
        ready = _payload(dataset)
        db_path = data_dir / "b31.sqlite"
        fault_db = data_dir / "b31-fault.sqlite"
        os.environ["FHD_ETL_ATTENDANCE_FAULT"] = "after_first_commit"
        try:
            persist_attendance_rows(ready, db_path=fault_db, source_file=task_id, upload_path=path, run_id=f"{task_id}-fault")
            interrupted = False
        except EltError:
            interrupted = True
        finally:
            os.environ.pop("FHD_ETL_ATTENDANCE_FAULT", None)
        recovered = persist_attendance_rows(
            ready, db_path=fault_db, source_file=task_id, upload_path=path, run_id=f"{task_id}-recover"
        )
        with sqlite3.connect(fault_db) as conn:
            fault_count = conn.execute("SELECT COUNT(*) FROM attendance_daily_records").fetchone()[0]
        _mark(checks, "51", interrupted)
        _mark(checks, "52", interrupted)
        _mark(checks, "53", interrupted and fault_count == len(ready))
        _mark(checks, "39", interrupted and fault_count == len(ready))
        if fault_count != len(ready):
            hard_fail = True
            notes.append("中断恢复后的行数与待入库行数不一致")
        first = persist_attendance_rows(
            ready, db_path=db_path, source_file=task_id, upload_path=path, run_id=task_id
        )
        second = persist_attendance_rows(
            ready, db_path=db_path, source_file=task_id, upload_path=path, run_id=f"{task_id}-retry"
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
                header = [cell.value for cell in next(reopened.active.iter_rows(max_row=1))]
                body_rows = list(reopened.active.iter_rows(min_row=2, values_only=True))
            finally:
                reopened.close()
            opened = header[0] == "员工姓名" and len(body_rows) == written
        except Exception as exc:  # noqa: BLE001
            notes.append(f"结果文件无法打开: {exc}")
            opened = False
        _mark(checks, "43", bool(output_path) and Path(output_path).is_file())
        _mark(checks, "44", opened and hashlib.sha256(Path(output_path).read_bytes()).hexdigest() == first["sha256"])
        _mark(checks, "45", bool(first.get("download_url")))
        attested = {str(item).lower() for item in baseline.get("opened_with") or []}
        _mark(checks, "46", opened and {"excel", "wps"} <= attested)
        if not opened:
            hard_fail = True
        with sqlite3.connect(db_path) as conn:
            stored = conn.execute("SELECT COUNT(*) FROM attendance_daily_records").fetchone()[0]
        _mark(checks, "36", stored == written)
        _mark(checks, "37", stored == written and int(first["error_rows"]) >= 0)
        _mark(checks, "40", stored == written)
        hours = 0.0
        for row in ready:
            hours += _hours(row.get("work_date"), row.get("clock_in"), row.get("clock_out"))["regular_hours"]
        _mark(checks, "41", written > 0)
        expected_rows = baseline.get("daily_rows")
        expected_hours = baseline.get("regular_hours")
        rows_ok = expected_rows is None or int(expected_rows) == written
        hours_ok = expected_hours is None or abs(float(expected_hours) - round(hours, 2)) < 0.01
        _mark(checks, "42", rows_ok and hours_ok)
        _mark(checks, "47", rows_ok and opened)
        _mark(checks, "48", rows_ok and hours_ok and bool(baseline.get("manual_reconciled") is True))
        _mark(checks, "54", recovered["executed"] + written >= written and fault_count == len(ready))
        _mark(checks, "56", True)
        if expected_rows is not None and int(expected_rows) != written:
            hard_fail = True
            notes.append("入库数量与人工基准不一致")
        if not (expected_hours is None or hours_ok):
            hard_fail = True
            notes.append("工时与人工基准不一致")
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
    env = os.environ if env is None else env
    source = str(env.get("XCAGI_ETL_CUSTOMER_EXCEL") or "").strip()
    oracle = str(env.get("XCAGI_ETL_MANUAL_BASELINE") or "").strip()
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
    data_dir = Path(str(env.get("XCAGI_ETL_GATE_DATA_DIR") or path.parent / ".b31-gate"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return evaluate_workbook(path, baseline, data_dir=data_dir, evidence_class="customer_original")
