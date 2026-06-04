"""微信库安全快照：先复制加密库到工作区，再在副本上解密/只读查询，不直接打开微信目录里的库。"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SNAPSHOT_ROOT_NAME = "snapshot_work"


def _toolkit_dir() -> str:
    from app.services.wechat_decrypt_autoconfig import (
        apply_runtime_env,
        load_runtime_config,
        resolve_wechat_decrypt_toolkit_dir,
    )

    runtime = load_runtime_config()
    apply_runtime_env(runtime)
    tk = str(runtime.get("toolkit_dir") or "").strip() or (
        resolve_wechat_decrypt_toolkit_dir() or ""
    )
    if not tk:
        raise FileNotFoundError("未配置 wechat-decrypt 工具目录")
    return tk


def snapshot_paths(toolkit_dir: str | None = None) -> dict[str, str]:
    tk = toolkit_dir or _toolkit_dir()
    root = os.path.join(tk, _SNAPSHOT_ROOT_NAME)
    enc_msg = os.path.join(root, "encrypted", "message")
    enc_contact = os.path.join(root, "encrypted", "contact")
    plain_msg = os.path.join(root, "plain", "message", "message_0.db")
    plain_contact = os.path.join(root, "plain", "contact", "contact.db")
    return {
        "root": root,
        "encrypted_message_dir": enc_msg,
        "encrypted_contact_dir": enc_contact,
        "plain_message_db": plain_msg,
        "plain_contact_db": plain_contact,
    }


def live_message_bundle_fingerprint(db_dir: str) -> str:
    """本机微信 message 目录（含 WAL/SHM）指纹，用于判断是否需要重新打快照。"""
    section = os.path.join(db_dir, "message")
    parts: list[str] = []
    for name in ("message_0.db", "message_0.db-wal", "message_0.db-shm"):
        path = os.path.join(section, name)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
            parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            continue
    if not parts:
        return ""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _snapshot_meta_file(toolkit_dir: str) -> str:
    return os.path.join(snapshot_paths(toolkit_dir)["root"], "snapshot_meta.json")


def _live_message_bundle_mtime(db_dir: str) -> float:
    """本机 message_0 主库 + WAL 的最新修改时间。"""
    section = os.path.join(db_dir, "message")
    latest = 0.0
    for name in ("message_0.db", "message_0.db-wal", "message_0.db-shm"):
        path = os.path.join(section, name)
        if not os.path.isfile(path):
            continue
        try:
            latest = max(latest, os.path.getmtime(path))
        except OSError:
            continue
    return latest


def message_snapshot_is_current(db_dir: str, toolkit_dir: str | None = None) -> bool:
    """明文快照是否仍对应当前本机微信 message 库（未变则无需复制+解密）。"""
    if not db_dir or not os.path.isdir(db_dir):
        return False
    tk = toolkit_dir or _toolkit_dir()
    paths = snapshot_paths(tk)
    plain = paths["plain_message_db"]
    if not os.path.isfile(plain) or os.path.getsize(plain) < 1024:
        return False
    live_fp = live_message_bundle_fingerprint(db_dir)
    if not live_fp:
        return False
    meta_path = _snapshot_meta_file(tk)
    if not os.path.isfile(meta_path):
        return False
    try:
        import json

        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
        if str(meta.get("live_fingerprint") or "") != live_fp:
            return False
    except (OSError, ValueError, TypeError):
        return False
    live_mt = _live_message_bundle_mtime(db_dir)
    try:
        plain_mt = os.path.getmtime(plain)
    except OSError:
        return False
    # 指纹一致但明文仍落后于本机 bundle（含 WAL）时，仍需复制解密
    if live_mt > plain_mt + 1:
        return False
    return True


def _write_snapshot_meta(toolkit_dir: str, *, live_fingerprint: str) -> None:
    import json
    from datetime import datetime, timezone

    meta_path = _snapshot_meta_file(toolkit_dir)
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    payload = {
        "live_fingerprint": live_fingerprint,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    Path(meta_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _copy_section_bundle(live_section_dir: str, dst_section_dir: str) -> int:
    """复制 .db / -wal / -shm 到快照目录（不触碰源文件句柄外的写操作）。"""
    os.makedirs(dst_section_dir, exist_ok=True)
    copied = 0
    if not os.path.isdir(live_section_dir):
        return 0
    names: set[str] = set()
    for f in glob.glob(os.path.join(live_section_dir, "*.db")):
        if f.endswith("-wal") or f.endswith("-shm"):
            continue
        names.add(os.path.basename(f))
    for base in list(names):
        names.add(f"{base}-wal")
        names.add(f"{base}-shm")
    for name in names:
        src = os.path.join(live_section_dir, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(dst_section_dir, name)
        try:
            shutil.copy2(src, dst)
            copied += 1
        except OSError as exc:
            logger.warning("[WeChat snapshot] 复制失败 %s -> %s: %s", src, dst, exc)
    return copied


def ensure_snapshot_message_db_ready(*, force: bool = False) -> dict[str, Any]:
    """macOS：确保 WECHAT_MSG_DB_PATH 指向最新快照明文库（供同步/轮询入口调用）。"""
    import platform

    from app.services.wechat_decrypt_autoconfig import load_runtime_config

    if platform.system().lower() != "darwin" or os.environ.get("WECHAT_USE_SNAPSHOT", "1") == "0":
        return {"success": False, "message": "非 macOS 或未启用快照", "rebuilt": False}
    db_dir = str(load_runtime_config().get("db_dir") or "").strip()
    if not db_dir:
        return {"success": False, "message": "未配置微信 db_dir", "rebuilt": False}
    need = bool(force) or not message_snapshot_is_current(db_dir)
    out = build_message_snapshot(force_refresh=need)
    out["rebuilt"] = bool(out.get("success")) and not bool(out.get("skipped"))
    return out


def ensure_wechat_snapshot_for_poll(*, force: bool = False) -> dict[str, Any]:
    """
    轮询/被动探测专用：检测本机微信 message 库变动，有变动则复制+解密，否则复用快照。
    返回 rebuilt=True 表示本轮执行了复制解密。
    """
    snap = ensure_snapshot_message_db_ready(force=force)
    if snap.get("success"):
        return snap
    if not force:
        retry = ensure_snapshot_message_db_ready(force=True)
        if retry.get("success"):
            retry["forced_retry"] = True
            retry["rebuilt"] = True
            return retry
    snap.setdefault("rebuilt", False)
    return snap


def build_message_snapshot(*, force_refresh: bool = True) -> dict[str, Any]:
    """
    1. 从微信 db_storage 复制 message/contact 到 snapshot_work/encrypted/
    2. 在副本上解密到 snapshot_work/plain/
    3. 设置 WECHAT_MSG_DB_PATH 指向明文副本（只读由调用方保证）
    """
    import json

    from app.services.wechat_contact_cache_import import _export_encrypted_db_to_plain_sqlcipher
    from app.services.wechat_decrypt_autoconfig import load_runtime_config

    try:
        tk = _toolkit_dir()
    except FileNotFoundError as exc:
        return {"success": False, "message": str(exc)}

    paths = snapshot_paths(tk)
    cfg_path = os.path.join(tk, "config.json")
    if not os.path.isfile(cfg_path):
        return {"success": False, "message": "config.json 不存在"}
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    runtime = load_runtime_config()
    db_dir = str(cfg.get("db_dir") or "")
    keys_file = str(
        runtime.get("keys_file") or cfg.get("keys_file") or os.path.join(tk, "all_keys.json")
    )

    if not db_dir or not os.path.isdir(db_dir):
        return {"success": False, "message": f"微信数据目录无效: {db_dir}"}

    if not os.path.isfile(keys_file):
        return {"success": False, "message": "all_keys.json 不存在，请先提钥"}

    plain_msg = paths["plain_message_db"]
    if not force_refresh and message_snapshot_is_current(db_dir, tk):
        os.environ["WECHAT_MSG_DB_PATH"] = plain_msg
        contact_plain = paths["plain_contact_db"]
        if os.path.isfile(contact_plain):
            os.environ["WECHAT_CONTACT_DB_PATH"] = contact_plain
        logger.debug("[WeChat snapshot] 复用未过期快照，跳过复制解密")
        return {
            "success": True,
            "skipped": True,
            "message": "本机微信库未变，复用快照",
            "message_db_path": plain_msg,
            "contact_db_path": contact_plain if os.path.isfile(contact_plain) else "",
            "snapshot_root": paths["root"],
        }

    import sys as _sys

    if tk not in _sys.path:
        _sys.path.insert(0, tk)
    from key_utils import get_key_info, strip_key_metadata

    with open(keys_file, encoding="utf-8") as f:
        keys = json.load(f)
    keys = strip_key_metadata(keys)

    msg_copied = _copy_section_bundle(
        os.path.join(db_dir, "message"),
        paths["encrypted_message_dir"],
    )
    contact_copied = _copy_section_bundle(
        os.path.join(db_dir, "contact"),
        paths["encrypted_contact_dir"],
    )

    enc_msg_0 = os.path.join(paths["encrypted_message_dir"], "message_0.db")
    enc_contact = os.path.join(paths["encrypted_contact_dir"], "contact.db")
    plain_msg = paths["plain_message_db"]
    plain_contact = paths["plain_contact_db"]
    os.makedirs(os.path.dirname(plain_msg), exist_ok=True)
    os.makedirs(os.path.dirname(plain_contact), exist_ok=True)

    ok_msg = False
    ok_contact = False
    key_msg = get_key_info(keys, "message/message_0.db")
    if key_msg and os.path.isfile(enc_msg_0):
        if force_refresh and os.path.isfile(plain_msg):
            try:
                os.remove(plain_msg)
            except OSError:
                pass
        ok_msg = _export_encrypted_db_to_plain_sqlcipher(
            enc_msg_0, plain_msg, str(key_msg.get("enc_key") or "")
        )
        if not ok_msg:
            try:
                from decrypt_db import decrypt_database

                ok_msg = bool(
                    decrypt_database(
                        enc_msg_0,
                        plain_msg,
                        bytes.fromhex(str(key_msg.get("enc_key") or "")),
                    )
                )
            except Exception as exc:
                logger.warning("snapshot decrypt message_0: %s", exc)

    key_contact = get_key_info(keys, "contact/contact.db")
    if key_contact and os.path.isfile(enc_contact):
        if force_refresh and os.path.isfile(plain_contact):
            try:
                os.remove(plain_contact)
            except OSError:
                pass
        ok_contact = _export_encrypted_db_to_plain_sqlcipher(
            enc_contact, plain_contact, str(key_contact.get("enc_key") or "")
        )

    if not ok_msg or not os.path.isfile(plain_msg):
        return {
            "success": False,
            "message": "消息库快照解密失败",
            "copied_files": msg_copied + contact_copied,
        }

    _write_snapshot_meta(tk, live_fingerprint=live_message_bundle_fingerprint(db_dir))

    os.environ["WECHAT_MSG_DB_PATH"] = plain_msg
    if ok_contact and os.path.isfile(plain_contact):
        os.environ["WECHAT_CONTACT_DB_PATH"] = plain_contact

    return {
        "success": True,
        "message": "已从副本解密消息库（未直接读取微信源库）",
        "message_db_path": plain_msg,
        "contact_db_path": plain_contact if ok_contact else "",
        "copied_files": msg_copied + contact_copied,
        "snapshot_root": paths["root"],
    }


def snapshot_fingerprint(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return ""
