"""合成考勤固化示例，不包含客户人员配置。

回归使用 80 名明确标记的虚构员工和 31 天合成记录，与仓库内
attendance-industry 参考实现逐槽对账，不依赖外部客户文件或跳过测试。
上午特殊班次由 SYNTHETIC-001 演练；现行参考实现的夜班统一从
18:00 起算，零头满 25 分钟计 0.5 小时，不额外重复累计周六时长。
"""

import re
from collections import defaultdict
from datetime import date, datetime, time

TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
DATE_RE = re.compile(r"(\d{2,4})-(\d{1,2})-(\d{1,2})")
HHMM_RE = re.compile(r"(\d{1,2}):(\d{2})")

# 金样归纳：上午块 (1,2) 的人（模板 B 列写 09:00 上班），其余 (2,2)
MORNING9 = {"SYNTHETIC-001"}
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
        dingtalk_hours = (
            rec["work_raw"] if rec["work_raw"] <= 24 else rec["work_raw"] / 60.0
        )
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
                    intervals = (
                        [(punches[0], punches[-1])] if punches[-1] > punches[0] else []
                    )
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
                            cs = max(
                                a, datetime(d.year, d.month, d.day, s.hour, s.minute)
                            )
                            ce = min(
                                b, datetime(d.year, d.month, d.day, e.hour, e.minute)
                            )
                            if ce > cs:
                                clipped.append((cs, ce))
                    eff = clipped
                if eff:
                    for band, bs, be, credit in _blocks(name):
                        total = 0.0
                        for a, b in eff:
                            cs = max(
                                a, datetime(d.year, d.month, d.day, bs.hour, bs.minute)
                            )
                            ce = min(
                                b, datetime(d.year, d.month, d.day, be.hour, be.minute)
                            )
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
            ot_start = datetime(d.year, d.month, d.day, 18, 0)
            minutes = max((punches[-1] - ot_start).total_seconds() / 60.0, 0.0)
            whole_hours, remainder = divmod(minutes, 60)
            total_night = whole_hours + (
                1.0 if remainder >= 55 else 0.5 if remainder >= 25 else 0.0
            )
            if total_night > 0:
                night.append({"symbol": night_symbol, "value": total_night})

        for band, entries in (
            ("morning", morning),
            ("afternoon", afternoon),
            ("night", night),
        ):
            trimmed = [
                {"symbol": e["symbol"], "value": round(float(e["value"]), 1)}
                for e in entries[:2]
            ]
            if trimmed:
                records.append(
                    {"key": name, "day": d.day, "band": band, "entries": trimmed}
                )
    return records
