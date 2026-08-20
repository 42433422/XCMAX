"""太阳鸟考勤转换的固化脚本（solidify 循环产物示例）。

由 LLM 在固化循环中亲笔编写（零 taiyangniao 依赖），3 轮迭代通过金样门禁：
v1 68.7%（原始记录误取「考勤时间」列）→ v2 97.8%（修打卡列优先级）→
v3 100%（金样归纳每人参数：MORNING9 上午 1+2 块、OT_1830 加班起算 18:30，
等价太阳鸟模板 B 列 DSL；请假子列口径复现参考实现——事假首列不计入）。

端到端验收：produce_records → compile → 模板写入员，与金样（太阳鸟单体输出）
数据区 30240 格逐格 0 差异。见 tests/test_mods/test_excel_rules_solidify.py 回归。

固化语义：MORNING9 / OT_1830 是当前人员配置的快照；人员变动时质检员
structure/expected 节会报警，触发重新 solidify。
"""

import re
from collections import defaultdict
from datetime import date, datetime, time

TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
DATE_RE = re.compile(r"(\d{2,4})-(\d{1,2})-(\d{1,2})")
HHMM_RE = re.compile(r"(\d{1,2}):(\d{2})")

# 金样归纳：上午块 (1,2) 的人（模板 B 列写 09:00 上班），其余 (2,2)
MORNING9 = {"李伟毅"}
OT_1830 = {"丁章帅", "杨宁", "杨进彬", "桂秀花", "桂艳芳", "桂辉定", "陈玉容"}
FACTORY_KEYS = ("惠州工厂", "工厂")
COMPANY_KEYS = ("公司-考勤", "公司正班", "惠州工厂-正班", "工厂正班")


