# ruff: noqa: E402, F401
"""每日摘要 · 三端页面截图巡检（P-W 网站 / P-S 软件 / P-App 移动 App 面）。

Playwright 抓取关键 URL 全页截图，记录 HTTP 状态与 console error，供邮件段落与 Vibe 预备引用。

环境变量：
- ``MODSTORE_DAILY_SURFACE_AUDIT_ENABLED``（默认 ``1``）：设为 ``0`` 关闭本段落。
- ``MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL``：站点根（默认 ``https://xiu-ci.com``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_MS``（默认 ``45000``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_MODE``（默认 ``daily``）：``daily`` 日更 — P-W/P-S/P-App 全量，P-W 公开商品详情仅 1–3 张；``sample`` 三产线各 1 张；``full`` 同 ``daily``（CI 别名）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_MAX_PER_LANE``（默认 ``1``）：仅 ``sample`` 模式下每产线最多几张。
- ``MODSTORE_DAILY_SURFACE_AUDIT_SAVE_DIR``：可选，保存 PNG 目录（默认 ``playwright-report/digest-surfaces`` 相对仓库根）。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED``（默认 ``1``）：是否对每条产线截图调用 bench LLM 生成「对应员工」的现状 / 异常 / 改进建议分析；未配置 bench LLM 时回退到基于 HTTP / console 的规则化摘要。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_USER_ID``：分析调用 bench LLM 使用的用户 ID（默认同 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_SURFACE_AUDIT_USER`` / ``MODSTORE_SURFACE_AUDIT_PASSWORD``：AI 市场 SPA 截图前登录（默认 ``admin`` / ``admin123``）。
- ``MODSTORE_SURFACE_AUDIT_API_URL``：登录 API 根（默认 ``MODSTORE_INTERNAL_API_BASE`` 或站点 ``base_url``）。
- ``MODSTORE_SURFACE_AUDIT_ANDROID``（默认 ``1``）：P-App 走本地 adb + 模拟器（``FHD/scripts/ci/run_android_surface_audit.mjs``），不再用 Playwright 移动 Web 截 xiu-ci.com。
- ``MODSTORE_SURFACE_AUDIT_CATALOG_MAX``（默认 ``3``）：P-W 市场公开商品详情 ``/market/catalog/:id`` 抽样 1–3 张（0=不截 catalog）。
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


from modstore_server.daily_digest_surface_audit_part01 import (
    _internal_api_base as _internal_api_base,
)


_DESKTOP_VIEWPORT = {"width": 1280, "height": 720}
_MOBILE_VIEWPORT = {"width": 390, "height": 844}


from modstore_server.daily_digest_surface_audit_part02 import (
    SurfaceTarget as SurfaceTarget,
)


_STATIC_PW_PAGES: Tuple[Tuple[str, str], ...] = (
    ("官网首页", "/"),
    ("关于修茈", "/about.html"),
    ("产品中心", "/services.html"),
    ("解决方案", "/solutions.html"),
    ("客户案例", "/cases.html"),
    ("制造案例", "/case-manufacture.html"),
    ("教育案例", "/case-edu.html"),
    ("园区案例", "/case-park.html"),
    ("新闻资讯", "/news.html"),
    ("资质荣誉", "/honors.html"),
    ("联系我们", "/contact.html"),
    # /developer.html 和 /excel-to-ai.html 已确认服务器返回首页内容（title/innerText 与 index.html 完全相同）→ 移除
)

_PW_MARKET_ENTRY_PAGES: Tuple[Tuple[str, str], ...] = (("软件下载", "/market/workbench/download"),)
_PW_MARKET_ADMIN_PAGES: Tuple[Tuple[str, str], ...] = (
    ("管理端·数据库管理", "/market/admin/database"),
    ("管理端·值班员工", "/market/admin/duty-employees"),
    ("管理端·运维审计", "/market/admin/ops-audit"),
    ("管理端·员工自主决策", "/market/admin/employee-autonomy"),
    ("管理端·变更请求", "/market/admin/change-requests"),
    ("管理端·员工入职", "/market/admin/yuangon-onboard"),
    ("管理端·编排任务", "/market/admin/orchestrate-jobs"),
    ("管理端·客服审核", "/market/admin/customer-service"),
    ("管理端·管家技能", "/market/admin/butler-skills"),
    ("管理端·AI 账号池", "/market/admin/ai-accounts"),
)
_PW_WB_MODE_PAGES: Tuple[Tuple[str, str], ...] = (
    ("工作台·聊", "/market/workbench/home", "direct"),
    ("工作台·做", "/market/workbench/home", "make"),
    ("工作台·说", "/market/workbench/home", "voice"),
)

_PW_SIDEBAR_PAGES: Tuple[Tuple[str, str], ...] = (
    ("AI 客服", "/market/customer-service"),
    ("沙箱测试", "/market/ai-test/sandbox"),  # /market/sandbox 是客户端重定向，用规范路径
)


_PS_PUBLIC_PAGES: Tuple[Tuple[str, str], ...] = (
    ("会员方案", "/market/plans"),
    ("登录页", "/market/login"),
    ("注册页", "/market/register"),
)

_PAPP_PUBLIC_PAGES: Tuple[Tuple[str, str], ...] = (
    ("智能生态（移动）", "/ai-ecosystem"),
    ("市场落地页（移动）", "/market/about"),
    ("软件下载（移动）", "/market/workbench/download"),
)

# P-S 软件（本地企业版客户端 · 127.0.0.1:5001）：与 FHD config/surface_audit_pages.json
# 的 P-S lane 同源（enterprise SKU），让邮件「三端」P-S 栏不再为空。
_PS_DESKTOP_PAGES: Tuple[Tuple[str, str], ...] = (
    ("智能对话", "/"),
    ("智能生态", "/ai-ecosystem"),
    ("产品管理", "/products"),
    ("客户管理", "/customers"),
    ("订单管理", "/orders"),
    ("出货记录", "/shipment-records"),
    ("审批中心", "/approval-hub/workspace"),
    ("库存管理", "/inventory"),
    ("MODstore", "/mod-store"),
    ("设置", "/settings"),
    ("桥接控制台", "/console"),
    ("批量分析", "/batch-analyze"),
    ("规划桥 Mod", "/mod/xcagi-planner-bridge/chat"),
)

_AI_STORE_TABS: Tuple[Tuple[str, str], ...] = (("AI市场-AI员工", "ai_employee"),)

_AI_STORE_TAB_LABELS: Dict[str, str] = {
    "all": "全部商品",
    "host_foundation": "宿主基础员工",
    "office": "办公员工包",
    "workflow": "工作流员工",
    "ai_employee": "AI 员工",
}
_PW_AI_MARKET_EXTRA_PAGES: Tuple[Tuple[str, str, str], ...] = (
    ("钱包", "/market/wallet", ""),
    ("已购商品", "/market/wallet/purchased", ""),
    ("订单列表", "/market/orders", ""),
)

# 账户/通知/AI考试 — 登录后有侧栏/用户菜单直接入口
_PW_ACCOUNT_PAGES: Tuple[Tuple[str, str], ...] = (
    ("账户设置", "/market/account"),
    ("通知中心", "/market/notifications"),
    ("使用统计", "/market/analytics"),
    ("退款申请", "/market/refunds"),
    ("开发者门户", "/market/dev"),
)

# AI 考试独立 Tab（AiTestLayout 下 Tab 栏）
_PW_AI_TEST_PAGES: Tuple[Tuple[str, str], ...] = (("AI员工考试", "/market/ai-test/exam"),)

# 工作台核心子页（WorkbenchView 顶栏有直接入口）
_PW_WORKBENCH_PAGES: Tuple[Tuple[str, str], ...] = (
    ("统一工作台", "/market/workbench/unified"),
    ("我的员工", "/market/workbench/employees"),
    ("我的素材", "/market/workbench/materials"),
    ("脚本工作流", "/market/workbench/script-workflows"),
)


from modstore_server.daily_digest_surface_audit_part03 import (
    _base_url as _base_url,
    _ps_base_url as _ps_base_url,
    _ps_audit_enabled as _ps_audit_enabled,
    _safe_slug_name as _safe_slug_name,
    _fetch_market_catalog_sync as _fetch_market_catalog_sync,
    _surface_audit_mode as _surface_audit_mode,
    _is_full_surface_audit as _is_full_surface_audit,
    _is_sample_surface_audit as _is_sample_surface_audit,
    _is_daily_surface_audit as _is_daily_surface_audit,
    _max_targets_per_lane as _max_targets_per_lane,
    _catalog_screenshot_max as _catalog_screenshot_max,
    _catalog_fetch_enabled as _catalog_fetch_enabled,
    _stable_sample_catalog_items as _stable_sample_catalog_items,
    _is_ai_employee_material as _is_ai_employee_material,
    _filter_catalog_ai_employee_items as _filter_catalog_ai_employee_items,
    _is_ai_employee_store_target as _is_ai_employee_store_target,
    _is_ps_ai_employee_target as _is_ps_ai_employee_target,
    _is_papp_ai_ecosystem_target as _is_papp_ai_ecosystem_target,
    _pick_lane_sample_target as _pick_lane_sample_target,
    _pick_sample_targets as _pick_sample_targets,
    _limit_targets_per_lane as _limit_targets_per_lane,
    _append_pw_catalog_targets as _append_pw_catalog_targets,
    _pw_catalog_items_for_daily as _pw_catalog_items_for_daily,
    _build_pw_full_targets as _build_pw_full_targets,
    build_digest_surface_targets as build_digest_surface_targets,
    build_surface_targets as build_surface_targets,
    default_surface_targets as default_surface_targets,
    _repo_root as _repo_root,
    _png_fingerprint as _png_fingerprint,
    compute_surface_baseline_delta as compute_surface_baseline_delta,
    baseline_delta_excerpt_markdown as baseline_delta_excerpt_markdown,
    _save_dir as _save_dir,
)


_MARKET_AUTH_SKIP_PREFIXES: Tuple[str, ...] = (
    "/market/login",
    "/market/register",
    "/market/login-email",
    "/market/forgot-password",
)


from modstore_server.daily_digest_surface_audit_part04 import (
    _path_needs_market_auth as _path_needs_market_auth,
    _parse_set_cookie_headers as _parse_set_cookie_headers,
    _surface_demo_account_defaults as _surface_demo_account_defaults,
    _surface_audit_login_api_base as _surface_audit_login_api_base,
    _login_surface_audit_sync as _login_surface_audit_sync,
    _fetch_admin_digest_code_sync as _fetch_admin_digest_code_sync,
    _inject_admin_digest as _inject_admin_digest,
    _prepare_admin_digest as _prepare_admin_digest,
    _cookie_url_for_auth as _cookie_url_for_auth,
    _inject_market_auth as _inject_market_auth,
    _goto_with_retry as _goto_with_retry,
)


_TRANSIENT_NAV_ERROR_MARKERS: Tuple[str, ...] = (
    "Timeout",
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_RESET",
    "ERR_NETWORK_CHANGED",
    "ERR_HTTP2_PROTOCOL_ERROR",
    "ERR_QUIC_PROTOCOL_ERROR",
    "net::ERR_FAILED",
)


from modstore_server.daily_digest_surface_audit_part05 import (
    _surface_capture_retry_count as _surface_capture_retry_count,
    _is_retryable_surface_row as _is_retryable_surface_row,
    _wait_page_ready as _wait_page_ready,
    _apply_page_prepare as _apply_page_prepare,
    _apply_page_prepare_step as _apply_page_prepare_step,
    _capture_one as _capture_one,
)


# ─── 三端 lane → 对应在岗员工 ───────────────────────────────────────────────
#
# 与 ``duty_roster.SIX_LINE_DEPARTMENTS`` 对齐：
# - P-W   → ``prod_web``（网站部）关键子区：营销静态 / 市场 SPA / 文档 SEO
# - P-S   → ``prod_software``（软件部）关键子区：核心编码 / 测试 / 编排
# - P-App → 移动发布官 + 市场前端（移动端 WebView 由 market SPA 复用）
_LANE_OWNER_FALLBACK: Dict[str, List[str]] = {
    "P-W": [
        "site-content-editor",
        "marketing-site-builder",
        "seo-sitemap-curator",
        "market-frontend-dev",
    ],
    "P-S": [
        "fhd-core-maintainer",
        "vibe-coding-maintainer",
        "test-qa-runner",
        "market-frontend-dev",
    ],
    "P-App": [
        "mobile-android-release-officer",
        "mobile-ios-release-officer",
        "market-frontend-dev",
    ],
}

_LANE_TO_DEPARTMENT = {"P-W": "prod_web", "P-S": "prod_software"}


from modstore_server.daily_digest_surface_audit_part06 import (
    lane_employee_ids as lane_employee_ids,
    _rule_based_lane_analysis as _rule_based_lane_analysis,
    _surface_analysis_timeout_sec as _surface_analysis_timeout_sec,
    _build_lane_analysis_user_content as _build_lane_analysis_user_content,
)


_LANE_ANALYSIS_SYSTEM = """你是 MODstore「{lane}」产线在岗 AI 员工（{owners}）。
数字管家把本产线今天的页面巡检结果交给你，请只用本产线视角，基于给出的 HTTP 状态、
页面标题、console 报错等**确凿事实**写一段简体中文分析，**不得编造**未给出的内容。

严格按以下结构输出（不要加多余前后缀，控制在 6 行内）：
现状：<一句话概括本产线页面整体是否健康>
异常：<逐条列出 HTTP≥400 / 抓取失败 / console 报错；没有则写「无」>
改进建议：<1-3 条可落地动作，点名本产线相关文件或岗位；信息不足写「待确认」>"""


from modstore_server.daily_digest_surface_audit_part07 import (
    analyze_surface_lanes as analyze_surface_lanes,
    _capture_surface_target_async as _capture_surface_target_async,
    run_surface_audit_async as run_surface_audit_async,
    _lane_summary as _lane_summary,
    _lane_analysis_md as _lane_analysis_md,
    surface_audit_excerpt_markdown as surface_audit_excerpt_markdown,
    _render_analysis_block_html as _render_analysis_block_html,
    _render_lane_html as _render_lane_html,
    _lane_count_overview_html as _lane_count_overview_html,
    _surface_audit_badge as _surface_audit_badge,
    _email_lane_row_cap as _email_lane_row_cap,
    build_surface_audit_html_sync as build_surface_audit_html_sync,
)
