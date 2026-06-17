"""XC AGI 邮件发送服务：基于 QQ邮箱 SMTP 发送验证码。

诊断与排障约定：
- 当 ``MODSTORE_SMTP_USER`` / ``MODSTORE_SMTP_PASSWORD`` 任一为空 **或者** 命中
  常见占位符（``your-...``、``CHANGE_ME``、``change_me`` 等）时，视作未配置。
  这样可以避免管理员把 ``.env.production`` 模板原封不动复制到生产、
  HTTP 先返回 202、SMTP login 阶段才暴露错误的"假性已配置"陷阱。
- 调试场景设 ``MODSTORE_EMAIL_DEBUG=1``：跳过 SMTP，把验证码打印到控制台。
- 管理员可通过 :mod:`modstore_server.email_admin_api` 的端点
  ``GET /api/admin/email/status`` / ``POST /api/admin/email/test`` 二秒诊断。
"""

from __future__ import annotations

import mimetypes
import os
import random
import re
import smtplib
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func

from modstore_server.env_loader import load_modstore_env
from modstore_server.models import User, get_session_factory

_MODSTORE_ROOT = Path(__file__).resolve().parent.parent

# 常见占位符模板：值里出现这些子串时视为"未填写"，连带 SMTP 视作未配置。
# 用 lower() 比对，匹配大小写无关。
_PLACEHOLDER_HINTS = (
    "your-",
    "your_",
    "change_me",
    "change-me",
    "change-this",
    "change_this",
    "placeholder",
    "todo",
    "xxxxxx",
    "请填写",
    "待填写",
)


def _looks_like_placeholder(value: str) -> bool:
    """判断字符串是否是常见的"占位符模板"，不是真实凭证。

    空串、空白、明显的占位符（``your-...``、``CHANGE_ME`` 等）都返回 ``True``。
    """
    if value is None:
        return True
    low = value.strip().lower()
    if not low:
        return True
    return any(hint in low for hint in _PLACEHOLDER_HINTS)


def _load_modstore_env() -> None:
    """加载 MODstore 环境文件：.env -> .env.production.synced -> .env.local。"""
    load_modstore_env(_MODSTORE_ROOT)


_load_modstore_env()


def _smtp_host() -> str:
    return (os.environ.get("MODSTORE_SMTP_HOST") or "smtp.qq.com").strip()


def _smtp_port() -> int:
    try:
        return int(os.environ.get("MODSTORE_SMTP_PORT") or "465")
    except ValueError:
        return 465


def _smtp_user() -> str:
    return (os.environ.get("MODSTORE_SMTP_USER") or "").strip()


def _smtp_password() -> str:
    return (os.environ.get("MODSTORE_SMTP_PASSWORD") or "").strip()


def _sender_email() -> str:
    u = _smtp_user()
    return (os.environ.get("MODSTORE_SENDER_EMAIL") or u).strip()


def _sender_name() -> str:
    return (os.environ.get("MODSTORE_SENDER_NAME") or "XC AGI").strip()


_CODE_EXPIRE_MINUTES = 5
_CODE_LENGTH = 6


