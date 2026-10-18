"""派给 dot（Para 工具 ``dolt``）的客服工单：控制标记、处理模式和离开 MODstore 前的脱敏。

dot 的转接程序（devfleet-private ``scripts/dot-mailbox-agent.mjs``）只接受标题以
``[xcmax:<32位hex>:<32位hex>]`` 开头的任务，任务内容会写进私有仓库的 mailbox 分支。
这里只改派给 dolt 的客服工单载荷；派给其他工具或非工单任务原样返回。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Dict, Iterable, List

DOLT_TOOL = "dolt"
TICKET_EVENT = "ops.intake.customer_ticket"
MODE_REPORT_ONLY = "report_only"
MODE_CODE_FIX = "code_fix"
MARKER_RE = re.compile(r"^\[xcmax:[0-9a-f]{32}:[0-9a-f]{32}\]")
SUMMARY_LIMIT = 1500
FIELD_LIMIT = 120

# 账号/登录/密码/权限类：与 dot 侧 classify 的关键词一致并略放宽，命中即只出报告。
_ACCOUNT_RE = re.compile(
    r"(账号|帐号|账户|帐户|登录|登陆|密码|验证码|注册|实名|权限|封号|解封|鉴权|授权|"
    r"account|login|log in|sign[ -]?in|password|credential|2fa|otp|permission|forbidden|"
    r"unauthori[sz]ed)",
    re.I,
)

_SECRET_KV_RE = re.compile(
    r"(?i)(?:bearer\s+|(?:api[_-]?key|access[_-]?key|private[_-]?key|password|passwd|pwd|"
    r"token|secret|authorization|cookie|session[_-]?key|密码|口令|密钥|令牌)"
    r"\s*[:=：]\s*(?:bearer\s+)?)[^\s,，;；'\"]+"
)
_PEM_RE = re.compile(r"-----BEGIN [^-]*-----.*?-----END [^-]*-----", re.S)
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_ID_CARD_RE = re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")
_BANK_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){14,18}\d(?!\d)")
_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?!\d)")
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_INTERNAL_ID_RE = re.compile(
    r"(?i)\b(?:user_?id|uid|tenant_?id|session_?id|owner_?id|customer_?id|account_?id|"
    r"member_?id|open_?id|union_?id|customer_instance_id|device_?id)\s*[:=：]\s*[\"']?[\w\-]+"
)
_NAME_LABEL_RE = re.compile(
    r"(?i)(?:姓名|名字|联系人|收件人|收货人|客户名|真实姓名|称呼|full[_ ]?name|contact[_ ]?name|"
    r"user[_ ]?name|username|nickname)\s*[:：=]\s*[^\s,，;；。]+"
)
_ADDRESS_LABEL_RE = re.compile(
    r"(?i)(?:收货地址|详细地址|住址|地址|address)\s*[:：=]\s*[^\n,，;；。]+"
)
_ADDRESS_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,8}(?:省|市|自治区)[\u4e00-\u9fa5\d]{0,20}?"
    r"(?:区|县|镇|乡|街道|路|街|大道|弄|巷)[\u4e00-\u9fa5\d]{0,20}?\d+\s*(?:号|弄|栋|幢|室|楼)"
    r"[\u4e00-\u9fa5\d\-#号栋幢楼室单元]*"
)
_LONG_OPAQUE_RE = re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}")
# dot 侧 safeText 的拒收规则（dot-mailbox.mjs）；兜底确保脱敏结果不会让桥停下。
_DOT_REJECT_RE = re.compile(
    r"(?i)(?:bearer\s+\S+|-----BEGIN .*PRIVATE KEY|(?:password|passwd|api[_-]?key|secret|token)"
    r"\s*[:=]\s*\S+|https?://[^/\s:@]+:[^/\s@]+@)"
)

_SENSITIVE_VALUE_KEYS = (
    "contact_name",
    "customer_name",
    "real_name",
    "name",
    "username",
    "user_name",
    "nickname",
    "display_name",
    "phone",
    "mobile",
    "email",
    "contact",
    "address",
    "user_id",
    "tenant_id",
    "session_id",
    "customer_instance_id",
)
_REPRO_KEYS = (
    "issue_domain",
    "scope",
    "product_version",
    "installed_version",
    "git_sha",
    "target_mod_id",
    "intake_source",
)


def _mask(kind: str) -> str:
    return f"[已遮蔽:{kind}]"


def _opaque(match: "re.Match[str]") -> str:
    value = match.group(0)
    # 40/64 位纯十六进制多为提交号或摘要，属于复现信息，保留；其余长十六进制按密钥处理。
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        return value
    if re.fullmatch(r"[0-9a-fA-F]+", value):
        return _mask("长串")
    classes = sum(bool(re.search(c, value)) for c in (r"\d", r"[a-z]", r"[A-Z]"))
    return _mask("长串") if classes == 3 else value


def redact_ticket_text(
    text: Any, sensitive_values: Iterable[str] = (), keep: Iterable[str] = (), ip: bool = True
) -> str:
    """遮蔽手机号、邮箱、姓名、地址、身份证、银行卡、令牌/密钥/密码、内部 ID 等。

    ``sensitive_values`` 是工单里已知的客户字段值（姓名、手机号等），原样遮蔽；
    纯数字值至少 6 位才按值遮蔽，避免把版本号里的短数字误伤。``keep`` 原样保留（工单号）。
    """

    from modstore_server.cred_vault import redact as vault_redact

    out = str(text if text is not None else "")
    if not out:
        return ""
    kept: Dict[str, str] = {}
    for index, value in enumerate(v for v in keep if v):
        sentinel = f"\u0000KEEP{index}\u0000"
        kept[sentinel] = value
        out = out.replace(value, sentinel)
    values = {str(v).strip() for v in sensitive_values}
    values = {v for v in values if len(v) >= (6 if v.isdigit() else 2)}
    for value in sorted(values, key=len, reverse=True):
        out = out.replace(value, _mask("客户信息"))
    out = _PEM_RE.sub(_mask("凭据"), out)
    out = _URL_USERINFO_RE.sub(r"\1", out)
    out = _SECRET_KV_RE.sub(_mask("凭据"), out)
    out = vault_redact(out)
    out = _INTERNAL_ID_RE.sub(_mask("内部ID"), out)
    out = _NAME_LABEL_RE.sub(_mask("姓名"), out)
    out = _ADDRESS_LABEL_RE.sub(_mask("地址"), out)
    out = _ADDRESS_RE.sub(_mask("地址"), out)
    out = _EMAIL_RE.sub(_mask("邮箱"), out)
    out = _ID_CARD_RE.sub(_mask("身份证"), out)
    out = _MOBILE_RE.sub(_mask("手机号"), out)
    out = _BANK_CARD_RE.sub(_mask("银行卡"), out)
    out = _LANDLINE_RE.sub(_mask("电话"), out)
    if ip:
        out = _IPV4_RE.sub(_mask("IP"), out)
    out = _LONG_OPAQUE_RE.sub(_opaque, out)
    out = _DOT_REJECT_RE.sub(_mask("凭据"), out)
    for sentinel, value in kept.items():
        out = out.replace(sentinel, value)
    return out.replace("\u0000", "")


def _raw(req: Dict[str, Any]) -> Dict[str, Any]:
    raw = req.get("raw_input")
    return raw if isinstance(raw, dict) else {}


def ticket_fields(req: Dict[str, Any]) -> Dict[str, Any]:
    """工单字段：事故小组把工单载荷放在 ``incident`` 里，顶层字段兜底。"""

    raw = _raw(req)
    nested = raw.get("incident")
    incident: Dict[str, Any] = nested if isinstance(nested, dict) else {}
    return {**{k: v for k, v in raw.items() if k != "incident"}, **incident}


def is_customer_ticket(req: Dict[str, Any]) -> bool:
    raw = _raw(req)
    fields = ticket_fields(req)
    return (
        raw.get("event_type") == TICKET_EVENT
        or fields.get("source") == "customer_ticket"
        or str(fields.get("ticket_no") or "").startswith("CS")
    )


def triage_result(req: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    """分诊结果：优先 ``customer_ticket_triage`` 贴的快照（含终极员工介入），否则按 intent 推。"""

    from modstore_server.customer_ticket_triage import allow_code_fix, resolve_dispatch_lane

    raw = _raw(req)
    nested = raw.get("triage")
    snapshot: Dict[str, Any] = nested if isinstance(nested, dict) else {}
    intent = str(snapshot.get("intent") or raw.get("intent") or fields.get("intent") or "")
    intent = intent.strip().lower()
    if "allow_code_fix" in raw:
        allow = bool(raw.get("allow_code_fix"))
    else:
        allow = allow_code_fix(intent)
    lane = str(snapshot.get("triage_lane") or resolve_dispatch_lane(intent))
    return {"intent": intent, "allow_code_fix": allow, "triage_lane": lane}


def ticket_mode(req: Dict[str, Any], fields: Dict[str, Any]) -> str:
    """按分诊选模式：分诊允许修代码、非只读岗位且不涉账号类，才 code_fix。

    账号/登录/密码/权限类一律只出报告，终极员工介入也不能把它改成修代码。
    """

    triage = triage_result(req, fields)
    text = " ".join(
        str(fields.get(key) or "") for key in ("title", "summary", "intent", "issue_domain")
    )
    if (
        bool(req.get("report_only"))
        or not triage["allow_code_fix"]
        or triage["intent"] == "account_support"
        or _ACCOUNT_RE.search(text + " " + triage["intent"])
    ):
        return MODE_REPORT_ONLY
    return MODE_CODE_FIX


def control_marker(fields: Dict[str, Any], req: Dict[str, Any]) -> str:
    anchor = str(fields.get("ticket_no") or fields.get("ticket_id") or req.get("request_id") or "")
    task_part = hashlib.sha256(f"modstore-ticket:{anchor}".encode()).hexdigest()[:32]
    return f"[xcmax:{task_part}:{uuid.uuid4().hex}]"


def _sensitive_values(fields: Dict[str, Any]) -> List[str]:
    return [str(fields[key]) for key in _SENSITIVE_VALUE_KEYS if fields.get(key) not in ("", None)]


def build_dolt_prompt(fields: Dict[str, Any], req: Dict[str, Any], mode: str) -> str:
    ticket_no = re.sub(r"[^A-Za-z0-9_\-]", "", str(fields.get("ticket_no") or ""))[:64]
    triage = triage_result(req, fields)
    sensitive = _sensitive_values(fields)

    def clean(value: Any, limit: int = FIELD_LIMIT, ip: bool = True) -> str:
        return redact_ticket_text(value, sensitive, keep=[ticket_no], ip=ip)[:limit]

    summary = clean(fields.get("summary") or "", SUMMARY_LIMIT)
    lines = [
        "[dot 客服工单] 来源 MODstore；内容已在 MODstore 脱敏，只含工单号、分类、摘要和复现信息。",
        f"mode: {mode}",
        f"工单号: {ticket_no or '-'}",
        f"分类: intent={clean(triage['intent']) or '-'}, triage_lane={clean(triage['triage_lane'])}",
        f"岗位: {clean(fields.get('role')) or '-'}",
        f"标题（已脱敏）: {clean(fields.get('title') or '', 200) or '-'}",
        "问题摘要（已脱敏）:",
        summary or "-",
        "复现信息:",
    ]
    # 版本号形如 1.2.3.4，复现字段不按 IP 遮蔽。
    lines += [f"- {key}: {clean(fields.get(key), ip=False) or '-'}" for key in _REPRO_KEYS]
    lines.append("执行范围:")
    if mode == MODE_REPORT_ONLY:
        lines += [
            "report_only: true",
            "仅出报告：只读排查并写报告，不改代码、不推分支、不开 PR。",
        ]
    else:
        lines.append(
            "从记录的 source SHA 开分支，最小改动修复并开 PR；不合并、不部署、不重启、不改生产。"
        )
    lines.append(
        "不访问或输出密钥和客户数据，不发消息或通知；处理不了就回报 cannot_handle 并写明原因。"
    )
    return "\n".join(lines)


def prepare_dolt_ticket_payload(
    req: Dict[str, Any], payload: Dict[str, Any], tool_name: str
) -> Dict[str, Any]:
    """派给 dolt 的客服工单：加控制标记、选模式、只带脱敏内容；其余载荷原样返回。"""

    if tool_name != DOLT_TOOL or not is_customer_ticket(req):
        return payload
    fields = ticket_fields(req)
    mode = ticket_mode(req, fields)
    ticket_no = re.sub(r"[^A-Za-z0-9_\-]", "", str(fields.get("ticket_no") or ""))[:64] or "-"
    # dot 不合并、不用 MODstore 本机工作区：去掉自动合并和本地路径。
    out = {k: v for k, v in payload.items() if k not in {"auto_merge", "workspace_path"}}
    out.update(
        title=f"{control_marker(fields, req)} [dot:{mode}] 客服工单 {ticket_no}"[:240],
        prompt=build_dolt_prompt(fields, req, mode),
        subtask_title=f"{mode}: 客服工单 {ticket_no}"[:240],
        report_only=mode == MODE_REPORT_ONLY,
        tool_name=DOLT_TOOL,
    )
    return out
