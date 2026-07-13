"""Verified business actions for natural-language chat.

This module is the safety boundary between free-form conversation and business
facts/side effects.  Attendance and personnel requests must never be answered
from model prose alone: a reply is produced here only after a deterministic
read, write, export, or print attempt and always carries an execution receipt.

The classifier intentionally uses an operation/entity model instead of a list
of complete canned phrases.  It therefore covers natural word-order variants
while allowing explanatory questions (for example, attendance policy) to keep
using normal conversation.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path
from app.mod_sdk.workspace import resolve_safe_workspace_relpath

BusinessOperation = Literal[
    "personnel_read",
    "attendance_read",
    "leave_write",
    "attendance_export",
    "attendance_print",
]


@dataclass(frozen=True)
class BusinessChatIntent:
    operation: BusinessOperation
    domain: Literal["personnel", "attendance"]


@dataclass(frozen=True)
class BusinessActorIdentity:
    """Server-derived identity candidates used to bind "我/本人" safely."""

    authenticated: bool
    local_user_id: str = ""
    username: str = ""
    display_name: str = ""
    trusted_client_user_id: str = ""


_ATTENDANCE_ENTITY_RE = re.compile(
    r"考勤|出勤|打卡|签到|迟到|早退|缺卡|旷工|排班|"
    r"请假|事假|病假|年假|调休|休假|婚假|产假|丧假",
    re.IGNORECASE,
)
_PERSONNEL_ENTITY_RE = re.compile(
    r"员工|人员|职员|工号|员工号|姓名|部门|岗位|职位", re.IGNORECASE
)
_ATTENDANCE_RECORD_RE = re.compile(
    r"考勤(?:表|单|记录|数据|明细|结果)?|出勤(?:名单|情况|记录)?|"
    r"打卡(?:时间|记录|明细)?|签到(?:时间|记录)?|迟到|早退|缺卡|旷工|"
    r"请假|事假|病假|年假|调休|休假|婚假|产假|丧假",
    re.IGNORECASE,
)
_PRINT_VERB_RE = re.compile(
    r"打印|打出来|打(?:一|两|三|\d+)?份|送到打印机|出纸", re.IGNORECASE
)
_EXPORT_VERB_RE = re.compile(
    r"导出|生成|制作|做(?:一|个|份|张)?|下载|整理成|给我(?:一|个|份|张)",
    re.IGNORECASE,
)
_WRITE_VERB_RE = re.compile(
    r"登记|录入|新增|添加|记(?:上|下|为)?|写入|提交|申请|办理|"
    r"安排|修改|更新|改成|删除|撤销|取消|审批|批准",
    re.IGNORECASE,
)
_LEAVE_CANCEL_RE = re.compile(r"取消|撤销|删除|不休假了|不用请假了|假不请了")
_LEAVE_MODIFY_RE = re.compile(r"修改|更新|改成|改为|换成")
_QUERY_CUE_RE = re.compile(
    r"查询|查(?:一下|下)?|找(?:一下|下)?|告诉我|看(?:一下|下)?|"
    r"有没有|是否|是不是|谁|哪(?:个|些|里)|什么|多少|几(?:点|次|个|人)|"
    r"叫什么|情况|状态|正常吗|迟到(?:了)?吗|出勤(?:了)?吗|打卡(?:了)?吗",
    re.IGNORECASE,
)
_INFO_CUE_RE = re.compile(
    r"制度|规则|政策|流程|规定|标准|教程|说明|介绍|含义|区别|差别|不同|是什么意思|"
    r"怎么(?:算|计算|操作|办理|设置)|如何(?:计算|办理|设置)|为什么会",
    re.IGNORECASE,
)
_LEAVE_RE = re.compile(r"请假|事假|病假|年假|调休|休假|婚假|产假|丧假")
_PERSONAL_OR_DATE_RE = re.compile(
    r"我|本人|今天|今日|昨天|昨日|前天|明天|后天|"
    r"20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?|\d{1,2}月\d{1,2}日"
)
_EMPLOYEE_NUMBER_PATTERNS = (
    re.compile(r"(?:工号|员工号)\s*[:：#-]?\s*([A-Za-z0-9_-]+)", re.IGNORECASE),
    re.compile(r"\b([A-Za-z0-9_-]+)\s*号员工", re.IGNORECASE),
)
_LEAVE_TYPES = ("事假", "病假", "年假", "调休", "休假", "婚假", "产假", "丧假")
_DB_NAME = "taiyangniao_pro.db"


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def classify_business_chat_intent(message: str) -> BusinessChatIntent | None:
    """Classify protected business semantics without relying on exact phrases."""

    text = _compact(message)
    if not text:
        return None

    has_attendance = bool(_ATTENDANCE_ENTITY_RE.search(text))
    has_personnel = bool(_PERSONNEL_ENTITY_RE.search(text))
    is_explanation = bool(_INFO_CUE_RE.search(text))
    has_record_cue = bool(
        _QUERY_CUE_RE.search(text)
        or _PERSONAL_OR_DATE_RE.search(text)
        or _EMPLOYEE_NUMBER_PATTERNS[0].search(text)
        or _EMPLOYEE_NUMBER_PATTERNS[1].search(text)
    )

    if has_attendance and _PRINT_VERB_RE.search(text):
        return BusinessChatIntent("attendance_print", "attendance")
    if has_attendance and _EXPORT_VERB_RE.search(text):
        return BusinessChatIntent("attendance_export", "attendance")

    if _LEAVE_RE.search(text):
        # A concrete leave statement such as "李四明天事假半天" is itself a
        # write-shaped request even when the user omits the verb "登记".  Pure
        # policy/how-to questions remain in normal conversation.
        concrete_leave = bool(
            _WRITE_VERB_RE.search(text)
            or _LEAVE_CANCEL_RE.search(text)
            or (_PERSONAL_OR_DATE_RE.search(text) and re.search(r"半天|全天|一天|上午|下午|\d+(?:\.\d+)?小时", text))
        )
        if concrete_leave and not is_explanation:
            return BusinessChatIntent("leave_write", "attendance")

    strong_record_question = bool(
        re.search(
            r"有没有|是否|是不是|几点|谁(?:出勤|打卡)|多少次|几次|"
            r"今天.*(?:迟到|出勤|打卡)|(?:迟到|出勤|打卡).*(?:了)?吗",
            text,
        )
    )
    if has_attendance and has_record_cue and not (is_explanation and not strong_record_question):
        return BusinessChatIntent("attendance_read", "attendance")

    if has_personnel and has_record_cue and not is_explanation:
        return BusinessChatIntent("personnel_read", "personnel")

    return None


def _db_path() -> Path:
    return resolve_mod_private_sqlite_path(_DB_NAME)


def _connect_existing() -> sqlite3.Connection | None:
    path = _db_path()
    if not path.is_file():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _authenticated_user_from_request(request: Any) -> Any | None:
    if request is None:
        return None
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        return resolve_session_user(request)
    except Exception:  # noqa: BLE001 - identity resolution must fail closed
        return None


def _resolve_actor_identity(
    *,
    request: Any = None,
    runtime_context: dict[str, Any] | None = None,
    client_user_id: str | None = None,
) -> BusinessActorIdentity:
    """Resolve the business actor from authenticated server state.

    Desktop chat ``body.user_id`` values such as ``web_normal_<session>`` are
    conversation namespaces, not personnel identifiers.  They are never used
    for employee matching.  A plain client id is retained only for trusted
    direct/internal callers where no HTTP identity exists.
    """

    user = _authenticated_user_from_request(request)
    if user is not None:
        local_id = str(getattr(user, "id", "") or "").strip()
        return BusinessActorIdentity(
            authenticated=True,
            local_user_id=local_id,
            username=str(getattr(user, "username", "") or "").strip(),
            display_name=str(getattr(user, "display_name", "") or "").strip(),
        )

    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    local_id = str(ctx.get("authenticated_local_user_id") or ctx.get("local_user_id") or "").strip()
    username = str(ctx.get("authenticated_username") or "").strip()
    display_name = str(ctx.get("authenticated_display_name") or "").strip()
    if local_id or username or display_name:
        return BusinessActorIdentity(
            authenticated=True,
            local_user_id=local_id,
            username=username,
            display_name=display_name,
        )

    candidate = str(client_user_id or "").strip()
    if re.match(r"^web_(?:normal|pro)_", candidate, re.IGNORECASE):
        candidate = ""
    return BusinessActorIdentity(
        authenticated=False,
        trusted_client_user_id=candidate,
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone()
    return row is not None


def _new_receipt(
    intent: BusinessChatIntent,
    *,
    status: str,
    executed: bool,
    verified: bool,
    source: str,
    affected_rows: int = 0,
    reason: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "receipt_id": f"biz_{uuid.uuid4().hex}",
        "domain": intent.domain,
        "operation": intent.operation,
        "status": status,
        "executed": executed,
        "verified": verified,
        "source": source,
        "affected_rows": int(affected_rows),
        "reason": reason,
        "artifacts": artifacts or [],
        "details": details or {},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _payload(text: str, intent: BusinessChatIntent, receipt: dict[str, Any]) -> dict[str, Any]:
    action = "business_tool_result" if receipt.get("executed") else "business_action_not_executed"
    return {
        "success": True,
        "message": text,
        "response": text,
        "execution_receipt": receipt,
        "business_receipt": receipt,
        "data": {
            "text": text,
            "action": action,
            "data": {
                "intent": asdict(intent),
                "execution_receipt": receipt,
            },
        },
    }


def _not_executed(
    intent: BusinessChatIntent,
    text: str,
    *,
    reason: str,
    source: str = "business_safety_policy",
    status: str = "not_executed",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _payload(
        text,
        intent,
        _new_receipt(
            intent,
            status=status,
            executed=False,
            verified=True,
            source=source,
            reason=reason,
            details=details,
        ),
    )


def _extract_employee_no(message: str) -> str:
    for pattern in _EMPLOYEE_NUMBER_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1).strip()
    return ""


def _extract_person_name(message: str) -> str:
    text = _compact(message)
    patterns = (
        r"(?:帮|给|替)\s*([\u4e00-\u9fa5]{2,4}?)(?=登记|录入|记|写入|提交|申请|办理|安排|请|事假|病假|年假|调休|休假|婚假|产假|丧假)",
        r"(?:员工|人员|姓名)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4}?)(?=是|在|属于|的|今天|今日|昨天|昨日|明天|后天|20\d{2}|\d{1,2}月|请假|事假|病假|年假|调休|休假)",
        r"^([\u4e00-\u9fa5]{2,4}?)(?=20\d{2}|今天|今日|昨天|昨日|明天|后天|是哪个|在哪个|属于|请假|事假|病假|年假|调休|休假)",
        r"(?:查|查询|找|看看)\s*([\u4e00-\u9fa5]{2,4}?)(?=的|是|在|属于|哪个|什么)",
    )
    for raw in patterns:
        match = re.search(raw, text)
        if match:
            candidate = match.group(1).strip()
            non_names = {
                "一下",
                "今天",
                "今日",
                "本人",
                "员工",
                "人员",
                "导出",
                "打印",
                "生成",
                "制作",
                "直接把",
                "给我",
                "帮我",
                "本月",
                "这个月",
            }
            if (
                candidate not in non_names
                and not candidate.endswith("部")
                and not re.search(r"导出|打印|生成|制作|直接|考勤", candidate)
            ):
                return candidate
    return ""


def _extract_department(message: str) -> str:
    match = re.search(
        r"([\u4e00-\u9fa5A-Za-z0-9_-]{1,20}部)"
        r"(?=今天|今日|昨天|昨日|本月|这个月|20\d{2}|\d{1,2}月|谁|的|考勤|出勤)",
        message,
    )
    return match.group(1).strip() if match else ""


def _resolve_person_from_actor(
    conn: sqlite3.Connection, actor: BusinessActorIdentity
) -> sqlite3.Row | None:
    if not _table_exists(conn, "attendance_employees"):
        return None
    identifiers = [
        item
        for item in (
            actor.local_user_id,
            actor.username,
            actor.trusted_client_user_id,
        )
        if item
    ]
    names = [item for item in (actor.display_name, actor.username) if item]
    clauses: list[str] = []
    params: list[str] = []
    for identifier in dict.fromkeys(identifiers):
        clauses.append("(TRIM(user_id) = ? OR TRIM(employee_no) = ?)")
        params.extend([identifier, identifier])
    for name in dict.fromkeys(names):
        clauses.append("TRIM(employee_name) = ?")
        params.append(name)
    if not clauses:
        return None
    return conn.execute(
        f"""
        SELECT employee_name, employee_no, department, position, user_id
        FROM attendance_employees
        WHERE {' OR '.join(clauses)}
        ORDER BY id DESC LIMIT 1
        """,
        params,
    ).fetchone()


def _handle_personnel_read(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    conn = _connect_existing()
    source = f"{_DB_NAME}:attendance_employees"
    if conn is None:
        return _not_executed(
            intent,
            "人员查询未执行：本机尚无可核验的人员库。请先导入人员名单。",
            reason="personnel_database_missing",
            source=source,
            status="unavailable",
        )
    try:
        if not _table_exists(conn, "attendance_employees"):
            return _not_executed(
                intent,
                "人员查询未执行：人员库尚未初始化。请先导入人员名单。",
                reason="personnel_table_missing",
                source=source,
                status="unavailable",
            )
        employee_no = _extract_employee_no(message)
        person_name = _extract_person_name(message)
        params: list[Any] = []
        where = "1=1"
        if employee_no:
            where = "TRIM(employee_no) = ? OR TRIM(user_id) = ?"
            params = [employee_no, employee_no]
        elif person_name:
            where = "TRIM(employee_name) = ?"
            params = [person_name]
        elif re.search(r"我|本人", message):
            person = _resolve_person_from_actor(conn, actor)
            if person is None:
                return _not_executed(
                    intent,
                    "已尝试查询，但当前登录账号没有绑定人员档案。请先在人员管理中绑定账号，或提供姓名/工号。",
                    reason="current_user_not_mapped",
                    source=source,
                    details={"actor": asdict(actor)},
                )
            where = "TRIM(employee_name) = ? AND (TRIM(employee_no) = ? OR TRIM(user_id) = ?)"
            params = [
                str(person["employee_name"] or ""),
                str(person["employee_no"] or ""),
                str(person["user_id"] or ""),
            ]
        rows = conn.execute(
            f"""
            SELECT employee_name, employee_no, department, position, user_id
            FROM attendance_employees WHERE {where}
            ORDER BY employee_name, id LIMIT 50
            """,
            params,
        ).fetchall()
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM attendance_employees WHERE {where}", params).fetchone()[0]
            or 0
        )
    except sqlite3.Error as exc:
        return _not_executed(
            intent,
            "人员查询未执行：读取人员库失败。",
            reason=f"personnel_query_failed:{exc}",
            source=source,
            status="failed",
        )
    finally:
        conn.close()

    receipt = _new_receipt(
        intent,
        status="verified" if rows else "verified_empty",
        executed=True,
        verified=True,
        source=source,
        affected_rows=len(rows),
        details={"matched_total": total, "employee_no": employee_no, "employee_name": person_name},
    )
    if not rows:
        key = employee_no or person_name or "当前登录账号"
        return _payload(
            f"已查询真实人员库，但没有找到“{key}”对应的员工；本次没有猜测姓名或部门。",
            intent,
            receipt,
        )
    lines = ["已查询真实人员库："]
    for row in rows[:20]:
        lines.append(
            f"- {str(row['employee_name'] or '未命名')}｜工号 {str(row['employee_no'] or '未设置')}｜"
            f"{str(row['department'] or '未设置部门')}｜{str(row['position'] or '未设置岗位')}"
        )
    if total > len(rows):
        lines.append(f"另有 {total - len(rows)} 条匹配记录未展开。")
    lines.append(f"数据来源：{source}；查询回执：{receipt['receipt_id']}。")
    return _payload("\n".join(lines), intent, receipt)


def _parse_date_scope(message: str, *, now: date | None = None) -> tuple[str, str, str] | None:
    today = now or date.today()
    text = _compact(message)
    if "前天" in text:
        d = today - timedelta(days=2)
        return "day", d.isoformat(), d.isoformat()
    if "昨天" in text or "昨日" in text:
        d = today - timedelta(days=1)
        return "day", d.isoformat(), d.isoformat()
    if "明天" in text:
        d = today + timedelta(days=1)
        return "day", d.isoformat(), d.isoformat()
    if "后天" in text:
        d = today + timedelta(days=2)
        return "day", d.isoformat(), d.isoformat()
    if "今天" in text or "今日" in text:
        return "day", today.isoformat(), today.isoformat()

    full = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?", text)
    if full:
        try:
            d = date(int(full.group(1)), int(full.group(2)), int(full.group(3)))
            return "day", d.isoformat(), d.isoformat()
        except ValueError:
            return None
    md = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", text)
    if md:
        try:
            d = date(today.year, int(md.group(1)), int(md.group(2)))
            return "day", d.isoformat(), d.isoformat()
        except ValueError:
            return None

    month = re.search(r"(20\d{2})[年./-](\d{1,2})月?", text)
    if month and not full:
        year, mon = int(month.group(1)), int(month.group(2))
        if 1 <= mon <= 12:
            start = date(year, mon, 1)
            next_month = date(year + (mon == 12), 1 if mon == 12 else mon + 1, 1)
            return "month", start.isoformat(), (next_month - timedelta(days=1)).isoformat()
    if any(token in text for token in ("本月", "这个月", "当月")):
        start = today.replace(day=1)
        next_month = date(today.year + (today.month == 12), 1 if today.month == 12 else today.month + 1, 1)
        return "month", start.isoformat(), (next_month - timedelta(days=1)).isoformat()
    return None


def _attendance_rows(
    message: str,
    *,
    actor: BusinessActorIdentity,
    require_scope: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    scope = _parse_date_scope(message)
    if require_scope and scope is None:
        return [], {}, "missing_date_scope"

    conn = _connect_existing()
    if conn is None:
        return [], {}, "attendance_database_missing"
    try:
        if not _table_exists(conn, "attendance_daily_records"):
            return [], {}, "attendance_records_missing"

        clauses: list[str] = []
        params: list[Any] = []
        meta: dict[str, Any] = {}
        if scope:
            scope_kind, start, end = scope
            clauses.append("work_date BETWEEN ? AND ?")
            params.extend([start, end])
            meta.update({"scope": scope_kind, "date_start": start, "date_end": end})

        employee_no = _extract_employee_no(message)
        person_name = _extract_person_name(message)
        department = _extract_department(message)
        if employee_no:
            clauses.append("TRIM(employee_no) = ?")
            params.append(employee_no)
            meta["employee_no"] = employee_no
        elif person_name:
            clauses.append("TRIM(employee_name) = ?")
            params.append(person_name)
            meta["employee_name"] = person_name
        elif re.search(r"我|本人|我的", message):
            person = _resolve_person_from_actor(conn, actor)
            if person is None:
                return [], {**meta, "actor": asdict(actor)}, "current_user_not_mapped"
            person_name_value = str(person["employee_name"] or "")
            employee_no_value = str(person["employee_no"] or "")
            employee_user_id = str(person["user_id"] or "")
            clauses.append(
                "(TRIM(employee_name) = ? AND (TRIM(employee_no) = ? OR TRIM(user_id) = ?))"
            )
            params.extend([person_name_value, employee_no_value, employee_user_id])
            meta.update(
                {
                    "actor": asdict(actor),
                    "employee_name": person_name_value,
                    "employee_no": employee_no_value,
                }
            )
        elif department:
            clauses.append("TRIM(department) = ?")
            params.append(department)
            meta["department"] = department

        where = " AND ".join(clauses) if clauses else "1=1"
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT employee_name, employee_no, department, position, user_id,
                       work_date, shift_name, daily_times_json, raw_times_json,
                       all_times_json, leave_hours, absent_days, late_count_hint,
                       early_count_hint, missing_card_count, notes_json, source_file,
                       imported_at
                FROM attendance_daily_records
                WHERE {where}
                ORDER BY work_date, employee_name, id
                LIMIT 5000
                """,
                params,
            ).fetchall()
        ]
        return rows, meta, None
    except sqlite3.Error as exc:
        return [], {}, f"attendance_query_failed:{exc}"
    finally:
        conn.close()


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _attendance_error_payload(
    intent: BusinessChatIntent, error: str, meta: dict[str, Any]
) -> dict[str, Any]:
    source = f"{_DB_NAME}:attendance_daily_records"
    if error == "missing_date_scope":
        text = "考勤查询未执行：请明确要查询的日期或月份，例如“今天”“2026年7月14日”或“本月”。"
    elif error == "current_user_not_mapped":
        text = "已尝试查询，但当前登录账号没有绑定人员档案，无法判断“我”的考勤。请先在人员管理中绑定账号或提供姓名/工号。"
    elif error in {"attendance_database_missing", "attendance_records_missing"}:
        text = "考勤查询未执行：当前没有可核验的打卡明细。请先通过“考勤表转换/考勤数据源”导入原始考勤表。"
    else:
        text = "考勤查询未执行：读取真实考勤数据失败。"
    return _not_executed(
        intent,
        text,
        reason=error,
        source=source,
        status="unavailable" if "missing" in error or "not_mapped" in error else "failed",
        details=meta,
    )