def _email_debug_enabled() -> bool:
    return os.environ.get("MODSTORE_EMAIL_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def _generate_code() -> str:
    return "".join([str(random.randint(0, 9)) for _ in range(_CODE_LENGTH)])


def generate_verification_code() -> str:
    """生成 6 位数字验证码（不入库、不发信）。"""
    return _generate_code()


_NOT_CONFIGURED_MESSAGE = (
    "未配置邮件服务：请在 MODstore_deploy/.env 或环境变量中设置真实的 "
    "MODSTORE_SMTP_USER 与 MODSTORE_SMTP_PASSWORD（注意 .env.production 模板里的 "
    "your-qq-smtp-auth-code / CHANGE_ME 等占位符不算已配置）；"
    "也可安装 python-dotenv 后使用 .env / .env.production.synced / .env.local。"
    "本地调试可设 MODSTORE_EMAIL_DEBUG=1 跳过发信并在控制台打印验证码。"
    "管理员可调 GET /api/admin/email/status 看当前生效配置，"
    "或 POST /api/admin/email/test 验证 SMTP。"
)


def _config_state() -> Dict[str, object]:
    """收集当前 SMTP 配置状态，便于错误信息与管理员 API 复用。

    返回脱敏后的字段：``user`` / ``password_set`` / ``placeholder_user`` /
    ``placeholder_password`` / ``debug`` / ``host`` / ``port`` / ``configured``。
    """
    user_raw = _smtp_user()
    pwd_raw = _smtp_password()
    user_ph = _looks_like_placeholder(user_raw)
    pwd_ph = _looks_like_placeholder(pwd_raw)
    debug = _email_debug_enabled()
    return {
        "user": user_raw if not user_ph else "",
        "user_present": bool(user_raw),
        "password_set": bool(pwd_raw) and not pwd_ph,
        "placeholder_user": user_ph and bool(user_raw),
        "placeholder_password": pwd_ph and bool(pwd_raw),
        "debug": debug,
        "host": _smtp_host(),
        "port": _smtp_port(),
        "sender_email": _sender_email(),
        "sender_name": _sender_name(),
        "configured": bool(user_raw) and bool(pwd_raw) and not user_ph and not pwd_ph,
    }


def email_status() -> Dict[str, object]:
    """供 ``email_admin_api`` 复用的脱敏状态视图。"""
    _load_modstore_env()
    state = _config_state()
    state["mode"] = (
        "debug" if state["debug"] else ("smtp" if state["configured"] else "unconfigured")
    )
    return state


def assert_email_outbound_configured() -> None:
    """
    在写入验证码前调用：未配置 SMTP 且未开 DEBUG 时立即失败，避免先 202 再发现不能发信。
    """
    _load_modstore_env()
    if _email_debug_enabled():
        return
    state = _config_state()
    if not state["configured"]:
        raise RuntimeError(_NOT_CONFIGURED_MESSAGE)


def send_verification_email(email: str, code: str, purpose: str = "login") -> None:
    """
    将已有验证码发到邮箱（供 HTTP 先返回后再由后台任务调用）。
    ``purpose``: ``login`` | ``register``，仅影响邮件文案。
    """
    _load_modstore_env()

    if _email_debug_enabled():
        print(f"[MODSTORE_EMAIL_DEBUG] to={email} purpose={purpose} code={code}", flush=True)
        return

    state = _config_state()
    if not state["configured"]:
        raise RuntimeError(_NOT_CONFIGURED_MESSAGE)
    user = _smtp_user()
    password = _smtp_password()

    action = "完成注册" if purpose == "register" else "完成登录"
    sender_name = _sender_name()

    subject = f"{sender_name} - 邮箱验证码"
    body = f"""
<html>
<body style="font-family: sans-serif; padding: 20px;">
  <h2 style="color: #333;">{sender_name} 邮箱验证码</h2>
  <p>您的验证码是：</p>
  <h1 style="color: #60a5fa; letter-spacing: 4px; font-size: 32px;">{code}</h1>
  <p>验证码将在 <b>{_CODE_EXPIRE_MINUTES} 分钟</b>后过期，请尽快{action}。</p>
  <p style="color: #999; font-size: 12px;">如果不是您本人操作，请忽略此邮件。</p>
</body>
</html>
"""

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{_sender_email()}>"
    msg["To"] = email

    with smtplib.SMTP_SSL(_smtp_host(), _smtp_port()) as server:
        server.login(user, password)
        server.sendmail(_sender_email(), email, msg.as_string())


def send_verification_code(email: str, purpose: str = "login") -> str:
    """
    同步：生成验证码并立即发信（测试或无需队列的场景）。
    返回验证码字符串。
    """
    assert_email_outbound_configured()
    code = generate_verification_code()
    send_verification_email(email, code, purpose)
    return code


def send_test_email(email: str) -> Dict[str, object]:
    """供管理员手动触发：给 ``email`` 发一封不含验证码、明确写"测试"的邮件，
    用于验证 SMTP 凭证是否真的能登录与投递。

    返回 ``{"mode": "smtp"|"debug", "delivered": bool, "host": str, "port": int}``。
    DEBUG 模式下不会真的连 SMTP，仅打印日志。
    """
    _load_modstore_env()
    if _email_debug_enabled():
        print(f"[MODSTORE_EMAIL_DEBUG] test email to={email}", flush=True)
        return {"mode": "debug", "delivered": True, "host": _smtp_host(), "port": _smtp_port()}

    state = _config_state()
    if not state["configured"]:
        raise RuntimeError(_NOT_CONFIGURED_MESSAGE)

    user = _smtp_user()
    password = _smtp_password()
    sender_name = _sender_name()
    subject = f"{sender_name} - SMTP 配置测试"
    body = f"""
<html>
<body style="font-family: sans-serif; padding: 20px;">
  <h2>{sender_name} SMTP 配置测试</h2>
  <p>这是一封管理员触发的<strong>测试邮件</strong>，无任何验证码或敏感信息。</p>
  <p>收到此邮件代表 SMTP 凭证有效，可以正常发信。</p>
  <p style="color: #999; font-size: 12px;">如果不是您本人操作，请忽略此邮件。</p>
</body>
</html>
"""
    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{_sender_email()}>"
    msg["To"] = email

    with smtplib.SMTP_SSL(_smtp_host(), _smtp_port()) as server:
        server.login(user, password)
        server.sendmail(_sender_email(), email, msg.as_string())
    return {
        "mode": "smtp",
        "delivered": True,
        "host": _smtp_host(),
        "port": _smtp_port(),
    }


def send_simple_html_email(to_email: str, subject: str, html_body: str) -> Dict[str, object]:
    """发送任意 HTML 邮件（站内通知镜像等）；未配置 SMTP 且非 DEBUG 时静默跳过。"""
    _load_modstore_env()
    if _email_debug_enabled():
        print(f"[MODSTORE_EMAIL_DEBUG] notify to={to_email} subj={subject}", flush=True)
        return {"mode": "debug", "delivered": True}

    state = _config_state()
    if not state["configured"]:
        return {"mode": "unconfigured", "delivered": False}

    user = _smtp_user()
    password = _smtp_password()
    sender_name = _sender_name()
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{_sender_email()}>"
    msg["To"] = to_email

    with smtplib.SMTP_SSL(_smtp_host(), _smtp_port()) as server:
        server.login(user, password)
        server.sendmail(_sender_email(), to_email, msg.as_string())
    return {"mode": "smtp", "delivered": True}


def _attach_file(msg: MIMEMultipart, path: Path) -> bool:
    """把单个文件作为附件挂到 ``msg``；失败返回 ``False`` 不抛异常。"""
    try:
        if not path.is_file():
            return False
        data = path.read_bytes()
        ctype, _ = mimetypes.guess_type(str(path))
        filename = path.name
        if str(path).lower().endswith(".pptx"):
            part = MIMEApplication(
                data,
                _subtype="vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        elif ctype:
            maintype, subtype = ctype.split("/", 1)
            part = MIMEBase(maintype, subtype)
            part.set_payload(data)
            encoders.encode_base64(part)
        else:
            part = MIMEApplication(data)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
        return True
    except Exception:  # noqa: BLE001
        return False


def send_html_email_with_attachments(
    to_email: str,
    subject: str,
    html_body: str,
    attachments: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """发送 HTML 邮件，可附带文件附件（如每日摘要的三端巡检 PPT）。

    - 未配置 SMTP 且非 DEBUG：静默跳过，``delivered=False``、``mode='unconfigured'``；
    - DEBUG：打印日志，``delivered=True``；
    - 无 ``attachments``：等价于 :func:`send_simple_html_email`。

    返回 ``{mode, delivered, attached: [filename], skipped_attachments: [path]}``。
    """
    _load_modstore_env()
    paths = [Path(p) for p in (attachments or []) if str(p or "").strip()]

    if _email_debug_enabled():
        print(
            f"[MODSTORE_EMAIL_DEBUG] notify+attach to={to_email} subj={subject} "
            f"attachments={[p.name for p in paths]}",
            flush=True,
        )
        return {
            "mode": "debug",
            "delivered": True,
            "attached": [p.name for p in paths],
            "skipped_attachments": [],
        }

    state = _config_state()
    if not state["configured"]:
        return {
            "mode": "unconfigured",
            "delivered": False,
            "attached": [],
            "skipped_attachments": [str(p) for p in paths],
        }

    if not paths:
        result = send_simple_html_email(to_email, subject, html_body)
        result.setdefault("attached", [])
        result.setdefault("skipped_attachments", [])
        return result

    user = _smtp_user()
    password = _smtp_password()
    sender_name = _sender_name()

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{_sender_email()}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    attached: List[str] = []
    skipped: List[str] = []
    for p in paths:
        if _attach_file(msg, p):
            attached.append(p.name)
        else:
            skipped.append(str(p))

    with smtplib.SMTP_SSL(_smtp_host(), _smtp_port()) as server:
        server.login(user, password)
        server.sendmail(_sender_email(), to_email, msg.as_string())
    return {"mode": "smtp", "delivered": True, "attached": attached, "skipped_attachments": skipped}


def find_user_by_email(email: str) -> User | None:
    """根据邮箱查找用户（不区分大小写）。"""
    norm = (email or "").strip().lower()
    if not norm:
        return None
    sf = get_session_factory()
    with sf() as session:
        return session.query(User).filter(func.lower(User.email) == norm).first()
