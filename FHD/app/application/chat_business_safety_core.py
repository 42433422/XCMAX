"""Shared policy, identity and receipt primitives for protected chat actions."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path
from app.utils.operational_errors import RECOVERABLE_ERRORS

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


_PERSONNEL_ENTITY_RE = re.compile(r"员工|人员|职员|工号|员工号|姓名|部门|岗位|职位", re.IGNORECASE)


_AI_EMPLOYEE_MENTION_RE = re.compile(
    r"(?:AI|人工智能|智能|数字|虚拟)[\-‐‑–—·]*"
    r"(?:(?:业务|销售|客服|采购|财务|仓储|运营|办公)[\-‐‑–—·]*)?员工",
    re.IGNORECASE,
)


_ATTENDANCE_RECORD_RE = re.compile(
    r"考勤(?:表|单|记录|数据|明细|结果)?|出勤(?:名单|情况|记录)?|"
    r"打卡(?:时间|记录|明细)?|签到(?:时间|记录)?|迟到|早退|缺卡|旷工|"
    r"请假|事假|病假|年假|调休|休假|婚假|产假|丧假",
    re.IGNORECASE,
)


_PRINT_VERB_RE = re.compile(r"打印|打出来|打(?:一|两|三|\d+)?份|送到打印机|出纸", re.IGNORECASE)


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
    re.compile(r"(?:工号|员工号)[:：#-]?([A-Za-z0-9_-]{1,64})", re.IGNORECASE),
    re.compile(r"\b([A-Za-z0-9_-]{1,64})号员工", re.IGNORECASE),
)


_LEAVE_TYPES = ("事假", "病假", "年假", "调休", "休假", "婚假", "产假", "丧假")


_DB_NAME = "taiyangniao_pro.db"


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).strip()


_CLAUSE_BOUNDARY_RE = re.compile(
    r"[,，;；。!?！？]+|然后|接着|随后|并且|"
    r"再(?=查询|查|登记|录入|取消|撤销|修改|帮|为|导出|打印)"
)


def classify_business_chat_intent(message: str) -> BusinessChatIntent | None:
    """Keep protected actions visible even alongside policy explanations."""
    intent = _classify_business_clause(message)
    if intent is not None:
        return intent
    # A policy cue in one clause must not exempt an independent record/action
    # request. Retain the whole-message pass for cross-clause entity references.
    operations = (
        "attendance_print",
        "attendance_export",
        "leave_write",
        "attendance_read",
        "personnel_read",
    )
    candidates = [
        candidate
        for clause in _CLAUSE_BOUNDARY_RE.split(_compact(message))
        if (candidate := _classify_business_clause(clause)) is not None
    ]
    return (
        min(candidates, key=lambda item: operations.index(item.operation)) if candidates else None
    )


def _classify_business_clause(message: str) -> BusinessChatIntent | None:
    """Classify one coherent request without relying on exact phrases."""

    text = _compact(message)
    if not text:
        return None

    has_attendance = bool(_ATTENDANCE_ENTITY_RE.search(text))
    # An AI employee is an assistant/capability reference, not a human record.
    # Remove only that noun phrase from personnel-entity detection: the rest of
    # a mixed request must still trigger the personnel/attendance/leave guard.
    # In particular, never exempt an entire message merely because it names AI.
    personnel_text = _AI_EMPLOYEE_MENTION_RE.sub("", text)
    has_personnel = bool(_PERSONNEL_ENTITY_RE.search(personnel_text))
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
            or (
                _PERSONAL_OR_DATE_RE.search(text)
                and re.search(r"半天|全天|一天|上午|下午|\d{1,4}(?:\.\d{1,2})?小时", text)
            )
        )
        if concrete_leave and not is_explanation:
            return BusinessChatIntent("leave_write", "attendance")

    record_terms = ("迟到", "出勤", "打卡")
    strong_record_question = (
        any(cue in text for cue in ("有没有", "是否", "是不是", "几点", "多少次", "几次"))
        or any(f"谁{term}" in text for term in ("出勤", "打卡"))
        or ("今天" in text and any(term in text for term in record_terms))
        or (text.endswith("吗") and any(term in text for term in record_terms))
    )
    if has_attendance and has_record_cue and not (is_explanation and not strong_record_question):
        return BusinessChatIntent("attendance_read", "attendance")

    if has_personnel and has_record_cue and not is_explanation:
        return BusinessChatIntent("personnel_read", "personnel")

    return None


def _db_path() -> Path:
    from app.application import chat_business_safety as facade

    resolver = getattr(facade, "_db_path", None)
    if callable(resolver) and resolver is not _db_path:
        return cast("Path", resolver())
    return resolve_mod_private_sqlite_path(_DB_NAME)


def _connect_existing() -> sqlite3.Connection | None:
    path = _db_path()
    if not path.is_file():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _authenticated_user_from_request(request: Any) -> Any | None:
    from app.application import chat_business_safety as facade

    resolver = getattr(facade, "_authenticated_user_from_request", None)
    if callable(resolver) and resolver is not _authenticated_user_from_request:
        return resolver(request)
    if request is None:
        return None
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        return resolve_session_user(request)
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - identity resolution must fail closed
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
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            f"""
        SELECT employee_name, employee_no, department, position, user_id
        FROM attendance_employees
        WHERE {" OR ".join(clauses)}
        ORDER BY id DESC LIMIT 1
        """,
            params,
        ).fetchone(),
    )
