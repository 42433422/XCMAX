#!/usr/bin/env python3
"""XCMAX 生产告警发送器（stdlib-only，兼容 python3.6+）。

告警通道（按序尝试，任一成功即算送达）：
  1. SMTP 直发（默认 QQ SMTP_SSL:465）——凭证优先 /etc/xcmax-ops.env 的 OPS_SMTP_*，
     缺省时回落解析 MODstore .env 的 MODSTORE_SMTP_*（生产已配好，零新增秘密）。
  2. OPS_WEBHOOK_URL（可选，POST JSON，兼容 Server酱/企业微信机器人等任意收 JSON 的端点）。
每条告警无条件追加到 /var/log/xcmax-ops/alerts.log；全通道失败时落
/var/lib/xcmax-ops/UNDELIVERED_ALERTS 并以退出码 3 告知调用方。

设计约束：告警器不得依赖被监控的系统（不 import FHD/MODstore 包、不经其 API 转发）。

CLI:
  notify.py --level crit --title "fhd-full down" --body "systemctl says dead"
  notify.py --level warn --title t --body-file /path/or/-（- 为 stdin）
  notify.py --self-test          # 打印通道配置状态并发送一条测试告警
  notify.py --channel-status     # 只打印通道配置状态，不发送
"""

from __future__ import print_function

import argparse
import json
import os
import smtplib
import socket
import ssl
import sys
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

STATE_DIR = os.environ.get("OPS_STATE_DIR", "/var/lib/xcmax-ops")
LOG_DIR = os.environ.get("OPS_LOG_DIR", "/var/log/xcmax-ops")
DEFAULT_ALERT_TO = "ler231573@gmail.com"
# 生产 MODstore .env 的默认位置（SMTP 凭证回落源）
DEFAULT_MODSTORE_ENV = "/root/XCMAX/成都修茈科技有限公司/MODstore_deploy/.env"

LEVELS = ("crit", "warn", "ok", "info")


def _tls12_context():
    """TLS 客户端上下文，强制最低 TLS1.2（老 python 退回禁用旧协议位）。"""
    ctx = ssl.create_default_context()
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:  # py3.6
        ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
    return ctx


def _read_env_file(path):
    """解析 KEY=VALUE 风格 env 文件（容忍 export 前缀 / 引号 / 注释）。"""
    data = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                data[key.strip()] = value
    except (IOError, OSError):
        pass
    return data


def _env_fallback():
    """合并 env 回落源（MODstore .env / fhd-full.env）为一个 dict。"""
    fallback = {}
    for candidate in (
        os.environ.get("OPS_MODSTORE_ENV") or DEFAULT_MODSTORE_ENV,
        "/root/fhd-full.env",
    ):
        if not fallback.get("MODSTORE_SMTP_PASSWORD") and os.path.exists(candidate):
            parsed = _read_env_file(candidate)
            for key in parsed:
                fallback.setdefault(key, parsed[key])
    return fallback


def _pick(fallback, ops_key, mod_key, default=""):
    return (
        os.environ.get(ops_key)
        or fallback.get(ops_key)
        or fallback.get(mod_key)
        or default
    )


def _smtp_password():
    """SMTP 密码只经此函数按需取用，绝不进入任何会被打印/落盘的结构。"""
    return _pick(_env_fallback(), "OPS_SMTP_PASSWORD", "MODSTORE_SMTP_PASSWORD")


def smtp_config():
    """SMTP 非敏感配置：OPS_SMTP_* 优先，缺项回落 MODSTORE_SMTP_*。不含密码。"""
    fallback = _env_fallback()
    host = _pick(fallback, "OPS_SMTP_HOST", "MODSTORE_SMTP_HOST", "smtp.qq.com")
    port_raw = _pick(fallback, "OPS_SMTP_PORT", "MODSTORE_SMTP_PORT", "465")
    try:
        port = int(port_raw)
    except ValueError:
        port = 465
    user = _pick(fallback, "OPS_SMTP_USER", "MODSTORE_SMTP_USER")
    sender = _pick(fallback, "OPS_SMTP_SENDER", "MODSTORE_SENDER_EMAIL", user)
    to_addr = os.environ.get("OPS_ALERT_EMAIL_TO") or fallback.get(
        "OPS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO
    )
    return {
        "host": host,
        "port": port,
        "user": user,
        "sender": sender or user,
        "to": to_addr,
        "configured": bool(user and _smtp_password()),
    }


