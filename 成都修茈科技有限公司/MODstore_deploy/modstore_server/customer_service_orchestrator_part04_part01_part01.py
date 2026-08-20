# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def _looks_like_raw_kb_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True
    if _facade()._RAW_STRUCTURE_RE.search(s):
        return True
    if s.count("{") + s.count("}") >= 2:
        return True
    if s.startswith("【") and "摘录" in s:
        return True
    return False


def _human_kb_tips(kb: str, *, limit: int = 3) -> list[str]:
    """从知识库块里只取可读自然语言行，过滤模板/JSON 脏数据。"""
    tips: list[str] = []
    for raw in (kb or "").splitlines():
        ln = raw.strip()
        if not ln or _facade()._looks_like_raw_kb_line(ln):
            continue
        if _facade().re.match("^\\d+[\\.、]\\s*", ln):
            ln = _facade().re.sub("^\\d+[\\.、]\\s*", "", ln)
        if ". " in ln[:5]:
            ln = ln.split(". ", 1)[-1].strip()
        if len(ln) < 8 or _facade()._looks_like_raw_kb_line(ln):
            continue
        tips.append(ln[:120])
        if len(tips) >= limit:
            break
    return tips


def _display_name_for_user(
    user: _facade().Optional[_facade().User],
    *,
    db: _facade().Optional[_facade().Session] = None,
) -> tuple[str, str]:
    address = ""
    member_hint = ""
    try:
        from modstore_server.xiaoc_cs_ssot import resolve_user_identity

        if user is not None:
            ident = resolve_user_identity(user, db=db, source="market_cs")
            address = ident.display_name
            if ident.membership and ident.membership != "普通用户":
                member_hint = f"（{ident.membership}）"
            elif ident.account_role == "admin":
                member_hint = "（管理员）"
    except RECOVERABLE_ERRORS:
        pass
    return (address, member_hint)


def _summarize_user_issue(user_text: str, *, max_len: int = 48) -> str:
    """压缩用户原话，供兜底复述；去掉寒暄前缀。"""
    t = _facade().re.sub("\\s+", "", (user_text or "").strip())
    for prefix in ("我有问题", "有个问题", "请问一下", "请问", "你好", "您好"):
        if t.startswith(prefix):
            t = t[len(prefix) :]
            break
    t = t.lstrip("，,。.!！、：:")
    if not t:
        t = (user_text or "").strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _looks_like_forbidden_privilege_request(user_text: str) -> bool:
    """用户是否在索要管理员/提权等客服绝不能代办的权限。"""
    t = _facade().re.sub("\\s+", "", (user_text or "").strip().lower())
    if len(t) < 4:
        return False
    marks = (
        "管理员权限",
        "给我管理员",
        "开通管理员",
        "设为管理员",
        "设置管理员",
        "升级管理员",
        "变成管理员",
        "改成管理员",
        "超级管理员",
        "要admin",
        "给我admin",
        "开通admin",
        "admin权限",
        "root权限",
        "提权",
        "给我权限后台",
        "开放后台权限",
        "给我后台权限",
        "is_admin",
        "升为管理员",
    )
    return any((x in t for x in marks))


def _refuse_forbidden_privilege_reply(user_text: str) -> str:
    """明确拒答：不承诺、不建提权动作、不派员工改权限。"""
    _ = user_text
    return "我是小C。这个请求我不能办理：客服与 AI 员工都无法为账号开通管理员或其它提权。管理员权限只能由平台运营在后台按合规流程配置。如果你遇到的是具体功能问题（比如页面打不开、显示异常），直接说现象和页面，我可以帮你登记排查；但不会、也不能改你的账号权限。"


def _looks_like_product_issue(user_text: str) -> bool:
    """缺陷/界面故障语义：LLM 主判；此处仅作不可用/误判 general 时的兜底。"""
    t = (user_text or "").strip()
    if len(t) < 4 or _facade().is_greeting(t):
        return False
    if _facade()._looks_like_forbidden_privilege_request(t):
        return False
    if _facade().re.fullmatch(
        "(请)?(帮我)?(提交工单|创建工单|转人工|人工客服|升级处理|要工单|找人工)(吧|一下|处理|核查)?[.!！。]?",
        t,
    ):
        return False
    defect_marks = (
        "看不清",
        "看不见",
        "看不清字",
        "浅色",
        "深色",
        "对比度",
        "自选模型",
        "打不开",
        "进不去",
        "报错",
        "白屏",
        "黑屏",
        "闪退",
        "卡住",
        "加载失败",
        "加载不出来",
        "加载不出",
        "打不开网页",
        "打不开网站",
        "首页",
        "官网",
        "没反应",
        "用不了",
        "点不了",
        "点了没用",
        "按钮无效",
        "显示异常",
        "文字看不见",
        "界面",
        "崩了",
        "bug",
        "故障",
        "坏了",
    )
    return any((x in t for x in defect_marks))


