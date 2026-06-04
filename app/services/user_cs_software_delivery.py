"""按需求表单偏好生成并推送桌面 + 手机（Android）安装包下载链接。"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

DesktopOs = Literal["mac", "win"]
MacArch = Literal["x64", "arm64"]
ProductSku = Literal["personal", "enterprise"]
DownloadPlatform = Literal["win", "mac", "android"]

_DEFAULT_VERSION = (os.environ.get("XCAGI_DOWNLOAD_VERSION", "9.0.0") or "9.0.0").strip()
_DEFAULT_ANDROID_VERSION = (
    os.environ.get("XCAGI_ANDROID_DOWNLOAD_VERSION", "1.5.0") or "1.5.0"
).strip()
_DEFAULT_BASE = (
    os.environ.get("XCAGI_DOWNLOAD_BASE", f"https://dl.xiu-ci.com/xcagi-v{_DEFAULT_VERSION}")
    or f"https://dl.xiu-ci.com/xcagi-v{_DEFAULT_VERSION}"
).rstrip("/")

_OS_FROM_MESSAGE_RE = re.compile(
    r"使用系统[：:]\s*(mac\s*os|macos|mac|windows|win)\b",
    re.I,
)
_NEED_MOBILE_RE = re.compile(
    r"手机端[：:]\s*(需要|不需要|是|否|yes|no)",
    re.I,
)
_MAC_ARCH_FROM_MESSAGE_RE = re.compile(
    r"(?:芯片|处理器|架构|mac\s*arch)[：:]\s*"
    r"(apple\s*silicon|m[1-9]\s*(?:pro|max|ultra)?|arm64|aarch64|intel|x64|x86_64)",
    re.I,
)
_MAC_SILICON_HINT_RE = re.compile(
    r"\b(apple\s*silicon|m[1-9]\s*(?:\s*pro|\s*max|\s*ultra)?|arm64|aarch64)\b",
    re.I,
)
_MAC_INTEL_HINT_RE = re.compile(
    r"\b(intel\s*mac|x86_64|mac\s*intel|intel\s*x64)\b",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_desktop_os(value: str | None) -> DesktopOs | None:
    raw = (value or "").strip().casefold()
    if raw in ("mac", "macos", "darwin", "osx"):
        return "mac"
    if raw in ("win", "windows", "win32", "pc"):
        return "win"
    return None


def normalize_need_mobile(value: str | bool | None, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    raw = (value or "").strip().casefold()
    if raw in ("1", "true", "yes", "y", "需要", "是", "on"):
        return True
    if raw in ("0", "false", "no", "n", "不需要", "否", "off"):
        return False
    return default


def parse_desktop_os_from_message(message: str) -> DesktopOs | None:
    m = _OS_FROM_MESSAGE_RE.search(message or "")
    if not m:
        return None
    return normalize_desktop_os(m.group(1))


def normalize_mac_arch(value: str | None) -> MacArch | None:
    raw = (value or "").strip().casefold().replace(" ", "")
    if raw in ("arm64", "aarch64", "applesilicon", "arm", "m1", "m2", "m3", "m4"):
        return "arm64"
    if raw in ("x64", "x86_64", "intel", "intelmac"):
        return "x64"
    if raw.startswith("m") and len(raw) <= 4 and raw[1:].isdigit():
        return "arm64"
    return None


def parse_mac_arch_from_message(message: str) -> MacArch | None:
    text = message or ""
    m = _MAC_ARCH_FROM_MESSAGE_RE.search(text)
    if m:
        return normalize_mac_arch(m.group(1))
    if _MAC_INTEL_HINT_RE.search(text):
        return "x64"
    if _MAC_SILICON_HINT_RE.search(text):
        return "arm64"
    return None


def resolve_mac_arch_from_pipeline(doc: dict[str, Any]) -> MacArch:
    form = doc.get("intake_form")
    if isinstance(form, dict):
        direct = normalize_mac_arch(str(form.get("mac_arch") or form.get("desktop_mac_arch") or ""))
        if direct:
            return direct
        parsed = parse_mac_arch_from_message(str(form.get("message") or ""))
        if parsed:
            return parsed
    direct_doc = normalize_mac_arch(str(doc.get("mac_arch") or doc.get("desktop_mac_arch") or ""))
    if direct_doc:
        return direct_doc
    return "arm64"


def parse_need_mobile_from_message(message: str) -> bool | None:
    m = _NEED_MOBILE_RE.search(message or "")
    if not m:
        return None
    return normalize_need_mobile(m.group(1), default=True)


def resolve_desktop_os_from_pipeline(doc: dict[str, Any]) -> DesktopOs | None:
    form = doc.get("intake_form")
    if isinstance(form, dict):
        direct = normalize_desktop_os(str(form.get("desktop_os") or ""))
        if direct:
            return direct
        parsed = parse_desktop_os_from_message(str(form.get("message") or ""))
        if parsed:
            return parsed
    return normalize_desktop_os(str(doc.get("desktop_os") or ""))


def resolve_need_mobile_from_pipeline(doc: dict[str, Any]) -> bool:
    form = doc.get("intake_form")
    if isinstance(form, dict):
        if "need_mobile" in form:
            return normalize_need_mobile(form.get("need_mobile"), default=True)
        parsed = parse_need_mobile_from_message(str(form.get("message") or ""))
        if parsed is not None:
            return parsed
    if "need_mobile" in doc:
        return normalize_need_mobile(doc.get("need_mobile"), default=True)
    return True


def resolve_product_sku(doc: dict[str, Any]) -> ProductSku:
    if str(doc.get("enterprise_auto_provisioned_at") or "").strip():
        return "enterprise"
    form = doc.get("intake_form")
    if isinstance(form, dict) and str(form.get("company") or "").strip():
        return "enterprise"
    explicit = str(doc.get("product_sku") or doc.get("download_sku") or "").strip().casefold()
    if explicit in ("personal", "enterprise"):
        return explicit  # type: ignore[return-value]
    return "enterprise"


def xcagi_download_file_name(
    sku: ProductSku,
    platform: DownloadPlatform,
    *,
    version: str | None = None,
    android_version: str | None = None,
    mac_arch: MacArch = "arm64",
) -> str:
    label = "Personal" if sku == "personal" else "Enterprise"
    ver = version or _DEFAULT_VERSION
    aver = android_version or _DEFAULT_ANDROID_VERSION
    if platform == "android":
        return f"XCAGI-{label}-Android-{aver}.apk"
    if platform == "mac":
        return f"XCAGI-{label}-{ver}-mac-{mac_arch}.dmg"
    return f"XCAGI-{label}-Setup-{ver}-x64.exe"


def build_software_download_url(
    *,
    sku: ProductSku,
    desktop_os: DesktopOs,
    base: str | None = None,
    mac_arch: MacArch | None = None,
) -> str:
    platform: DownloadPlatform = "mac" if desktop_os == "mac" else "win"
    root = (base or _DEFAULT_BASE).rstrip("/")
    if platform == "mac":
        fname = xcagi_download_file_name(sku, platform, mac_arch=mac_arch or "arm64")
    else:
        fname = xcagi_download_file_name(sku, platform)
    return f"{root}/{sku}/{fname}"


def build_android_download_url(
    *,
    sku: ProductSku,
    base: str | None = None,
    android_version: str | None = None,
) -> str:
    root = (base or _DEFAULT_BASE).rstrip("/")
    fname = xcagi_download_file_name(
        sku,
        "android",
        android_version=android_version or _DEFAULT_ANDROID_VERSION,
    )
    return f"{root}/{sku}/{fname}"


def build_delivery_download_bundle(
    doc: dict[str, Any],
    *,
    base: str | None = None,
) -> dict[str, Any]:
    desktop_os = resolve_desktop_os_from_pipeline(doc)
    if not desktop_os:
        raise ValueError("客户尚未选择桌面系统（Mac / Windows），请先在需求表单中确认或手动补录")
    sku = resolve_product_sku(doc)
    need_mobile = resolve_need_mobile_from_pipeline(doc)
    mac_arch: MacArch | None = resolve_mac_arch_from_pipeline(doc) if desktop_os == "mac" else None
    desktop_url = build_software_download_url(
        sku=sku,
        desktop_os=desktop_os,
        base=base,
        mac_arch=mac_arch,
    )
    android_url = build_android_download_url(sku=sku, base=base) if need_mobile else ""
    result: dict[str, Any] = {
        "desktop_os": desktop_os,
        "product_sku": sku,
        "need_mobile": need_mobile,
        "desktop_url": desktop_url,
        "android_url": android_url,
    }
    if mac_arch:
        result["mac_arch"] = mac_arch
    return result


def desktop_os_label(desktop_os: DesktopOs, mac_arch: MacArch | None = None) -> str:
    if desktop_os == "mac":
        if mac_arch == "arm64":
            return "macOS（Apple Silicon）"
        if mac_arch == "x64":
            return "macOS（Intel）"
        return "macOS"
    return "Windows"


def mac_arch_label(mac_arch: MacArch) -> str:
    return "Apple Silicon" if mac_arch == "arm64" else "Intel"


def build_software_delivery_message(
    doc: dict[str, Any],
    *,
    download_url: str | None = None,
    android_url: str | None = None,
) -> str:
    bundle = build_delivery_download_bundle(doc)
    desktop_os = bundle["desktop_os"]
    sku = bundle["product_sku"]
    need_mobile = bundle["need_mobile"]
    mac_arch = bundle.get("mac_arch")
    url = download_url or bundle["desktop_url"]
    apk = android_url if android_url is not None else bundle["android_url"]
    client = str(doc.get("username") or "").strip()
    who = f"{client}，您好" if client and not client.endswith("好") else (client or "您好")
    sku_label = "企业版" if sku == "enterprise" else "个人版"
    mac_arch_typed = mac_arch if mac_arch in ("x64", "arm64") else None
    lines = [
        f"{who}！",
        "",
        "您定制的 XCAGI 软件已可下载安装，请按设备选择对应安装包：",
        "",
        f"【电脑端 · {desktop_os_label(desktop_os, mac_arch_typed)}】",
        f"版本：{sku_label}",
        f"下载链接：{url}",
    ]
    if desktop_os == "mac" and mac_arch_typed:
        alt: MacArch = "x64" if mac_arch_typed == "arm64" else "arm64"
        alt_url = build_software_download_url(sku=sku, desktop_os="mac", mac_arch=alt)
        lines.extend(
            [
                f"（若为 {mac_arch_label(alt)} Mac，请改用：{alt_url}）",
            ]
        )
    if need_mobile and apk:
        lines.extend(
            [
                "",
                "【手机端 · Android】",
                f"版本：{sku_label}",
                f"下载链接：{apk}",
            ]
        )
    lines.extend(
        [
            "",
            "安装说明：",
            "· Windows：下载 .exe 后双击安装；若系统提示未知来源，请在「更多信息」中仍要运行。",
            "· macOS：下载对应芯片架构的 .dmg（Apple Silicon 或 Intel）后拖入「应用程序」；首次打开若被拦截，请在「隐私与安全性」中允许。",
        ]
    )
    if need_mobile and apk:
        lines.append(
            "· Android：下载 .apk 后在手机设置中允许「安装未知应用」后安装；企业环境可先由 IT 统一下发。"
        )
    lines.extend(
        [
            "",
            "如下载异常或需要协助部署，请直接在本群留言，我们会尽快跟进。",
            "",
            "祝使用顺利！",
        ]
    )
    return "\n".join(lines)


def notify_software_delivery(
    market_user_id: int,
    *,
    username: str = "",
    force: bool = False,
) -> dict[str, Any]:
    from app.desktop_automation.service import get_desktop_automation_service
    from app.services.user_cs_intake_notice import _primary_contact_name
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    try:
        bundle = build_delivery_download_bundle(doc)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    desktop_os = bundle["desktop_os"]
    if doc.get("software_delivery_sent_at") and not force:
        return {
            "ok": False,
            "error": "安装包链接已发送过，如需重发请使用「重新发送安装包」",
            "sent_at": doc.get("software_delivery_sent_at"),
        }
    contact = _primary_contact_name(uid) or ""
    if not contact:
        return {"ok": False, "error": "未绑定微信群联系人"}
    url = bundle["desktop_url"]
    apk = bundle["android_url"]
    text = build_software_delivery_message(doc, download_url=url, android_url=apk)
    try:
        send_result = get_desktop_automation_service().send_wechat_message(contact, text)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    ok = bool(send_result.get("success")) and bool(
        send_result.get("message_sent", send_result.get("success"))
    )
    if ok:
        now = _now_iso()
        doc = dict(doc)
        doc["software_delivery_sent_at"] = now
        doc["software_delivery_os"] = desktop_os
        if bundle.get("mac_arch"):
            doc["software_delivery_mac_arch"] = bundle["mac_arch"]
        doc["software_delivery_url"] = url
        if apk:
            doc["software_delivery_android_url"] = apk
        doc["software_delivery_need_mobile"] = bundle["need_mobile"]
        doc = save_pipeline(doc)
    return {
        "ok": ok,
        "message": text,
        "download_url": url,
        "android_download_url": apk,
        "desktop_os": desktop_os,
        "need_mobile": bundle["need_mobile"],
        "product_sku": bundle["product_sku"],
        "send_result": send_result,
        "pipeline": doc if ok else None,
        "error": "" if ok else str(send_result.get("error") or "发送失败"),
    }
