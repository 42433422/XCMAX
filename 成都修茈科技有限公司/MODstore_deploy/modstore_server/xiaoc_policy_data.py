"""Immutable XiaoC permission-policy data and knowledge dataset identifiers."""

from __future__ import annotations

import copy
from typing import Any, Dict

PUBLIC_DATASET_ID = "persy-knowledge"
INTERNAL_DATASET_ID = "xiaoc-internal"
PERSY_DATASET_ID = PUBLIC_DATASET_ID
_PRIVATE_DATASET_PREFIXES = ("user_", "desktop_", "tenant_")
_DENY_PRIVATE_LABELS = (
    INTERNAL_DATASET_ID,
    "user_*",
    "desktop_private",
    "tenant_private",
)


_PUBLIC_ONLY_KNOWLEDGE: Dict[str, Any] = {
    "read_persy": True,
    "write_persy": False,
    "dataset_id": PUBLIC_DATASET_ID,
    "public_dataset_id": PUBLIC_DATASET_ID,
    "internal_dataset_id": INTERNAL_DATASET_ID,
    "datasets": {
        "read": [PUBLIC_DATASET_ID],
        "write": [],
        "deny": list(_DENY_PRIVATE_LABELS),
    },
}

XIAOC_PERMISSIONS: Dict[str, Dict[str, Any]] = {
    "external": {
        "label": "外部小C（官网公开）",
        "auth": "none",
        "knowledge": copy.deepcopy(_PUBLIC_ONLY_KNOWLEDGE),
        "tools": {
            "navigate": False,
            "click": False,
            "fill": False,
            "scroll": False,
            "read_page": False,
            "enhance_current_page": False,
            "wallet_pay": False,
            "refund": False,
            "admin_ops": False,
        },
        "allowed": [
            "产品/方案/案例介绍",
            "引导联系表单 /contact.html",
            "引导产品页 /services.html、市场 /market/",
            "仅基于公开库（persy-knowledge）只读摘录回答",
            "报价口径：需定制，引导留资（不编造合同金额）",
        ],
        "denied": [
            "浏览器工具调用（跳转/点击/填表/滚动/读页）",
            "vibe-coding / 改 Mod/工作流/员工",
            "支付、退款、下架、改价、改权限",
            "读取他人订单/隐私数据",
            "编造未公示资质/合同金额",
            "读取内部库 xiaoc-internal",
            "读取客户私有库 / 企业桌面私有库",
        ],
        "limits": {
            "max_reply_chars": 200,
            "rate_limit": "corp_chat_bucket",
            "llm_tools": False,
        },
    },
    "market_cs": {
        "label": "市场客服小C（已登录）",
        "auth": "login",
        "knowledge": copy.deepcopy(_PUBLIC_ONLY_KNOWLEDGE),
        "tools": {
            "navigate": False,
            "click": False,
            "fill": False,
            "scroll": False,
            "read_page": False,
            "enhance_current_page": False,
            "wallet_pay": False,
            "refund": False,  # 只建工单，不直接退款
            "admin_ops": False,
            "create_ticket": True,
        },
        "allowed": [
            "投诉/申诉/退款咨询并创建工单",
            "上架审核与账号权益问答",
            "仅基于公开库只读摘录回答产品问题",
        ],
        "denied": [
            "直接执行退款/下架",
            "页面自动化工具",
            "管理端运维操作",
            "读取内部库 xiaoc-internal",
            "读取客户私有库 / 企业桌面私有库",
        ],
        "limits": {
            "max_reply_chars": 600,
            "llm_tools": False,
        },
    },
    "admin": {
        "label": "管理端小C（内部主客服）",
        "auth": "login",
        "knowledge": {
            "read_persy": True,
            "write_persy": True,  # 写走知识库 UI/API；对话侧保证检索边界
            "dataset_id": PUBLIC_DATASET_ID,
            "public_dataset_id": PUBLIC_DATASET_ID,
            "internal_dataset_id": INTERNAL_DATASET_ID,
            "datasets": {
                "read": [PUBLIC_DATASET_ID, INTERNAL_DATASET_ID],
                "write": [PUBLIC_DATASET_ID, INTERNAL_DATASET_ID],
                "deny": ["user_*", "desktop_private", "tenant_private"],
            },
        },
        "tools": {
            "navigate": True,  # low
            "read_page": True,  # low
            "scroll": True,  # low
            "click": True,  # medium — 需预览确认
            "fill": True,  # medium — 需预览确认
            "enhance_current_page": True,  # high — 须明确确认
            "get_my_account_snapshot": True,  # admin only, self
            "get_my_wallet": True,
            "get_my_orders": True,
            "get_my_tickets": True,
            "get_ops_update_brief": True,
            "wallet_pay": False,  # 只引导到充值页，不代付
            "refund": False,
            "admin_ops": False,
        },
        "allowed": [
            "全站导航与页面摘要",
            "搜索/推荐 AI 员工",
            "引导充值与会员购买（不代付）",
            "在用户明确意图下发起 vibe-coding（高风险确认）",
            "检索公开库 + 内部库并回答",
            "管理员会话：本人账户/钱包/订单/工单只读摘要",
            "管理员会话：日更与 release_train 更新推送（只读）",
        ],
        "denied": [
            "未确认的高风险改文件/支付",
            "直接退款或后台运维危险操作",
            "查询他人账户/订单/工单",
            "触发 all-hands 重算或其它写操作运维",
            "读取客户私有库 / 企业桌面私有库",
        ],
        "limits": {
            "risk_model": "low_direct / medium_preview / high_confirm",
            "llm_tools": True,
            "tool_names": [
                "navigate",
                "click",
                "fill",
                "scroll",
                "read",
                "enhance_current_page",
                "get_my_account_snapshot",
                "get_my_wallet",
                "get_my_orders",
                "get_my_tickets",
                "get_ops_update_brief",
            ],
        },
    },
}