def _handle_attendance_read(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    rows, meta, error = _attendance_rows(message, actor=actor)
    if error:
        return _attendance_error_payload(intent, error, meta)

    source = f"{_DB_NAME}:attendance_daily_records"
    receipt = _new_receipt(
        intent,
        status="verified" if rows else "verified_empty",
        executed=True,
        verified=True,
        source=source,
        affected_rows=len(rows),
        details=meta,
    )
    scope_label = meta.get("date_start")
    if meta.get("date_end") and meta.get("date_end") != scope_label:
        scope_label = f"{scope_label} 至 {meta['date_end']}"
    if not rows:
        return _payload(
            f"已查询真实考勤库，但没有找到 {scope_label or '指定范围'} 的匹配记录，因此无法判断出勤或迟到；本次没有猜测。\n"
            f"数据来源：{source}；查询回执：{receipt['receipt_id']}。",
            intent,
            receipt,
        )

    wants_punch = bool(re.search(r"几点|时间|打卡|签到", message))
    wants_late = "迟到" in message
    wants_leave = bool(_LEAVE_RE.search(message))
    if wants_late:
        late_rows = [row for row in rows if float(row.get("late_count_hint") or 0) > 0]
        if len(rows) == 1:
            row = rows[0]
            late_count = float(row.get("late_count_hint") or 0)
            status = "有迟到标记" if late_count > 0 else "迟到标记为 0"
            times = _json_list(row.get("all_times_json"))
            time_text = f"；打卡时间：{', '.join(times)}" if times else "；没有打卡时间明细"
            text = (
                f"已查询 {row.get('work_date')} 的导入考勤记录：{row.get('employee_name') or '该员工'}{status}{time_text}。\n"
                "该结论只代表当前已导入的数据，不代表未同步的数据。"
            )
        else:
            text = f"已查询 {len(rows)} 条真实考勤记录，其中 {len(late_rows)} 条带迟到标记。"
            if late_rows:
                text += "\n" + "\n".join(
                    f"- {row.get('work_date')} {row.get('employee_name')}：迟到标记 {row.get('late_count_hint')}"
                    for row in late_rows[:20]
                )
    elif wants_punch:
        lines = []
        for row in rows[:30]:
            times = _json_list(row.get("all_times_json"))
            lines.append(
                f"- {row.get('work_date')} {row.get('employee_name')}："
                + (", ".join(times) if times else "无打卡时间")
            )
        text = f"已查询真实打卡明细（{len(rows)} 条）：\n" + "\n".join(lines)
    elif wants_leave:
        leave_rows = [row for row in rows if float(row.get("leave_hours") or 0) > 0]
        text = f"已查询 {len(rows)} 条真实考勤记录，其中 {len(leave_rows)} 条含请假时长。"
        if leave_rows:
            text += "\n" + "\n".join(
                f"- {row.get('work_date')} {row.get('employee_name')}：{row.get('leave_hours')} 小时"
                for row in leave_rows[:20]
            )
    else:
        punched = sum(1 for row in rows if _json_list(row.get("all_times_json")))
        absent = sum(1 for row in rows if float(row.get("absent_days") or 0) > 0)
        late = sum(1 for row in rows if float(row.get("late_count_hint") or 0) > 0)
        text = (
            f"已查询真实考勤记录 {len(rows)} 条：有打卡时间 {punched} 条，"
            f"迟到标记 {late} 条，缺勤标记 {absent} 条。"
        )
    text += f"\n数据来源：{source}；查询回执：{receipt['receipt_id']}。"
    return _payload(text, intent, receipt)


def _ensure_leave_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_leave_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id TEXT NOT NULL UNIQUE,
            employee_name TEXT NOT NULL,
            employee_no TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            leave_type TEXT NOT NULL,
            leave_date TEXT NOT NULL,
            period TEXT NOT NULL,
            hours REAL NOT NULL,
            approval_status TEXT NOT NULL,
            approval_evidence TEXT NOT NULL DEFAULT '',
            source_message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(employee_name, leave_date, period, leave_type)
        )
        """
    )


def _leave_fields(message: str) -> dict[str, Any]:
    text = _compact(message)
    leave_type = next((item for item in _LEAVE_TYPES if item in text), "")
    scope = _parse_date_scope(text)
    leave_date = scope[1] if scope and scope[0] == "day" else ""
    if "上午" in text:
        period, hours = "morning", 4.0
    elif "下午" in text:
        period, hours = "afternoon", 4.0
    elif "半天" in text:
        period, hours = "half_day_unspecified", 4.0
    elif "全天" in text or "一天" in text:
        period, hours = "full_day", 8.0
    else:
        match = re.search(r"(\d+(?:\.\d+)?)小时", text)
        period, hours = ("hours", float(match.group(1))) if match else ("", 0.0)
    approval_positive = bool(
        re.search(r"(?:主管|领导|经理)?.{0,8}(?:已|已经)?(?:审批通过|批准|同意)", text)
    )
    approval_negative = bool(
        re.search(r"未(?:审批|批准|同意)|没有(?:审批|批准|同意)|不(?:批准|同意)|拒绝", text)
    )
    approved = approval_positive and not approval_negative
    return {
        "employee_name": _extract_person_name(text),
        "leave_type": leave_type,
        "leave_date": leave_date,
        "period": period,
        "hours": hours,
        "approval_status": "reported_approved" if approved else "pending",
        "approval_evidence": "用户声明已审批通过，未核验审批单或审批 ID" if approved else "",
        "approval_verified": False,
    }


def _handle_leave_write(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    if _LEAVE_CANCEL_RE.search(message):
        return _not_executed(
            intent,
            "请假取消未执行：当前聊天工具只支持新增登记，尚未接入可核验的撤销接口。请在请假记录中选择原记录取消；系统不会把聊天回复当成取消回执。",
            reason="leave_cancel_tool_unavailable",
        )
    if _LEAVE_MODIFY_RE.search(message):
        return _not_executed(
            intent,
            "请假修改未执行：当前聊天工具尚未接入可核验的修改接口。请在请假记录中编辑原记录；没有更新回执前系统不会声称修改成功。",
            reason="leave_modify_tool_unavailable",
        )
    fields = _leave_fields(message)
    if not fields.get("employee_name") and re.search(r"我|本人", message):
        identity_conn = _connect_existing()
        try:
            person = _resolve_person_from_actor(identity_conn, actor) if identity_conn else None
            if person is not None:
                fields["employee_name"] = str(person["employee_name"] or "")
        finally:
            if identity_conn is not None:
                identity_conn.close()
    missing = [
        label
        for key, label in (
            ("employee_name", "员工姓名"),
            ("leave_type", "请假类型"),
            ("leave_date", "请假日期"),
            ("period", "时段或时长"),
        )
        if not fields.get(key)
    ]
    if missing:
        return _not_executed(
            intent,
            f"请假未登记：还缺少{'、'.join(missing)}。补全后我才能写入并返回真实登记回执。",
            reason="missing_required_fields",
            details={"missing_fields": missing},
        )

    db_path = _db_path()
    if not db_path.is_file():
        return _not_executed(
            intent,
            "请假未登记：本机尚无人员库，无法核验员工身份。请先导入人员名单。",
            reason="personnel_database_missing",
            source=f"{_DB_NAME}:attendance_leave_records",
            status="unavailable",
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    source = f"{_DB_NAME}:attendance_leave_records"
    try:
        if not _table_exists(conn, "attendance_employees"):
            return _not_executed(
                intent,
                "请假未登记：人员库尚未初始化，无法核验员工身份。",
                reason="personnel_table_missing",
                source=source,
                status="unavailable",
            )
        employee = conn.execute(
            """
            SELECT employee_name, employee_no, user_id FROM attendance_employees
            WHERE TRIM(employee_name) = ? ORDER BY id DESC LIMIT 1
            """,
            (fields["employee_name"],),
        ).fetchone()
        if employee is None:
            return _not_executed(
                intent,
                f"请假未登记：真实人员库中没有找到“{fields['employee_name']}”，系统不会为未知员工创建记录。",
                reason="employee_not_found",
                source=source,
                details={"employee_name": fields["employee_name"]},
            )

        _ensure_leave_schema(conn)
        existing = conn.execute(
            """
            SELECT * FROM attendance_leave_records
            WHERE employee_name=? AND leave_date=? AND period=? AND leave_type=?
            LIMIT 1
            """,
            (
                fields["employee_name"],
                fields["leave_date"],
                fields["period"],
                fields["leave_type"],
            ),
        ).fetchone()
        now = datetime.now().isoformat(timespec="seconds")
        if existing is not None:
            if (
                fields["approval_status"] == "reported_approved"
                and existing["approval_status"] != "reported_approved"
            ):
                conn.execute(
                    """
                    UPDATE attendance_leave_records
                    SET approval_status='reported_approved', approval_evidence=?, updated_at=?
                    WHERE id=?
                    """,
                    (fields["approval_evidence"], now, existing["id"]),
                )
                conn.commit()
                existing = conn.execute(
                    "SELECT * FROM attendance_leave_records WHERE id=?", (existing["id"],)
                ).fetchone()
                status = "updated"
            else:
                status = "already_exists"
            receipt_id = str(existing["receipt_id"])
            record_id = int(existing["id"])
        else:
            receipt_id = f"leave_{uuid.uuid4().hex}"
            cur = conn.execute(
                """
                INSERT INTO attendance_leave_records (
                    receipt_id, employee_name, employee_no, user_id, leave_type,
                    leave_date, period, hours, approval_status, approval_evidence,
                    source_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    fields["employee_name"],
                    str(employee["employee_no"] or ""),
                    str(employee["user_id"] or actor.local_user_id or ""),
                    fields["leave_type"],
                    fields["leave_date"],
                    fields["period"],
                    fields["hours"],
                    fields["approval_status"],
                    fields["approval_evidence"],
                    message[:2000],
                    now,
                    now,
                ),
            )
            record_id = int(cur.lastrowid)
            conn.commit()
            status = "created"
    except sqlite3.Error as exc:
        conn.rollback()
        return _not_executed(
            intent,
            "请假未登记：写入真实请假记录失败。",
            reason=f"leave_write_failed:{exc}",
            source=source,
            status="failed",
        )
    finally:
        conn.close()

    approval_label = (
        "按用户声明记录为已审批（未核验审批单/审批 ID）"
        if fields["approval_status"] == "reported_approved"
        else "待审批"
    )
    receipt = _new_receipt(
        intent,
        status=status,
        executed=True,
        verified=True,
        source=source,
        affected_rows=1,
        details={
            **fields,
            "record_id": record_id,
            "write_receipt_id": receipt_id,
        },
    )
    action_label = "记录已存在" if status == "already_exists" else "登记成功"
    text = (
        f"请假{action_label}：{fields['employee_name']}，{fields['leave_date']}，"
        f"{fields['leave_type']} {fields['hours']:g} 小时，状态为{approval_label}。\n"
        f"业务记录 ID：{record_id}；写入回执：{receipt_id}。"
    )
    return _payload(text, intent, receipt)


