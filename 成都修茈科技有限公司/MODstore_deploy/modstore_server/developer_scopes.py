"""开发者 PAT scope 约定与 Mod 同步 / 模型配置映射。

路由级强制校验尚未全量落地；此处集中 **允许写入的 scope 白名单** 与 **产品级推荐组合**，
供创建 Token、桌面导出与文档引用。
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Sequence, Tuple

# 当前 API 层已约定或文档中出现的 scope
KNOWN_SCOPES: FrozenSet[str] = frozenset(
    {
        "workflow:read",
        "workflow:execute",
        "employee:execute",
        "catalog:read",
        "webhook:manage",
        # 产品语义：桌面 Mod 同步 + 用平台 Token 配置/调用模型（与具体路由对齐见下表）
        "mod:sync",
        "llm:use",
    }
)

# 语义说明（供 UI / 文档展示；与 enforce 可逐步对齐）
SCOPE_ROUTE_HINTS: Dict[str, str] = {
    "mod:sync": "Mod/包目录：catalog 列表与下载、市场已购包下载等（与 catalog:read 组合使用）",
    "llm:use": "模型侧：员工执行、LLM 代理等（与 employee:execute 等组合使用）",
    "catalog:read": "GET /api/catalog/... 市场与包元数据",
    "employee:execute": "员工对话与工具调用链",
    "workflow:read": "工作流读取",
    "workflow:execute": "工作流触发与执行",
    "webhook:manage": "开发者 Webhook 订阅管理",
}

# 推荐一键勾选：桌面钥匙串典型能力
PRESET_DESKTOP_KEYCHAIN: Tuple[str, ...] = (
    "mod:sync",
    "catalog:read",
    "llm:use",
    "employee:execute",
)


def normalize_scopes_for_storage(scopes: Sequence[str]) -> List[str]:
    """去重保序；未知 scope 在 API 层应已拒绝。"""
    seen: set[str] = set()
    out: List[str] = []
    for s in scopes or []:
        t = (s or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def validate_scopes_or_raise(scopes: Sequence[str]) -> List[str]:
    """校验 scope 白名单，返回规范化列表；非法则抛 ValueError。"""
    bad = [s for s in (scopes or []) if (s or "").strip() and (s or "").strip() not in KNOWN_SCOPES]
    if bad:
        raise ValueError(f"未知 scope: {', '.join(bad)}；允许值见 KNOWN_SCOPES")
    return normalize_scopes_for_storage(scopes)