def _looks_like_concrete_issue(user_text: str) -> bool:
    """用户是否已描述具体问题（而非空话/寒暄）。"""
    t = (user_text or "").strip()
    if len(t) < 6:
        return False
    if _facade().is_greeting(t):
        return False
    if _facade()._looks_like_product_issue(t):
        return True
    if any(
        (
            x in t
            for x in (
                "看不清",
                "看不见",
                "看不清字",
                "浅色",
                "深色",
                "对比",
                "对比度",
                "按钮",
                "自选模型",
                "打不开",
                "进不去",
                "失败",
                "报错",
                "卡住",
                "加载",
                "空白",
                "闪退",
                "用不了",
                "没反应",
                "太慢",
                "bug",
                "Bug",
                "问题",
                "故障",
                "异常",
            )
        )
    ):
        return True
    return len(_facade().re.sub("\\s+", "", t)) >= 10


def _ack_concrete_issue_reply(user_text: str, *, hello: str, ticketed: bool) -> str:
    """知识库无可用摘录时：复述用户问题，不再甩购买/会员开场白。"""
    summary = _facade()._summarize_user_issue(user_text)
    if ticketed:
        return f"我是小C。{hello}已记下你的问题：「{summary}」，并登记工单；你可以继续补充页面位置、截图或复现步骤，我们会尽快处理。"
    return f"我是小C。{hello}收到，你说的是「{summary}」。方便补充一下大概在哪个页面/功能、是文字还是图标按钮吗？需要正式跟进修复时，点击「提交工单」即可。"


def _xiaoc_general_reply(
    user_text: str,
    *,
    user: _facade().Optional[_facade().User] = None,
    db: _facade().Optional[_facade().Session] = None,
    ticketed: bool = False,
) -> str:
    """general 意图走小C SSOT；只输出可读话术，绝不把知识库原始结构甩给客户。"""
    address, member_hint = _facade()._display_name_for_user(user, db=db)
    hello = (
        f"{address}{member_hint}，"
        if address and address not in {"用户", "访客", "匿名访客"}
        else ""
    )
    kb = ""
    try:
        from modstore_server.xiaoc_cs_ssot import knowledge_block_for_query

        kb = knowledge_block_for_query(user_text, top_k=4, mode="market_cs")
    except RECOVERABLE_ERRORS:
        kb = ""
    tips = _facade()._human_kb_tips(kb)
    concrete = _facade()._looks_like_concrete_issue(user_text)
    if concrete:
        return _facade()._ack_concrete_issue_reply(user_text, hello=hello, ticketed=ticketed)
    if tips:
        body = "；".join(tips)
        return f"我是小C。{hello}{body} 若还要补充，直接说具体场景就行。"
    if ticketed:
        return f"我是小C。{hello}已为你登记工单；你可以继续补充材料，我们会尽快处理。"
    return f"我是小C。{hello}可以先说说你的具体问题，比如购买、会员权益、订单或余额；需要正式受理时我会帮你建工单。"


