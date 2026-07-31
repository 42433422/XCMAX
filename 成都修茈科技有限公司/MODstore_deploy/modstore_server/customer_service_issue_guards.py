"""Customer-service issue/privilege guard helpers (extracted for source-governance)."""

from __future__ import annotations

import re
from typing import Any

GREETING_RE = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|hi|hey|在吗|早上好|上午好|下午好|晚上好|你好呀|您好呀)"
    r"[!！。.?？~\s]*$",
    re.I,
)


def is_greeting(text: str) -> bool:
    return bool(GREETING_RE.match((text or "").strip()))


def _looks_like_forbidden_privilege_request(user_text: str) -> bool:
    """用户是否在索要管理员/提权等客服绝不能代办的权限。"""
    t = re.sub(r"\s+", "", (user_text or "").strip().lower())
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
    return any(x in t for x in marks)


def _refuse_forbidden_privilege_reply(user_text: str) -> str:
    """明确拒答：不承诺、不建提权动作、不派员工改权限。"""
    _ = user_text
    return (
        "我是小C。这个请求我不能办理："
        "客服与 AI 员工都无法为账号开通管理员或其它提权。"
        "管理员权限只能由平台运营在后台按合规流程配置。"
        "如果你遇到的是具体功能问题（比如页面打不开、显示异常），"
        "直接说现象和页面，我可以帮你登记排查；但不会、也不能改你的账号权限。"
    )


def _looks_like_product_issue(user_text: str) -> bool:
    """缺陷/界面故障语义：LLM 主判；此处仅作不可用/误判 general 时的兜底。"""
    t = (user_text or "").strip()
    if len(t) < 4 or is_greeting(t):
        return False
    if _looks_like_forbidden_privilege_request(t):
        return False
    # 不用 _is_escalate_only（其定义在后）；纯升级短句直接排除
    if re.fullmatch(
        r"(请)?(帮我)?(提交工单|创建工单|转人工|人工客服|升级处理|要工单|找人工)"
        r"(吧|一下|处理|核查)?[.!！。]?",
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
    return any(x in t for x in defect_marks)