def _parse_date(v):
    if v is None:
        return None
    m = DATE_RE.search(str(v))
    if not m:
        return None
    y = int(m.group(1))
    if y < 100:
        y += 2000
    try:
        return date(y, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_dt(v, d):
    if v is None or d is None:
        return None
    text = str(v).strip()
    if not text:
        return None
    dm = DATE_RE.search(text)
    tm = HHMM_RE.search(text[dm.end() :] if dm else text)
    if not tm:
        return None
    base = _parse_date(text) if dm else d
    if base is None:
        base = d
    return datetime(base.year, base.month, base.day, int(tm.group(1)), int(tm.group(2)))


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def _hours(a, b):
    return max((b - a).total_seconds() / 3600.0, 0.0)


def _round_half(x):
    if x <= 0:
        return 0.0
    return round(round(x * 2) / 2, 2)


def _round_whole(x):
    import math

    if x <= 0:
        return 0.0
    return float(int(math.floor(x + 0.5)))


def _shift_ranges(shift):
    out = []
    for a, b in TIME_RANGE_RE.findall(str(shift or "").replace("—", "-")):
        h1, m1 = a.split(":")
        h2, m2 = b.split(":")
        t1, t2 = time(int(h1), int(m1)), time(int(h2), int(m2))
        if t2 > t1:
            out.append((t1, t2))
    return out


def _is_rest(shift):
    t = str(shift or "").strip()
    return (not t) or ("休息" in t)


def _is_factory_group(group, shift):
    t = str(group or "") + " " + str(shift or "")
    return any(k in t for k in COMPANY_KEYS)


def _blocks(name):
    if name in MORNING9:
        return [
            ("morning", time(9, 0), time(10, 0), 1.0),
            ("morning", time(10, 0), time(12, 0), 2.0),
            ("afternoon", time(13, 30), time(15, 30), 2.0),
            ("afternoon", time(15, 30), time(17, 30), 2.0),
        ]
    return [
        ("morning", time(8, 0), time(10, 0), 2.0),
        ("morning", time(10, 0), time(12, 0), 2.0),
        ("afternoon", time(13, 30), time(15, 30), 2.0),
        ("afternoon", time(15, 30), time(17, 30), 2.0),
    ]


def _full_day(name, symbol):
    m, a = [], []
    for band, _s, _e, credit in _blocks(name):
        (m if band == "morning" else a).append({"symbol": symbol, "value": credit})
    return m, a


def _schedule(d, group, shift, name):
    parsed = _shift_ranges(shift)
    wd = d.weekday()
    if wd == 6:
        return []
    if wd == 5:
        if parsed:
            return parsed
        if _is_factory_group(group, shift):
            return [(time(13, 30), time(16, 0))]
        return []
    if parsed:
        return parsed
    return [(time(8, 0), time(12, 0)), (time(13, 30), time(17, 30))]


def _regular_symbol(dept, group, shift, d):
    if _is_rest(shift):
        return "★"
    is_factory_person = (
        ("惠州工厂" in str(dept or ""))
        or ("工厂" in str(group or ""))
        or ("工厂" in str(shift or ""))
    )
    if (
        ("公司" in str(shift or ""))
        and is_factory_person
        and ("远程" not in str(group or ""))
        and ("公司-考勤" not in str(group or ""))
    ):
        s = "☆"
    else:
        s = "√"
    if d.weekday() == 6 and s in ("√", "☆"):
        return "★"
    return s


def produce_records(source_workbook: dict, rules: dict) -> list:
    sheets = {s.get("name"): s for s in source_workbook.get("sheets") or []}
    daily = sheets.get("每日统计") or {"rows": [], "columns": []}
    raw = sheets.get("原始记录") or {"rows": []}
    keys = {
        str(b.get("key") or "").strip()
        for b in (rules.get("template_map") or {}).get("blocks") or []
    }
    keys.discard("")

    cal = (rules.get("template_map") or {}).get("calendar") or {}
    day_count = int(cal.get("day_count") or 31)

    # 原始记录打卡：按 (姓名, 日期)
    raw_punch = defaultdict(list)
    for row in raw.get("rows") or []:
        name = str(row.get("姓名") or "").strip()
        d = _parse_date(row.get("考勤日期"))
        dt = _parse_dt(row.get("打卡时间") or row.get("考勤时间"), d)
        if name and d and dt:
            raw_punch[(name, d)].append(dt)

    # 请假子列：从「请假」列到「加班时长（转加班费）」列之间
    cols = daily.get("columns") or []
    leave_cols = []
    if "请假" in cols:
        i = cols.index("请假")
        j = len(cols)
        for k in range(i + 1, len(cols)):
            if str(cols[k]).startswith("加班时长"):
                j = k
                break
        leave_cols = cols[i + 1 : j]

    clock_cols = [c for c in cols if re.match(r"^(上班|下班)\d+打卡时间$", str(c))]

    # 每人每日记录
    per = {}
    for row in daily.get("rows") or []:
        name = str(row.get("姓名") or "").strip()
        d = _parse_date(row.get("日期"))
        if not name or d is None or name not in keys:
            continue
        punches = set()
        for c in clock_cols:
            dt = _parse_dt(row.get(c), d)
            if dt:
                punches.add(dt)
        for dt in raw_punch.get((name, d), []):
            punches.add(dt)
        per[(name, d)] = {
            "punches": sorted(punches),
            "group": row.get("考勤组"),
            "dept": row.get("部门"),
            "shift": row.get("班次"),
            "leave": sum(_f(row.get(c)) for c in leave_cols),
            "absent": _f(row.get("旷工天数")),
            "attend_hint": _f(row.get("出勤天数")),
            "work_raw": _f(row.get("工作时长")),
        }

    # 连旷 streak
    streaks = {}
    by_name = defaultdict(list)
    for name, d in per:
        by_name[name].append(d)
    for name, ds in by_name.items():
        streak = 0
        for d in sorted(ds):
            rec = per[(name, d)]
            if not rec["punches"] and rec["absent"] > 0:
                streak += 1
            else:
                streak = 0
            streaks[(name, d)] = streak

    records = []
    for (name, d), rec in sorted(per.items()):
        if d.day < 1 or d.day > day_count:
            continue
        punches = rec["punches"]
        shift, group, dept = rec["shift"], rec["group"], rec["dept"]
        symbol = _regular_symbol(dept, group, shift, d)
        dingtalk_hours = rec["work_raw"] if rec["work_raw"] <= 24 else rec["work_raw"] / 60.0
        morning, afternoon, night = [], [], []

        if not punches:
            if (
                (not _is_rest(shift))
                and rec["leave"] <= 0
                and (dingtalk_hours >= 6.5 or rec["attend_hint"] >= 1.0)
            ):
                morning, afternoon = _full_day(name, symbol)
            elif rec["leave"] > 0 or rec["absent"] > 0 and streaks[(name, d)] >= 3:
                morning, afternoon = _full_day(name, "〇")
        else:
            sched = _schedule(d, group, shift, name)
            if len(punches) == 1:
                if not (_is_rest(shift) and rec["leave"] <= 0):
                    morning, afternoon = _full_day(name, symbol)
                intervals = []
            else:
                n = len(punches)
                if n % 2 == 1:
                    intervals = [(punches[0], punches[-1])] if punches[-1] > punches[0] else []
                else:
                    intervals = [
                        (punches[i], punches[i + 1])
                        for i in range(0, n, 2)
                        if punches[i + 1] > punches[i]
                    ]
                eff = intervals
                if sched:
                    clipped = []
                    for a, b in intervals:
                        for s, e in sched:
                            cs = max(a, datetime(d.year, d.month, d.day, s.hour, s.minute))
                            ce = min(b, datetime(d.year, d.month, d.day, e.hour, e.minute))
                            if ce > cs:
                                clipped.append((cs, ce))
                    eff = clipped
                if eff:
                    for band, bs, be, credit in _blocks(name):
                        total = 0.0
                        for a, b in eff:
                            cs = max(a, datetime(d.year, d.month, d.day, bs.hour, bs.minute))
                            ce = min(b, datetime(d.year, d.month, d.day, be.hour, be.minute))
                            if ce > cs:
                                total += _hours(cs, ce)
                        val = min(_round_whole(total), credit)
                        if val > 0:
                            (morning if band == "morning" else afternoon).append(
                                {"symbol": symbol, "value": val}
                            )
                elif not sched:
                    morning, afternoon = _full_day(name, symbol)

            # 夜班加班
            night_symbol = "★" if symbol == "★" else "☆"
            ot_start = (
                datetime(d.year, d.month, d.day, 18, 30)
                if name in OT_1830
                else datetime(d.year, d.month, d.day, 18, 0)
            )
            base = 0.0
            if punches and punches[-1] > ot_start:
                base = _round_half(_hours(ot_start, punches[-1]))
            extra_sat = 0.0
            if d.weekday() == 5 and _is_factory_group(group, shift) and sched and len(punches) >= 2:
                total = sum(_hours(a, b) for a, b in intervals)
                inside = 0.0
                for a, b in intervals:
                    for s, e in sched:
                        cs = max(a, datetime(d.year, d.month, d.day, s.hour, s.minute))
                        ce = min(b, datetime(d.year, d.month, d.day, e.hour, e.minute))
                        if ce > cs:
                            inside += _hours(cs, ce)
                extra_sat = _round_half(max(0.0, total - inside))
            total_night = _round_half(base + extra_sat)
            if total_night > 0:
                if total_night < 1.0 and base > 0 and extra_sat == 0.0:
                    total_night = 1.0
                night.append({"symbol": night_symbol, "value": total_night})

        for band, entries in (("morning", morning), ("afternoon", afternoon), ("night", night)):
            trimmed = [
                {"symbol": e["symbol"], "value": round(float(e["value"]), 1)} for e in entries[:2]
            ]
            if trimmed:
                records.append({"key": name, "day": d.day, "band": band, "entries": trimmed})
    return records