_EXPORT_COLUMNS = (
    ("work_date", "日期"),
    ("employee_name", "姓名"),
    ("employee_no", "工号"),
    ("department", "部门"),
    ("position", "岗位"),
    ("shift_name", "班次"),
    ("all_times_json", "打卡时间"),
    ("leave_hours", "请假小时"),
    ("absent_days", "缺勤天数"),
    ("late_count_hint", "迟到标记"),
    ("early_count_hint", "早退标记"),
    ("missing_card_count", "缺卡次数"),
)


def _create_attendance_export(rows: list[dict[str, Any]], meta: dict[str, Any]) -> tuple[Path, str]:
    import openpyxl

    token = uuid.uuid4().hex[:12]
    label = str(meta.get("date_start") or "records")
    if meta.get("scope") == "month":
        label = label[:7]
    filename = f"attendance-{label}-{token}.xlsx"
    relpath = f"attendance_exports/{filename}"
    output = resolve_safe_workspace_relpath(relpath)
    output.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "考勤明细"
    ws.append([label for _, label in _EXPORT_COLUMNS])
    for row in rows:
        values: list[Any] = []
        for key, _ in _EXPORT_COLUMNS:
            value = row.get(key)
            if key == "all_times_json":
                value = "、".join(_json_list(value))
            values.append(value)
        ws.append(values)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        width = min(36, max(10, max(len(str(cell.value or "")) for cell in col) + 2))
        ws.column_dimensions[col[0].column_letter].width = width
    wb.save(output)
    wb.close()
    return output, relpath