def build_reply(
    *,
    ticket: _facade().CustomerServiceTicket,
    decision: _facade().CustomerServiceDecision,
    actions: list[_facade().Any],
    extracted: _facade().Dict[str, _facade().Any],
) -> tuple[str, list[_facade().Dict[str, _facade().Any]]]:
    intent = ticket.intent or "general"
    intent_cn = {
        "refund": "退款",
        "catalog_complaint": "投诉",
        "catalog_review": "上架审核",
        "account_support": "账号权益",
        "llm_extension": "模型扩展",
        "product_issue": "功能问题",
        "general": "咨询",
    }.get(intent, "咨询")
    if intent == "account_support":
        reply = "我是小C。已记下你的账号/余额问题。请补充最近一次充值或扣费的时间、金额，或钱包页截图；发完后我会继续处理。"
    elif decision.decision == "needs_more_info":
        reply = f"我是小C。{intent_cn}已收到。{decision.rationale}直接在对话里补充即可。"
    elif decision.decision == "accepted":
        reply = f"我是小C。你的{intent_cn}已登记，正在跟进处理；还不会结案。可继续补充截图或具体页面，我们会尽快回复。"
    elif actions:
        action_cn = {
            "refund.apply": "退款申请",
            "catalog.complaint.create": "投诉登记",
            "catalog.compliance.review": "合规审核",
            "llm.model_capability.propose": "模型扩展申请",
            "employee.dispatch": "转交处理",
        }
        done = "、".join(
            (
                action_cn.get(str(getattr(a, "action_type", "")), "")
                for a in actions
                if getattr(a, "status", "") in {"completed", "skipped"}
            )
        )
        done = "、".join((x for x in done.split("、") if x))
        if done:
            reply = f"我是小C。你的{intent_cn}已受理，并已完成：{done}。"
        else:
            reply = f"我是小C。你的{intent_cn}已受理，正在处理中。"
    else:
        reply = f"我是小C。你的{intent_cn}已受理。{decision.rationale}"
    life = _facade().ticket_lifecycle_payload(ticket.status, ticket.decision_status)
    cards = [
        {
            "type": "ticket",
            "title": ticket.title,
            "ticket_no": ticket.ticket_no,
            "status": ticket.status,
            "intent": ticket.intent,
            "subject_type": ticket.subject_type,
            "subject_id": ticket.subject_id,
            **life,
        },
        {
            "type": "decision",
            "decision": decision.decision,
            "rationale": decision.rationale,
            "status": ticket.status,
            **{k: life[k] for k in ("lifecycle_stage", "lifecycle_label")},
        },
    ]
    if actions:
        cards.append({"type": "actions", "items": [_facade().action_payload(a) for a in actions]})
    return (reply, cards)


def resolve_issue_domain(
    *,
    intent: str,
    text: str,
    extracted: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    llm_domain: _facade().Any = None,
) -> _facade().Dict[str, str]:
    """判定问题归属：platform / software / custom。

    custom = 宿主入门第三步定制线交付的账号定制功能 Mod / 定制员工（非公开市场上架）。
    """
    data = extracted or {}
    ctx = context or {}
    t = (text or "").strip()
    scene = str(data.get("scene") or ctx.get("scene") or "").strip().lower()
    pkg_id = str(data.get("pkg_id") or ctx.get("pkg_id") or "").strip()
    catalog_id = data.get("catalog_id") or ctx.get("catalog_id")
    artifact = str(data.get("artifact") or ctx.get("artifact") or "").strip().lower()
    account_custom_flag = data.get("account_custom")
    if account_custom_flag is None:
        account_custom_flag = ctx.get("account_custom")
    account_custom = str(account_custom_flag or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "custom",
        "account_custom",
    }

    def _pack(domain: str, source: str) -> _facade().Dict[str, str]:
        d = domain if domain in _facade().ISSUE_DOMAINS else "platform"
        return {
            "domain": d,
            "label": _facade().ISSUE_DOMAIN_LABELS.get(d, "平台"),
            "source": source,
        }

    clarify = _facade()._parse_domain_clarify_reply(t)
    if clarify:
        return _pack(clarify, "user_clarify")
    custom_marks = (
        "客户定制",
        "账号定制",
        "定制线",
        "定制员工",
        "定制 mod",
        "定制Mod",
        "定制功能",
        "白标",
        "专属皮肤",
        "专属员工",
        "未上架员工",
    )
    if (
        account_custom
        or scene in {"custom", "account_custom", "定制"}
        or artifact in {"account_custom", "custom"}
        or any((x in t for x in custom_marks))
        or str(pkg_id).startswith(("custom_", "acct_custom_", "account_custom_"))
    ):
        return _pack("custom", "rules_custom")
    if intent in {"catalog_complaint", "catalog_review"}:
        return _pack("software", "rules_catalog_intent")
    if catalog_id not in (None, "", 0, "0") or pkg_id:
        return _pack("software", "rules_catalog_ref")
    if any((x in t for x in ("商品", "这个 mod", "这个Mod", "员工包", "扩展市场", "我买的"))):
        return _pack("software", "rules_software_text")
    llm_d = str(llm_domain or data.get("issue_domain") or "").strip().lower()
    if llm_d in _facade().ISSUE_DOMAINS:
        if llm_d == "software" and (not (catalog_id or pkg_id)):
            pass
        else:
            return _pack(llm_d, "llm")
    if intent in {"refund", "account_support", "llm_extension", "greeting"}:
        return _pack("platform", "rules_platform_intent")
    if intent == "product_issue" or _facade()._looks_like_product_issue(t):
        return _pack("platform", "rules_product_default")
    return _pack("platform", "default")
