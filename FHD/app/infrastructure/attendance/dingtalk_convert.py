"""钉钉考勤 Excel 规范化与月度统计。

Phase 3B 从 ``app.legacy.attendance_convert`` 吸收。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def build_normalized_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["工号", "姓名", "部门", "日期", "上班打卡", "下班打卡", "工作时长", "考勤结果"]
        )
    out = pd.DataFrame()
    out["工号"] = df.get("工号", "")
    out["姓名"] = df.get("姓名", "")
    out["部门"] = df.get("部门", "")
    out["日期"] = pd.to_datetime(df.get("日期"), errors="coerce").dt.strftime("%Y-%m-%d")
    out["上班打卡"] = pd.to_datetime(df.get("上班打卡时间"), errors="coerce")
    out["下班打卡"] = pd.to_datetime(df.get("下班打卡时间"), errors="coerce")
    out["工作时长"] = (out["下班打卡"] - out["上班打卡"]).dt.total_seconds().div(3600).round(2)
    out["考勤结果"] = df.get("考勤结果", "")
    return out


def aggregate_monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["工号", "姓名", "部门", "日期", "上班打卡", "下班打卡", "工作时长", "考勤结果"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    g = (
        df.groupby(["工号", "姓名", "部门", "日期"], dropna=False)
        .agg({"上班打卡": "min", "下班打卡": "max", "工作时长": "max", "考勤结果": "last"})
        .reset_index()
    )
    return g[cols]


def convert_dingtalk_file(
    input_path: Path | str,
    output_path: Path | str,
    *,
    month: str | None = None,
    sheet: int | str = 0,
    header_row: int = 0,
) -> dict[str, Any]:
    src = Path(input_path)
    out = Path(output_path)
    df = pd.read_excel(src, sheet_name=sheet, header=header_row, engine="openpyxl")
    norm = build_normalized_frame(df)
    stats = aggregate_monthly_stats(norm)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        norm.to_excel(w, sheet_name="明细", index=False)
        stats.to_excel(w, sheet_name="月度统计", index=False)
    return {"rows_in": int(len(df)), "rows_stats": int(len(stats)), "month": month}


__all__ = [
    "build_normalized_frame",
    "aggregate_monthly_stats",
    "convert_dingtalk_file",
]