def webhook_config():
    url = os.environ.get("OPS_WEBHOOK_URL", "").strip()
    return {"url": url, "configured": bool(url)}


def _append_line(path, line):
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except (IOError, OSError):
        pass


def log_alert(level, title, body):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _append_line(
        os.path.join(LOG_DIR, "alerts.log"),
        "[%s] level=%s title=%s\n%s\n---" % (stamp, level, title, body),
    )


def send_smtp(level, title, body):
    cfg = smtp_config()
    if not cfg["configured"]:
        return False, "smtp 未配置（缺 user/password）"
    hostname = socket.gethostname()
    subject = "[XCMAX-%s] %s" % (level.upper(), title)
    text = "%s\n\n-- host: %s | %s | xcmax-ops" % (
        body,
        hostname,
        time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("XCMAX 运维哨兵", "utf-8")), cfg["sender"]))
    msg["To"] = cfg["to"]
    try:
        server = smtplib.SMTP_SSL(
            cfg["host"], cfg["port"], timeout=20, context=_tls12_context()
        )
        try:
            server.login(cfg["user"], _smtp_password())
            server.sendmail(cfg["sender"], [cfg["to"]], msg.as_string())
        finally:
            server.quit()
        return True, "smtp -> %s" % cfg["to"]
    except Exception as exc:  # smtplib/socket 异常族杂，告警路径上一律吞并报告
        return False, "smtp 失败: %s" % exc


def send_webhook(level, title, body):
    cfg = webhook_config()
    if not cfg["configured"]:
        return False, "webhook 未配置"
    import urllib.request

    payload = json.dumps(
        {
            "level": level,
            "title": title,
            "body": body,
            "host": socket.gethostname(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            # Server酱/企微机器人常用字段的兼容别名
            "text": "[XCMAX-%s] %s" % (level.upper(), title),
            "desp": body,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        cfg["url"], data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        code = resp.getcode()
        if 200 <= code < 300:
            return True, "webhook %s" % code
        return False, "webhook http %s" % code
    except Exception as exc:
        return False, "webhook 失败: %s" % exc


def deliver(level, title, body):
    """发送告警。返回 (delivered, details)。永远先落本地日志。"""
    log_alert(level, title, body)
    details = []
    delivered = False
    ok, msg = send_smtp(level, title, body)
    details.append(msg)
    delivered = delivered or ok
    ok, msg = send_webhook(level, title, body)
    details.append(msg)
    delivered = delivered or ok
    if not delivered:
        _append_line(
            os.path.join(STATE_DIR, "UNDELIVERED_ALERTS"),
            "[%s] %s: %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), level, title),
        )
    return delivered, "; ".join(details)


def channel_status():
    smtp = smtp_config()
    hook = webhook_config()
    lines = [
        "smtp: %s (host=%s port=%s user=%s to=%s)"
        % (
            "已配置" if smtp["configured"] else "未配置",
            smtp["host"],
            smtp["port"],
            smtp["user"] or "-",
            smtp["to"],
        ),
        "webhook: %s" % ("已配置" if hook["configured"] else "未配置（可选）"),
        "alerts.log: %s" % os.path.join(LOG_DIR, "alerts.log"),
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="XCMAX ops alert sender")
    parser.add_argument("--level", choices=LEVELS, default="info")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--body-file", default="")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--channel-status", action="store_true")
    args = parser.parse_args(argv)

    if args.channel_status:
        print(channel_status())
        return 0

    if args.self_test:
        print(channel_status())
        delivered, details = deliver(
            "info",
            "xcmax-ops 自检",
            "这是一条测试告警。收到它说明告警链路可用。\n通道状态:\n" + channel_status(),
        )
        print("发送结果: %s (%s)" % ("送达" if delivered else "未送达", details))
        return 0 if delivered else 3

    if not args.title:
        parser.error("--title 必填（除 --self-test/--channel-status 外）")
    body = args.body
    if args.body_file:
        if args.body_file == "-":
            body = sys.stdin.read()
        else:
            with open(args.body_file, "r", encoding="utf-8", errors="replace") as fh:
                body = fh.read()
    delivered, details = deliver(args.level, args.title, body or "(无正文)")
    print(details)
    return 0 if delivered else 3


if __name__ == "__main__":
    sys.exit(main())
