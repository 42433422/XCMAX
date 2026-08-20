# isort: skip_file
# ruff: noqa: E402, F401
"""每日运维 / 质量摘要邮件（APScheduler 触发）。

环境变量：
- ``MODSTORE_DAILY_DIGEST_ENABLED``：默认 ``1``，设为 ``0`` 关闭。
- ``MODSTORE_DAILY_DIGEST_EMAIL``：收件人，默认 ``1499383833@qq.com``；支持逗号或分号分隔多个地址。
- ``MODSTORE_DAILY_DIGEST_NOTIFY_USER_IDS``：可选，逗号分隔的用户 ID；摘要邮件**至少一封投递成功**后写入站内通知（SYSTEM）。
- ``MODSTORE_DAILY_DIGEST_RUN_PYTEST``：设为 ``1`` 时在摘要中附带 ``pytest tests/ -q``（可能较慢，超时 15 分钟）。
- ``MODSTORE_REPO_ROOT``：仓库根（与运维 handler 一致）。
- ``MODSTORE_GIT_BRANCH`` / ``MODSTORE_GIT_COMMIT``：摘要「仓库分支 / 最新提交」。生产镜像通常无 ``git`` 与 ``.git``，可设环境变量或 ``/app/.modstore_build.json``；若进程能在 ``MODSTORE_REPO_ROOT``（或默认部署根）下解析到 **Git 工作副本**，则**优先于** ``.modstore_build.json`` 显示实时分支与提交（环境变量仍最优先）。亦支持 ``MODSTORE_GIT_SHA`` / ``GIT_SHA`` / ``COMMIT_SHA``（与 ``/api/health`` 一致）。另有别名 ``GIT_BRANCH``、``GIT_COMMIT``、``VCS_REF``、``SOURCE_COMMIT``。
- ``MODSTORE_DAILY_BRIEF_ENABLED``：设为 ``1`` 时在摘要中追加各 catalog 在岗员工的「工作内容摘要 + 新方案」段落（默认 ``0``）。
- ``MODSTORE_DAILY_BRIEF_MAX``：最多生成几条岗位方案（默认 ``16``）。
- ``MODSTORE_DAILY_BRIEF_GROUND_YUANGON``：岗位简报是否预读 ``yuangon/<area>/<pkg_id>/`` 下真实文件注入 LLM（默认 ``1``；关闭设 ``0``）。依赖 ``MODSTORE_REPO_ROOT`` 含 yuangon 目录。
- ``MODSTORE_DAILY_BRIEF_GROUND_MAX_CHARS``：上述节选总字符上限（默认 ``60000``，最大可调到 ``200000``）。
- ``MODSTORE_DAILY_BRIEF_STRICT_GROUNDING``：设为 ``1`` 时岗位简报使用「可核对依据」版任务提示（三条建议须带 **依据** 行；默认 ``0``）。
- ``MODSTORE_DAILY_BRIEF_EXTRA_GLOBS_JSON``：JSON 对象，键为 ``pkg_id`` 或 ``"*"``，值为相对岗位目录的 glob 字符串数组，合并进节选（在固定清单与 ``prompts``/``tasks`` 之后）。
- 员工包 ``employee_config_v2.metadata.daily_brief_ground_paths``：同上，每包额外 glob 列表（与 env 合并）。
- ``MODSTORE_DAILY_DIGEST_CONSISTENCY``：设为 ``0`` 时跳过 ``yuangon`` 文档一致性扫描（默认启用；大仓库可关闭以缩短发送耗时）。
- ``MODSTORE_DIGEST_AUDIT_HINT``：设为 ``1`` 时在摘要邮件中附带运维审计/事件计数为何常为 0 的说明（scheduler、DB、nginx 路径）。
- ``MODSTORE_DAILY_VIBE_PREP_ENABLED``（默认 ``1``）：08:00 摘要落库后自动跑 Vibe 预备双 Markdown（更新 + 补丁），写入 ``daily_digest_records``。
- ``MODSTORE_DAILY_VIBE_PREP_MAX_EMPLOYEES``（默认 ``52``）：自动任务汇总员工上限。
- ``MODSTORE_DAILY_VIBE_PREP_USER_ID``：自动任务 bench LLM 使用的用户 ID（默认同 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED``（默认 ``1``）：Vibe 预备完成后将更新/补丁清单拆分写入 P-W / P-S / S-R 三产线字段。
- ``MODSTORE_DAILY_VIBE_EXECUTE_ENABLED``（默认 ``1``）：08:15 cron 消费 P-S + P-App 补丁清单并 ``dispatch_subtasks``（Phase A，不跑 P3–P9）。
- ``MODSTORE_DAILY_VIBE_EXECUTE_HOUR`` / ``MINUTE`` / ``TZ``：执行 cron 时刻（默认 08:15 北京时间）。
- ``MODSTORE_DAILY_VIBE_EXECUTE_PRIORITIES``：逗号分隔优先级过滤（默认 ``P0,P1,P2``）。
- ``MODSTORE_DAILY_VIBE_EXECUTE_MAX_UNITS``：单次最多派发条目数（默认 ``32``）。
- ``MODSTORE_DAILY_MEETING_USER_ID``（默认 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_ENABLED``（默认 ``1``）：08:00 摘要内 P-W/P-S/P-App 全量截图（P-W 公开商品详情 1–3 张；P-App adb 全屏）。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED``（默认 ``1``）：三端每条产线由「对应员工」bench LLM 生成现状 / 异常 / 改进建议分析；未配置 bench LLM 时回退规则化摘要。
- ``MODSTORE_DAILY_SURFACE_PPT_ENABLED``（默认 ``1``）：把三端截图 + 分析拼成 PowerPoint 作为邮件附件（见 ``daily_digest_surface_ppt.py``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL``：巡检根 URL（默认 ``https://xiu-ci.com``）。
- ``MODSTORE_APPROVAL_AUTHORIZED_FROM`` / ``MODSTORE_APPROVAL_TOKEN_TTL_HOURS``：回信审批白名单与令牌 TTL；每日摘要**无论是否有待审改动**都会附带一枚 **身份校验** 令牌（``kind=digest_identity``，6 位十六进制）；有待审分支时表格内另有按行的 ``approve_one``。``digest_identity`` 在摘要生成后即写入 ``OpsApprovalToken``（与存档 HTML 一致），**不依赖**邮件是否投递成功；按行 ``approve_one`` 仍仅在至少一封摘要邮件投递成功后才入库，避免未发邮件即可部署。
- ``MODSTORE_TLS_CERT_PATHS``：逗号/分号分隔的 PEM 证书路径（用于 TLS 到期巡检段落）；未配置则跳过。
- ``CERT_EXPIRY_INFO_DAYS`` / ``CERT_EXPIRY_WARN_DAYS`` / ``CERT_EXPIRY_CRIT_DAYS``：证书分级阈值（默认 60 / 30 / 14 天）；WARNING/CRITICAL 会写入 ``security.alert`` 事件。
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from sqlalchemy import func

from modstore_server.email_service import (
    send_html_email_with_attachments,
    send_simple_html_email,
)
from modstore_server.models import (
    CatalogItem,
    DailyDigestRecord,
    EmployeeExecutionMetric,
    IncidentEvent,
    OpsActionAuditLog,
    OpsApprovalToken,
    OpsStagedChange,
    get_session_factory,
)

logger = logging.getLogger(__name__)


from modstore_server.daily_digest_part01 import (
    digest_calendar_day as digest_calendar_day,
)

DEFAULT_DIGEST_EMAIL = "1499383833@qq.com"


from modstore_server.daily_digest_part02 import (
    _new_unique_ops_token_plain as _new_unique_ops_token_plain,
    parse_daily_digest_recipient_emails as parse_daily_digest_recipient_emails,
    _notify_daily_digest_in_app as _notify_daily_digest_in_app,
    _html_to_text_excerpt as _html_to_text_excerpt,
    count_on_duty_employees as count_on_duty_employees,
    autonomy_decisions_digest_html as autonomy_decisions_digest_html,
    count_catalog_employee_packs as count_catalog_employee_packs,
)

# ---------------------------------------------------------------------------
# 邮件视觉基元（presentation primitives）
# 纯函数 · 无 DB / 无副作用，邮件安全（全内联样式），便于本地预览与复用。
# ---------------------------------------------------------------------------

# 状态色板： (前景, 背景, 边框)
_DIGEST_TONES: Dict[str, Tuple[str, str, str]] = {
    "ok": ("#047857", "#ecfdf5", "#a7f3d0"),
    "warn": ("#b45309", "#fffbeb", "#fde68a"),
    "crit": ("#b91c1c", "#fef2f2", "#fecaca"),
    "info": ("#1d4ed8", "#eff6ff", "#bfdbfe"),
    "muted": ("#475569", "#f1f5f9", "#e2e8f0"),
}


from modstore_server.daily_digest_part03 import (
    _status_pill as _status_pill,
    _section_title as _section_title,
    _hero_overview_html as _hero_overview_html,
    _render_digest_document as _render_digest_document,
    _persist_daily_digest_record as _persist_daily_digest_record,
    _run_scheduled_digest_vibe_prep as _run_scheduled_digest_vibe_prep,
    _repo_root as _repo_root,
    _consistency_check_html as _consistency_check_html,
    _git_line as _git_line,
    _git_worktree_root as _git_worktree_root,
    _digest_commit_display as _digest_commit_display,
    _digest_git_branch_and_head as _digest_git_branch_and_head,
    _pytest_lastfailed_snippet as _pytest_lastfailed_snippet,
    _cursor_error_lines_count as _cursor_error_lines_count,
    _audit_digest_hint_html as _audit_digest_hint_html,
    _publish_tls_cert_security_alerts as _publish_tls_cert_security_alerts,
    _tls_cert_digest_html as _tls_cert_digest_html,
    _nginx_tail_hint as _nginx_tail_hint,
    _run_pytest_summary as _run_pytest_summary,
    _digest_system_work_summary_html as _digest_system_work_summary_html,
    _digest_kpi_cards_html as _digest_kpi_cards_html,
)


from modstore_server.daily_digest_part04 import (
    _meeting_minutes_md_to_html as _meeting_minutes_md_to_html,
    _surface_meeting_topic as _surface_meeting_topic,
    _surface_audit_meeting_minutes_html as _surface_audit_meeting_minutes_html,
    build_meeting_minutes_html_sync as build_meeting_minutes_html_sync,
    _daily_meeting_error_card as _daily_meeting_error_card,
    _daily_meeting_outer_timeout_sec as _daily_meeting_outer_timeout_sec,
    _build_meeting_minutes_html_bounded as _build_meeting_minutes_html_bounded,
    build_digest_html as build_digest_html,
    build_digest_approval_bundle as build_digest_approval_bundle,
    _surface_audit_failed_bundle as _surface_audit_failed_bundle,
    _build_surface_audit_bundle as _build_surface_audit_bundle,
)


from modstore_server.daily_digest_part05 import (
    run_daily_digest_email as run_daily_digest_email,
    cron_trigger_for_digest as cron_trigger_for_digest,
)