def _handle_attendance_export(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    rows, meta, error = _attendance_rows(message, actor=actor)
    if error:
        return _attendance_error_payload(intent, error, meta)
    if not rows:
        source = f"{_DB_NAME}:attendance_daily_records"
        return _not_executed(
            intent,
            "考勤表未生成：已查询真实考勤库，但指定范围没有记录。",
            reason="no_attendance_rows",
            source=source,
            details=meta,
        )
    try:
        output, relpath = _create_attendance_export(rows, meta)
    except Exception as exc:  # noqa: BLE001 - converted to a truthful receipt
        return _not_executed(
            intent,
            "考勤表未生成：文件写出失败。",
            reason=f"attendance_export_failed:{exc}",
            source=f"{_DB_NAME}:attendance_daily_records",
            status="failed",
            details=meta,
        )
    url = f"/api/mod/taiyangniao-pro/attendance/download?relpath={quote(relpath)}"
    artifact = {
        "kind": "file",
        "filename": output.name,
        "path": str(output),
        "download_url": url,
        "size_bytes": output.stat().st_size,
    }
    receipt = _new_receipt(
        intent,
        status="completed",
        executed=True,
        verified=output.is_file() and output.stat().st_size > 0,
        source=f"{_DB_NAME}:attendance_daily_records",
        affected_rows=len(rows),
        artifacts=[artifact],
        details=meta,
    )
    text = (
        f"考勤表已根据真实记录生成，共 {len(rows)} 行。\n"
        f"[下载 {output.name}]({url})\n"
        f"导出回执：{receipt['receipt_id']}。"
    )
    return _payload(text, intent, receipt)


def _get_printer_service():
    from app.services import get_printer_service

    return get_printer_service()


def _handle_attendance_print(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    rows, meta, error = _attendance_rows(message, actor=actor)
    if error:
        return _attendance_error_payload(intent, error, meta)
    if not rows:
        return _not_executed(
            intent,
            "打印未执行：指定范围没有可核验的考勤记录。",
            reason="no_attendance_rows",
            source=f"{_DB_NAME}:attendance_daily_records",
            details=meta,
        )
    try:
        service = _get_printer_service()
        printers = service.get_printers()
    except Exception as exc:  # noqa: BLE001
        return _not_executed(
            intent,
            "打印未执行：无法读取系统打印机状态。",
            reason=f"printer_status_failed:{exc}",
            source="printer_service",
            status="failed",
        )
    count = int(printers.get("count") or len(printers.get("printers") or [])) if isinstance(printers, dict) else 0
    if not isinstance(printers, dict) or not printers.get("success") or count <= 0:
        return _not_executed(
            intent,
            "打印未执行：当前没有可用打印机。请先在“考勤打印机”中连接并验证打印机。",
            reason="no_available_printer",
            source="printer_service",
            details={"printer_count": count},
        )
    try:
        output, relpath = _create_attendance_export(rows, meta)
        result = service.print_document(str(output))
    except Exception as exc:  # noqa: BLE001
        return _not_executed(
            intent,
            "打印未执行：考勤文件生成或提交打印失败。",
            reason=f"print_submit_failed:{exc}",
            source="printer_service",
            status="failed",
        )
    if not isinstance(result, dict) or not result.get("success"):
        reason = str((result or {}).get("message") or "printer_rejected") if isinstance(result, dict) else "printer_rejected"
        return _not_executed(
            intent,
            f"打印未执行：打印服务未接受任务（{reason}）。",
            reason=reason,
            source="printer_service",
            status="failed",
        )
    url = f"/api/mod/taiyangniao-pro/attendance/download?relpath={quote(relpath)}"
    printer_name = str(result.get("printer") or result.get("printer_name") or "系统默认打印机")
    receipt = _new_receipt(
        intent,
        status="submitted",
        executed=True,
        verified=True,
        source="printer_service",
        affected_rows=len(rows),
        artifacts=[
            {
                "kind": "file",
                "filename": output.name,
                "path": str(output),
                "download_url": url,
                "size_bytes": output.stat().st_size,
            }
        ],
        details={**meta, "printer": printer_name, "backend_result": result},
    )
    text = (
        f"考勤表已提交到 {printer_name}，共 {len(rows)} 行。打印机是否实际出纸仍以设备状态为准。\n"
        f"打印回执：{receipt['receipt_id']}；[下载打印文件]({url})。"
    )
    return _payload(text, intent, receipt)


def try_handle_business_chat_action(
    message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    request: Any = None,
) -> dict[str, Any] | None:
    """Execute a protected business action or return ``None`` for normal chat."""

    intent = classify_business_chat_intent(message)
    if intent is None:
        return None
    context = runtime_context if isinstance(runtime_context, dict) else {}
    actor = _resolve_actor_identity(
        request=request,
        runtime_context=context,
        client_user_id=user_id or str(context.get("user_id") or ""),
    )
    if intent.operation == "personnel_read":
        return _handle_personnel_read(message, intent, actor=actor)
    if intent.operation == "attendance_read":
        return _handle_attendance_read(message, intent, actor=actor)
    if intent.operation == "leave_write":
        return _handle_leave_write(message, intent, actor=actor)
    if intent.operation == "attendance_export":
        return _handle_attendance_export(message, intent, actor=actor)
    if intent.operation == "attendance_print":
        return _handle_attendance_print(message, intent, actor=actor)
    return None


__all__ = [
    "BusinessChatIntent",
    "classify_business_chat_intent",
    "try_handle_business_chat_action",
]
