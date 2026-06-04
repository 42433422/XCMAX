"""自动配置 wechat-decrypt：检测工具目录、微信 db_storage、密钥与运行时环境变量。"""

from __future__ import annotations

import glob
import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir, get_resource_path, resolve_fhd_repo_root

logger = logging.getLogger(__name__)

_RUNTIME_FILE = "wechat_decrypt_runtime.json"
_PYCRYPTODOME_SPEC = "pycryptodome>=3.19,<4"


def _pycryptodome_import_ok() -> bool:
    try:
        from Crypto.Cipher import AES  # noqa: F401

        return True
    except ImportError:
        return False


def ensure_pycryptodome(*, auto_install: bool = True) -> tuple[bool, str]:
    """
    确保 ``from Crypto.Cipher`` 可用（wechat-decrypt 依赖 pycryptodome）。
    缺失且 ``auto_install`` 时用当前解释器执行 pip install。
    """
    if _pycryptodome_import_ok():
        return True, "已安装"
    if not auto_install:
        return False, f"未安装；请执行: {sys.executable} -m pip install {_PYCRYPTODOME_SPEC}"

    logger.info("pycryptodome 未安装，正在自动安装: %s", _PYCRYPTODOME_SPEC)
    try:
        pip_probe = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if pip_probe.returncode != 0:
            subprocess.run(
                [sys.executable, "-m", "ensurepip", "--upgrade"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", _PYCRYPTODOME_SPEC],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:400]
            return False, f"pip 安装失败 (code {proc.returncode}): {err or '未知错误'}"
    except Exception as exc:
        logger.warning("自动安装 pycryptodome 异常: %s", exc)
        return False, f"自动安装失败: {exc}"

    if _pycryptodome_import_ok():
        return True, "已自动安装 pycryptodome"
    return False, "安装后仍无法 import Crypto，请重启后端后重试"


def _runtime_path() -> Path:
    return Path(get_app_data_dir()) / _RUNTIME_FILE


def _db_dir_from_toolkit_config(data: dict[str, Any]) -> str:
    """runtime 未写入 db_dir 时，从 wechat-decrypt/config.json 补全（与 decrypt_status 一致）。"""
    toolkit = str(data.get("toolkit_dir") or "").strip()
    if not toolkit:
        return ""
    cfg_path = str(data.get("config_path") or "").strip() or os.path.join(toolkit, "config.json")
    if not os.path.isfile(cfg_path):
        return ""
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return str(json.load(f).get("db_dir") or "").strip()
    except Exception:
        return ""


def load_runtime_config() -> dict[str, Any]:
    path = _runtime_path()
    if not path.is_file():
        data: dict[str, Any] = {}
    else:
        try:
            with path.open(encoding="utf-8") as f:
                raw = json.load(f)
            data = raw if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.warning("读取 wechat_decrypt_runtime.json 失败: %s", exc)
            data = {}
    if not str(data.get("db_dir") or "").strip():
        db_dir = _db_dir_from_toolkit_config(data)
        if db_dir:
            data = {**data, "db_dir": db_dir}
    return data


def save_runtime_config(data: dict[str, Any]) -> None:
    path = _runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _format_mtime(path: str) -> str:
    try:
        if path and os.path.isfile(path):
            return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m-%d %H:%M")
    except OSError:
        pass
    return "未知"


def _wechat_db_freshness(toolkit_dir: str, db_dir: str) -> dict[str, Any]:
    """对比本机微信源库与本地 decrypted 库的新旧（含 message WAL）。"""
    live_msg = os.path.join(db_dir, "message", "message_0.db") if db_dir else ""
    live_contact = os.path.join(db_dir, "contact", "contact.db") if db_dir else ""
    dec_msg = os.path.join(toolkit_dir, "decrypted", "message", "message_0.db")
    dec_contact = os.path.join(toolkit_dir, "decrypted", "contact", "contact.db")

    def bundle_mtime(main: str) -> float:
        mt = 0.0
        for p in (main, f"{main}-wal", f"{main}-shm"):
            try:
                if p and os.path.isfile(p):
                    mt = max(mt, os.path.getmtime(p))
            except OSError:
                continue
        return mt

    live_msg_mt = bundle_mtime(live_msg)
    live_contact_mt = bundle_mtime(live_contact)
    dec_msg_mt = os.path.getmtime(dec_msg) if os.path.isfile(dec_msg) else 0.0
    dec_contact_mt = os.path.getmtime(dec_contact) if os.path.isfile(dec_contact) else 0.0

    return {
        "live_message_db": live_msg,
        "live_contact_db": live_contact,
        "decrypted_message_db": dec_msg,
        "decrypted_contact_db": dec_contact,
        "message_stale": bool(live_msg_mt > 0 and dec_msg_mt > 0 and live_msg_mt > dec_msg_mt + 30),
        "contact_stale": bool(
            live_contact_mt > 0 and dec_contact_mt > 0 and live_contact_mt > dec_contact_mt + 30
        ),
        "message_missing": bool(live_msg_mt > 0 and dec_msg_mt <= 0),
        "live_message_mtime": live_msg_mt,
        "decrypted_message_mtime": dec_msg_mt,
    }


def prepare_wechat_message_db_for_read(
    *, force_decrypt: bool = False, retry_key_scan: bool = False
) -> dict[str, Any]:
    """
    从本机微信 db_storage 同步 message_0.db（含 WAL）并解密，返回可读明文库路径。
    供群聊消息同步 / refresh_messages 使用，避免读到 resources 里过期的副本。
    """
    runtime = load_runtime_config()
    apply_runtime_env(runtime)
    toolkit = str(runtime.get("toolkit_dir") or "").strip()
    db_dir = str(runtime.get("db_dir") or "").strip()
    msg_path = str(runtime.get("message_db_path") or "").strip()
    if not toolkit:
        toolkit = resolve_wechat_decrypt_toolkit_dir() or ""
    if toolkit and not msg_path:
        msg_path = os.path.join(toolkit, "decrypted", "message", "message_0.db")

    live_main = ""
    if db_dir:
        live_main = os.path.join(db_dir, "message", "message_0.db")

    decrypt_detail: dict[str, Any] = {"success": False, "message": "未执行解密"}
    snapshot_detail: dict[str, Any] = {"success": False, "message": "未使用快照"}
    force_msg = bool(force_decrypt or retry_key_scan)

    # macOS：先复制到 snapshot_work 再在副本上解密/读取，不直接打开微信目录里的库
    use_snapshot = (
        platform.system().lower() == "darwin"
        and toolkit
        and db_dir
        and os.environ.get("WECHAT_USE_SNAPSHOT", "1") != "0"
    )
    if use_snapshot:
        try:
            from app.services.wechat_db_snapshot import build_message_snapshot

            snapshot_detail = build_message_snapshot(force_refresh=force_msg)
            if snapshot_detail.get("success"):
                msg_path = str(snapshot_detail.get("message_db_path") or msg_path)
                decrypt_detail = {
                    "success": True,
                    "message": snapshot_detail.get("message") or "快照副本已就绪",
                    "via": "snapshot_work",
                }
        except Exception as exc:
            snapshot_detail = {"success": False, "message": str(exc)}
            logger.warning("build_message_snapshot: %s", exc)

    if toolkit and db_dir and not snapshot_detail.get("success"):
        try:
            from app.services.wechat_contact_cache_import import ensure_decrypted_wechat_dbs

            decrypt_detail = ensure_decrypted_wechat_dbs(force_message=force_msg)
        except Exception as exc:
            decrypt_detail = {"success": False, "message": str(exc)}

    runtime = load_runtime_config()
    snap_plain = ""
    if use_snapshot and snapshot_detail.get("success"):
        snap_plain = str(snapshot_detail.get("message_db_path") or msg_path).strip()
    apply_runtime_env(runtime)
    if snap_plain and os.path.isfile(snap_plain):
        msg_path = snap_plain
        os.environ["WECHAT_MSG_DB_PATH"] = snap_plain
    else:
        msg_path = str(runtime.get("message_db_path") or msg_path).strip()
    if toolkit and not msg_path:
        msg_path = os.path.join(toolkit, "decrypted", "message", "message_0.db")

    stale = False
    stale_reason = ""
    if live_main and os.path.isfile(live_main) and msg_path and os.path.isfile(msg_path):
        try:
            live_mt = os.path.getmtime(live_main)
            wal = live_main + "-wal"
            if os.path.isfile(wal):
                live_mt = max(live_mt, os.path.getmtime(wal))
            dec_mt = os.path.getmtime(msg_path)
            if live_mt > dec_mt + 30:
                stale = True
                stale_reason = (
                    f"本机微信消息库已更新（{datetime.fromtimestamp(live_mt).strftime('%m-%d %H:%M')}），"
                    f"但解密库较旧（{datetime.fromtimestamp(dec_mt).strftime('%m-%d %H:%M')}）"
                )
        except OSError:
            pass

    if force_decrypt and toolkit and db_dir and not decrypt_detail.get("success"):
        stale = True

    if retry_key_scan and toolkit and db_dir and stale:
        keys_path = os.path.join(toolkit, "all_keys.json")
        if _keys_file_usable(keys_path):
            try:
                from app.services.wechat_db_snapshot import build_message_snapshot

                snap_retry = build_message_snapshot(force_refresh=True)
                if snap_retry.get("success"):
                    msg_path = str(snap_retry.get("message_db_path") or msg_path).strip()
                    snapshot_detail = snap_retry
                    decrypt_detail = {
                        "success": True,
                        "message": snap_retry.get("message") or "已刷新快照",
                        "via": "snapshot_work",
                    }
                    stale = False
                    stale_reason = ""
            except Exception as exc:
                logger.warning("stale 时刷新快照失败: %s", exc)
        if stale and not _keys_file_usable(keys_path):
            key_scan = _try_extract_keys(toolkit, force=True)
        elif stale:
            key_scan = {
                "success": False,
                "message": "密钥文件不可用且快照刷新未消除滞后",
            }
        else:
            key_scan = {"success": True, "skipped": True}
        if key_scan.get("success") and stale and not key_scan.get("skipped"):
            try:
                from app.services.wechat_contact_cache_import import ensure_decrypted_wechat_dbs

                decrypt_detail = ensure_decrypted_wechat_dbs(force_message=True)
            except Exception as exc:
                decrypt_detail = {"success": False, "message": str(exc)}
            runtime = load_runtime_config()
            apply_runtime_env(runtime)
            msg_path = str(runtime.get("message_db_path") or msg_path).strip()
            stale = False
            stale_reason = ""
            if live_main and msg_path and os.path.isfile(msg_path):
                try:
                    live_mt = os.path.getmtime(live_main)
                    wal = live_main + "-wal"
                    if os.path.isfile(wal):
                        live_mt = max(live_mt, os.path.getmtime(wal))
                    if os.path.getmtime(msg_path) < live_mt - 30:
                        stale = True
                        stale_reason = "重新扫描密钥后解密库仍落后于本机微信"
                except OSError:
                    pass

    ok_path = bool(msg_path and os.path.isfile(msg_path))
    # 解密库落后于本机微信时仍允许读取已有明文库（避免完全无法同步）
    readable = ok_path
    return {
        "success": readable,
        "message_db_path": msg_path if ok_path else "",
        "live_message_db": live_main,
        "decrypt": decrypt_detail,
        "snapshot": snapshot_detail,
        "stale": stale,
        "stale_reason": stale_reason,
        "db_dir": db_dir,
        "key_scan_attempted": bool(retry_key_scan),
        "read_only_stale": bool(stale and readable),
    }


def apply_runtime_env(cfg: dict[str, Any] | None = None) -> None:
    """将持久化配置应用到当前进程环境变量。"""
    data = cfg or load_runtime_config()
    toolkit = str(data.get("toolkit_dir") or "").strip()
    if toolkit:
        os.environ["WECHAT_DECRYPT_PATH"] = toolkit
    contact_db = str(data.get("contact_db_path") or "").strip()
    db_dir = str(data.get("db_dir") or "").strip()
    msg_db = str(data.get("message_db_path") or "").strip()
    if (
        platform.system().lower() == "darwin"
        and toolkit
        and db_dir
        and os.environ.get("WECHAT_USE_SNAPSHOT", "1") != "0"
    ):
        try:
            from app.services.wechat_db_snapshot import (
                message_snapshot_is_current,
                snapshot_paths,
            )

            paths = snapshot_paths(toolkit)
            plain = paths["plain_message_db"]
            plain_contact = paths["plain_contact_db"]
            if message_snapshot_is_current(db_dir, toolkit) and os.path.isfile(plain):
                msg_db = plain
                if os.path.isfile(plain_contact):
                    contact_db = plain_contact
        except Exception:
            pass
    if contact_db:
        os.environ["WECHAT_CONTACT_DB_PATH"] = contact_db
    if msg_db:
        os.environ["WECHAT_MSG_DB_PATH"] = msg_db
    if db_dir:
        os.environ["WECHAT_DB_DIR"] = db_dir
        m = re.search(r"(wxid_[0-9a-zA-Z]+)", db_dir)
        if m:
            os.environ["WECHAT_SELF_WXID"] = m.group(1)


def resolve_wechat_decrypt_toolkit_dir() -> str | None:
    """返回含 config.py / decrypt_db.py 的 wechat-decrypt 目录。"""
    persisted = str(load_runtime_config().get("toolkit_dir") or "").strip()
    if persisted and _is_valid_toolkit(persisted):
        return persisted

    repo = resolve_fhd_repo_root()
    repo_root = repo if repo is not None else Path(get_resource_path()).parent

    candidates: list[Path] = [
        Path(get_resource_path("wechat-decrypt")),
        repo_root / "XCAGI" / "resources" / "wechat-decrypt",
        repo_root / "XCAGI" / "wechat-decrypt",
        repo_root / "wechat-decrypt",
    ]
    env_path = os.environ.get("WECHAT_DECRYPT_PATH", "").strip()
    if env_path:
        candidates.insert(0, Path(env_path))

    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        if _is_valid_toolkit(p):
            return str(p.resolve())
    return None


def _is_valid_toolkit(path: str | Path) -> bool:
    p = Path(path)
    return (p / "config.py").is_file() and (p / "decrypt_db.py").is_file()


def _db_storage_mtime(db_storage: str) -> float:
    msg_dir = os.path.join(db_storage, "message")
    target = msg_dir if os.path.isdir(msg_dir) else db_storage
    try:
        return os.path.getmtime(target)
    except OSError:
        return 0.0


def detect_wechat_db_storage_dirs() -> list[str]:
    """按最近活跃排序的 db_storage 候选路径。"""
    home = Path.home()
    patterns: list[str] = []

    if platform.system().lower() == "windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            patterns.append(os.path.join(appdata, "Tencent", "xwechat", "config", "*.ini"))
    else:
        patterns.extend(
            [
                str(home / "Documents" / "xwechat_files" / "*" / "db_storage"),
                str(
                    home
                    / "Library"
                    / "Containers"
                    / "com.tencent.xinWeChat"
                    / "Data"
                    / "Documents"
                    / "xwechat_files"
                    / "*"
                    / "db_storage"
                ),
                str(
                    home
                    / "Library"
                    / "Containers"
                    / "com.tencent.xWeChat"
                    / "Data"
                    / "Documents"
                    / "xwechat_files"
                    / "*"
                    / "db_storage"
                ),
            ]
        )

    # Windows ini roots
    if platform.system().lower() == "windows":
        try:
            from app.services.wechat_contact_cache_import import _resolve_wechat_decrypt_dir

            toolkit = _resolve_wechat_decrypt_dir()
            if toolkit:
                sys.path.insert(0, toolkit)
                from config import _auto_detect_db_dir_windows  # type: ignore

                detected = _auto_detect_db_dir_windows()
                if detected and os.path.isdir(detected):
                    return [detected]
        except Exception:
            logger.debug("Windows wechat db auto-detect fallback", exc_info=True)

    seen: set[str] = set()
    found: list[str] = []
    for pattern in patterns:
        if pattern.endswith("*.ini"):
            continue
        for match in glob.glob(pattern):
            norm = os.path.normpath(match)
            if os.path.isdir(match) and norm not in seen:
                seen.add(norm)
                found.append(match)

    found.sort(key=_db_storage_mtime, reverse=True)
    return found


def _write_toolkit_config(toolkit_dir: str, db_dir: str) -> str:
    cfg_path = os.path.join(toolkit_dir, "config.json")
    process = "Weixin.exe" if platform.system().lower() == "windows" else "WeChat"
    payload = {
        "db_dir": db_dir,
        "keys_file": "all_keys.json",
        "decrypted_dir": "decrypted",
        "decoded_image_dir": "decoded_images",
        "wechat_process": process,
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
    return cfg_path


def _keys_file_usable(keys_path: str) -> bool:
    if not keys_path or not os.path.isfile(keys_path):
        return False
    try:
        with open(keys_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
        return any(not str(k).startswith("_") for k in data.keys())
    except Exception:
        return False


def _decrypted_sqlite_usable(toolkit_dir: str) -> bool:
    """本地 decrypted/*.db 是否已是可读的 SQLite（无密钥也可给 XCAGI 用）。"""
    for rel in ("message/message_0.db", "contact/contact.db"):
        path = os.path.join(toolkit_dir, "decrypted", rel)
        if not os.path.isfile(path) or os.path.getsize(path) < 4096:
            continue
        try:
            import sqlite3

            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()
                if row and int(row[0]) > 0:
                    return True
        except Exception:
            continue
    return False


def _compile_macos_key_scanner(toolkit_dir: str) -> str | None:
    src = os.path.join(toolkit_dir, "find_all_keys_macos.c")
    out = os.path.join(toolkit_dir, "find_all_keys_macos")
    if not os.path.isfile(src):
        return None
    if os.path.isfile(out) and os.access(out, os.X_OK):
        return out
    try:
        subprocess.run(
            [
                "cc",
                "-O2",
                "-o",
                out,
                src,
                "-framework",
                "Foundation",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        os.chmod(out, 0o755)
        return out if os.path.isfile(out) else None
    except Exception as exc:
        logger.warning("编译 find_all_keys_macos 失败: %s", exc)
        return None


def _try_extract_keys(toolkit_dir: str, *, force: bool = False) -> dict[str, Any]:
    keys_path = os.path.join(toolkit_dir, "all_keys.json")
    if _keys_file_usable(keys_path):
        return {
            "success": True,
            "skipped": True,
            "message": "已存在可用 all_keys.json，跳过提钥/内存扫描",
            "keys_file": keys_path,
        }

    if not force and _decrypted_sqlite_usable(toolkit_dir):
        return {
            "success": False,
            "skipped": True,
            "message": (
                "无 all_keys.json，但本地 decrypted 库可用；"
                "跳过内存扫描（微信 4.1.10 需关 SIP 后在终端提钥才能同步新消息）"
            ),
            "keys_file": keys_path,
            "use_decrypted_fallback": True,
        }

    system = platform.system().lower()
    if system == "darwin" and force:
        resigned_script = os.path.join(toolkit_dir, "capture_keys_resigned_spawn.py")
        if os.path.isfile(resigned_script):
            try:
                fr = subprocess.run(
                    [sys.executable, resigned_script],
                    cwd=toolkit_dir,
                    capture_output=True,
                    text=True,
                    timeout=240,
                    check=False,
                )
                if _keys_file_usable(keys_path):
                    return {
                        "success": True,
                        "message": "已通过桌面重签名 + CCKeyDerivationPBKDF 更新 all_keys.json",
                        "keys_file": keys_path,
                    }
                logger.warning(
                    "capture_keys_resigned_spawn: %s",
                    (fr.stderr or fr.stdout or "")[:500],
                )
            except Exception as exc:
                logger.warning("capture_keys_resigned_spawn: %s", exc)

    if system == "darwin":
        binary = _compile_macos_key_scanner(toolkit_dir)
        if not binary:
            return {
                "success": False,
                "message": "未找到或无法编译 find_all_keys_macos.c",
            }
        salts_script = os.path.join(toolkit_dir, "collect_wechat_db_salts.py")
        salts_tsv = os.path.join(toolkit_dir, "db_salts.tsv")
        if os.path.isfile(salts_script):
            try:
                subprocess.run(
                    [sys.executable, salts_script],
                    cwd=toolkit_dir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except Exception as exc:
                logger.warning("collect_wechat_db_salts: %s", exc)

        def _wechat_scan_pids() -> list[int]:
            """4.x message_0.db 由主进程 WeChat 打开，优先扫描主进程。"""
            main: list[int] = []
            rest: list[int] = []
            seen: set[int] = set()
            for cmd in (
                ["pgrep", "-x", "WeChat"],
                ["pgrep", "WeChatAppEx"],
            ):
                try:
                    pg = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                except Exception:
                    continue
                for line in (pg.stdout or "").split():
                    line = line.strip()
                    if not line.isdigit():
                        continue
                    p = int(line)
                    if p in seen:
                        continue
                    seen.add(p)
                    try:
                        ps = subprocess.run(
                            ["ps", "-p", str(p), "-o", "comm="],
                            capture_output=True,
                            text=True,
                            timeout=3,
                            check=False,
                        )
                        comm = (ps.stdout or "").strip()
                    except Exception:
                        comm = ""
                    if comm == "WeChat" or comm.endswith("/WeChat"):
                        main.append(p)
                    elif "WeChat" in comm:
                        rest.append(p)
            return main + rest

        scan_pids = _wechat_scan_pids()
        scan_env = os.environ.copy()
        if os.path.isfile(salts_tsv):
            scan_env["WECHAT_DB_SALTS_TSV"] = salts_tsv
        proc = None
        last_hint = ""
        try:
            for pid in scan_pids or [""]:
                scan_cmd = [binary]
                if pid:
                    scan_cmd.append(str(pid))
                if os.path.isfile(salts_tsv):
                    scan_cmd.append(salts_tsv)
                proc = subprocess.run(
                    scan_cmd,
                    cwd=toolkit_dir,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=scan_env,
                )
                last_hint = (proc.stderr or proc.stdout or "").strip()
                if _keys_file_usable(keys_path):
                    mtime = os.path.getmtime(keys_path)
                    if mtime > time.time() - 600:
                        break
            if proc is None:
                proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
            if proc.returncode != 0 or "task_for_pid failed" in (proc.stderr or ""):
                hint = last_hint or (proc.stderr or proc.stdout or "").strip()
                for script_name in (
                    "capture_keys_resigned_spawn.py",
                    "recover_keys_xprime_frida.py",
                    "capture_passphrase_frida.py",
                    "recover_keys_frida_memory.py",
                ):
                    frida_script = os.path.join(toolkit_dir, script_name)
                    if not os.path.isfile(frida_script):
                        continue
                    try:
                        fr = subprocess.run(
                            [sys.executable, frida_script],
                            cwd=toolkit_dir,
                            capture_output=True,
                            text=True,
                            timeout=600,
                            check=False,
                        )
                        if _keys_file_usable(keys_path):
                            mtime = os.path.getmtime(keys_path)
                            if mtime > time.time() - 600:
                                label = (
                                    "Frida PBKDF2 passphrase"
                                    if "passphrase" in script_name
                                    else "Frida 内存扫描"
                                )
                                return {
                                    "success": True,
                                    "message": f"已通过 {label} 更新 all_keys.json",
                                    "keys_file": keys_path,
                                }
                        hint = (fr.stderr or fr.stdout or hint or "").strip()
                    except Exception as exc:
                        hint = f"{hint} {exc}".strip()
                phrase_path = os.path.join(toolkit_dir, "passphrase.hex")
                derive_py = os.path.join(toolkit_dir, "derive_keys_pbkdf2.py")
                if os.path.isfile(phrase_path) and os.path.isfile(derive_py):
                    try:
                        phrase = open(phrase_path, encoding="utf-8").read().strip()
                        dr = subprocess.run(
                            [sys.executable, derive_py, "--passphrase-hex", phrase],
                            cwd=toolkit_dir,
                            capture_output=True,
                            text=True,
                            timeout=300,
                            check=False,
                        )
                        if _keys_file_usable(keys_path):
                            return {
                                "success": True,
                                "message": "已通过 PBKDF2 派生更新 all_keys.json",
                                "keys_file": keys_path,
                            }
                        hint = (dr.stderr or dr.stdout or hint or "").strip()
                    except Exception as exc:
                        hint = f"{hint} {exc}".strip()
                admin_pid = ""
                for p in scan_pids:
                    try:
                        ps = subprocess.run(
                            ["ps", "-p", str(p), "-o", "comm="],
                            capture_output=True,
                            text=True,
                            timeout=3,
                            check=False,
                        )
                        if "WeChatAppEx" in (ps.stdout or ""):
                            admin_pid = str(p)
                            break
                    except Exception:
                        continue
                if not admin_pid and scan_pids:
                    admin_pid = str(scan_pids[0])
                if admin_pid and os.path.isfile(salts_tsv):
                    try:
                        scan_sh = os.path.join(toolkit_dir, "scan-keys-admin.sh")
                        if os.path.isfile(scan_sh):
                            admin_cmd = f"bash '{scan_sh}'"
                        else:
                            admin_cmd = (
                                f"cd '{toolkit_dir}' && "
                                f"./find_all_keys_macos {admin_pid} '{salts_tsv}'"
                            )
                        admin = subprocess.run(
                            [
                                "osascript",
                                "-e",
                                f'do shell script "{admin_cmd}" with administrator privileges',
                            ],
                            capture_output=True,
                            text=True,
                            timeout=300,
                            check=False,
                        )
                        if admin.returncode == 0 and _keys_file_usable(keys_path):
                            mtime = os.path.getmtime(keys_path)
                            if mtime > time.time() - 600:
                                return {
                                    "success": True,
                                    "message": "已通过管理员权限扫描并更新 all_keys.json",
                                    "keys_file": keys_path,
                                }
                        hint = (admin.stderr or admin.stdout or hint or "").strip()
                    except Exception as exc:
                        hint = f"{hint} {exc}".strip()
                fail_msg = (
                    "内存密钥扫描失败：请保持微信已登录，打开目标群聊并滚动消息；"
                    "运行期间先切到其他聊天再切回目标群（触发 sqlite3_key）。\n"
                    f"  bash '{os.path.join(toolkit_dir, 'get-keys-now.sh')}'\n"
                    "（含 Frida 内存扫描 + 管理员扫内存，需完全磁盘访问）。"
                    + (f" 详情: {hint[:200]}" if hint else "")
                )
                if _keys_file_usable(keys_path):
                    return {
                        "success": True,
                        "skipped": True,
                        "used_cached_keys": True,
                        "message": (
                            "内存扫描未成功，沿用已有 all_keys.json 尝试解密；"
                            "若 message 库仍过期，请在终端执行 "
                            f"sudo {binary}"
                        ),
                        "keys_file": keys_path,
                        "needs_sudo": True,
                    }
                return {
                    "success": False,
                    "message": fail_msg,
                    "needs_sudo": True,
                }
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "内存密钥扫描超时"}
        except Exception as exc:
            return {"success": False, "message": f"内存密钥扫描异常: {exc}"}
    elif system in ("windows", "linux"):
        try:
            if toolkit_dir not in sys.path:
                sys.path.insert(0, toolkit_dir)
            import find_all_keys  # type: ignore

            rc = find_all_keys.main()
            if rc not in (0, None):
                return {
                    "success": False,
                    "message": "find_all_keys 未成功，请确认微信正在运行并具有读内存权限",
                }
        except Exception as exc:
            return {"success": False, "message": f"密钥扫描失败: {exc}"}
    else:
        return {"success": False, "message": f"不支持的平台: {system}"}

    if not os.path.isfile(keys_path):
        return {"success": False, "message": "扫描完成但未生成 all_keys.json"}

    try:
        usable = _keys_file_usable(keys_path)
    except Exception:
        usable = False
    if not usable:
        recover = os.path.join(toolkit_dir, "recover_wechat_keys_hmac.py")
        if os.path.isfile(recover):
            try:
                proc = subprocess.run(
                    [sys.executable, recover],
                    cwd=toolkit_dir,
                    capture_output=True,
                    text=True,
                    timeout=360,
                    check=False,
                )
                if _keys_file_usable(keys_path):
                    return {
                        "success": True,
                        "message": "HMAC 校验已恢复 all_keys.json",
                        "keys_file": keys_path,
                    }
                hint = (proc.stdout or proc.stderr or "")[-300:]
                return {
                    "success": False,
                    "message": f"内存扫描未得到可用密钥。{hint}",
                    "keys_file": keys_path,
                }
            except Exception as exc:
                logger.warning("recover_wechat_keys_hmac: %s", exc)

    return {
        "success": True,
        "message": "已生成 all_keys.json",
        "keys_file": keys_path,
    }


def auto_configure_wechat_decrypt(*, force_key_scan: bool = False) -> dict[str, Any]:
    """
    全自动配置 wechat-decrypt。

    返回 steps 列表供前端展示进度；success 为 True 时表示至少完成目录与 config 写入。
    """
    steps: list[dict[str, Any]] = []

    def add_step(step_id: str, label: str, state: str, detail: str = "") -> None:
        steps.append({"id": step_id, "label": label, "state": state, "detail": detail})

    toolkit = resolve_wechat_decrypt_toolkit_dir()
    if not toolkit:
        add_step(
            "toolkit",
            "定位 wechat-decrypt 工具",
            "error",
            "未找到含 config.py 的工具目录（请确认 XCAGI/wechat-decrypt 存在）",
        )
        return {
            "success": False,
            "message": "未找到 wechat-decrypt 工具包",
            "steps": steps,
        }
    add_step("toolkit", "定位 wechat-decrypt 工具", "done", toolkit)

    db_candidates = detect_wechat_db_storage_dirs()
    if not db_candidates:
        add_step(
            "db_dir",
            "检测微信数据目录",
            "error",
            "未找到 db_storage（macOS: ~/Documents/xwechat_files 或微信容器目录）",
        )
        return {
            "success": False,
            "message": "未检测到本机微信数据目录，请确认微信已登录并产生本地数据",
            "steps": steps,
            "toolkit_dir": toolkit,
        }

    db_dir = db_candidates[0]
    add_step(
        "db_dir",
        "检测微信数据目录",
        "done",
        db_dir + (f"（另有 {len(db_candidates) - 1} 个候选）" if len(db_candidates) > 1 else ""),
    )

    try:
        cfg_path = _write_toolkit_config(toolkit, db_dir)
        add_step("config", "写入 config.json", "done", cfg_path)
    except Exception as exc:
        add_step("config", "写入 config.json", "error", str(exc))
        return {
            "success": False,
            "message": f"写入配置失败: {exc}",
            "steps": steps,
        }

    keys_step_label = "强制扫描解密密钥（微信需保持登录）" if force_key_scan else "提取解密密钥"
    keys_path = os.path.join(toolkit, "all_keys.json")
    key_result = _try_extract_keys(toolkit, force=force_key_scan)
    if key_result.get("success"):
        state = "skipped" if key_result.get("skipped") else "done"
        add_step("keys", keys_step_label, state, key_result.get("message", ""))
    elif key_result.get("use_decrypted_fallback") and _decrypted_sqlite_usable(toolkit):
        add_step(
            "keys",
            keys_step_label,
            "skipped",
            key_result.get("message", "使用已有解密库"),
        )
        key_result = {**key_result, "success": True, "used_decrypted_fallback": True}
    elif _keys_file_usable(keys_path):
        add_step(
            "keys",
            keys_step_label,
            "skipped",
            (key_result.get("message") or "内存扫描失败")
            + "；将尝试使用已有 all_keys.json 解密 message_0.db",
        )
        key_result = {**key_result, "success": True, "used_cached_keys": True}
    else:
        add_step(
            "keys",
            keys_step_label,
            "error",
            key_result.get("message", "未找到可用密钥，请手动运行 find_all_keys_macos"),
        )

    decrypted_contact = os.path.join(toolkit, "decrypted", "contact", "contact.db")
    decrypted_message = os.path.join(toolkit, "decrypted", "message", "message_0.db")

    runtime = {
        "toolkit_dir": toolkit,
        "db_dir": db_dir,
        "config_path": os.path.join(toolkit, "config.json"),
        "keys_file": os.path.join(toolkit, "all_keys.json"),
        "contact_db_path": decrypted_contact,
        "message_db_path": decrypted_message,
        "db_candidates": db_candidates,
        "keys_scan_ok": bool(key_result.get("success")),
    }
    save_runtime_config(runtime)
    apply_runtime_env(runtime)

    add_step("env", "应用运行时环境", "done", get_app_data_dir())

    crypto_ok, crypto_detail = ensure_pycryptodome(auto_install=True)
    if crypto_ok:
        add_step("pycrypto", "解密依赖 pycryptodome", "done", crypto_detail)
    else:
        add_step("pycrypto", "安装解密依赖 pycryptodome", "error", crypto_detail)

    sync_detail = ""
    sync_ok = False
    try:
        from app.services.wechat_contact_cache_import import ensure_decrypted_wechat_dbs

        if toolkit not in sys.path:
            sys.path.insert(0, toolkit)
        sync_result = ensure_decrypted_wechat_dbs(force_message=force_key_scan)
        sync_ok = bool(sync_result.get("success"))
        if sync_ok:
            sync_detail = sync_result.get("message", "解密同步完成")
            add_step("decrypt", "同步并解密数据库", "done", sync_detail)
        else:
            sync_detail = sync_result.get("message", "解密未完成")
            add_step("decrypt", "同步并解密数据库", "skipped", sync_detail)
    except Exception as exc:
        sync_detail = str(exc)
        add_step("decrypt", "同步并解密数据库", "skipped", sync_detail)

    contact_exists = os.path.isfile(decrypted_contact)
    message_exists = os.path.isfile(decrypted_message)
    freshness = _wechat_db_freshness(toolkit, db_dir) if toolkit and db_dir else {}
    message_stale = bool(freshness.get("message_stale"))
    contact_stale = bool(freshness.get("contact_stale"))

    if message_stale:
        stale_msg = (
            f"message_0.db 落后于本机微信（解密库 {_format_mtime(decrypted_message)}，"
            f"微信源库 {_format_mtime(freshness.get('live_message_db', ''))}）。"
            "请保持微信登录，在终端执行 sudo ./find_all_keys_macos 后重试。"
        )
        sync_detail = stale_msg
        for step in steps:
            if step.get("id") == "decrypt":
                step["detail"] = stale_msg
                step["state"] = "error"

    if sync_detail and "0 个数据库" in sync_detail and not message_stale:
        if message_stale:
            sync_detail = (
                "联系人库未重新解密；"
                f"消息库已落后本机微信（解密库 {_format_mtime(decrypted_message)}，"
                f"微信源库 {_format_mtime(freshness.get('live_message_db', ''))}）。"
                "请勾选「强制扫描密钥」或保持微信登录后重试，再点「同步聊天记录」。"
            )
            for step in steps:
                if step.get("id") == "decrypt":
                    step["detail"] = sync_detail
                    step["state"] = "skipped"
        elif contact_stale:
            sync_detail = (
                f"消息库未重新解密；联系人库落后于本机微信（解密库 {_format_mtime(decrypted_contact)}）。"
                "请重新扫描密钥后再解密。"
            )
            for step in steps:
                if step.get("id") == "decrypt":
                    step["detail"] = sync_detail
                    step["state"] = "skipped"
        elif contact_exists or message_exists:
            sync_detail = (
                "未重新解密（本地 decrypted 库不比微信源库旧，沿用已有结果；"
                "含 contact.db 与 message_0.db）"
            )
            for step in steps:
                if step.get("id") == "decrypt":
                    step["detail"] = sync_detail

    import_detail = ""
    import_total = 0
    try:
        from app.services.wechat_contact_cache_import import refresh_wechat_contacts_from_decrypt

        payload, code = refresh_wechat_contacts_from_decrypt()
        import_total = int(payload.get("total") or 0)
        if payload.get("success"):
            import_detail = payload.get("message", "联系人已导入应用库")
            add_step("import", "导入联系人到应用库", "done", import_detail)
        else:
            import_detail = payload.get("message", "导入跳过")
            state = "skipped" if payload.get("skipped") else "error"
            add_step("import", "导入联系人到应用库", state, import_detail)
    except Exception as exc:
        import_detail = str(exc)
        add_step("import", "导入联系人到应用库", "skipped", import_detail)

    summary_parts = ["wechat-decrypt 已自动配置"]
    if contact_exists:
        summary_parts.append("解密库 contact.db 可用")
    if message_exists and not message_stale:
        summary_parts.append("解密库 message_0.db 可用")
    elif message_stale:
        summary_parts.append("解密库 message_0.db 已过期，聊天记录同步将不可用")
    elif freshness.get("message_missing"):
        summary_parts.append("尚未解密 message_0.db，请扫描密钥后同步聊天记录")
    if sync_detail:
        summary_parts.append(sync_detail)
    if import_detail:
        summary_parts.append(import_detail)
    if import_total > 0:
        summary_parts.append(f"应用库共 {import_total} 条联系人可供读取")
    elif contact_exists and not import_detail:
        summary_parts.append("解密库有数据，但尚未写入应用库，请点「立即同步」")

    pipeline_ok = contact_exists or message_exists
    if force_key_scan and message_stale and not key_result.get("success"):
        pipeline_ok = bool(contact_exists or message_exists)
    if message_stale:
        summary_parts.insert(
            0,
            "解密库 message_0.db 已过期，将尽量同步已有解密记录（新消息需重新扫描密钥）",
        )

    return {
        "success": pipeline_ok,
        "message": "；".join(summary_parts),
        "imported_total": import_total,
        "toolkit_dir": toolkit,
        "db_dir": db_dir,
        "contact_db_exists": contact_exists,
        "message_db_exists": message_exists,
        "message_db_stale": message_stale,
        "contact_db_path": decrypted_contact if contact_exists else None,
        "message_db_path": decrypted_message if message_exists else None,
        "steps": steps,
        "keys_scan": key_result,
        "freshness": freshness,
    }


def get_wechat_decrypt_status() -> dict[str, Any]:
    """供 decrypt_status API 使用的聚合状态。"""
    runtime = load_runtime_config()
    apply_runtime_env(runtime)
    toolkit = resolve_wechat_decrypt_toolkit_dir()
    contact_path = str(runtime.get("contact_db_path") or "").strip()
    if not contact_path and toolkit:
        contact_path = os.path.join(toolkit, "decrypted", "contact", "contact.db")
    exists = bool(contact_path and os.path.isfile(contact_path))
    db_dir = str(runtime.get("db_dir") or "").strip()
    if not db_dir and toolkit:
        try:
            with open(os.path.join(toolkit, "config.json"), encoding="utf-8") as f:
                db_dir = str(json.load(f).get("db_dir") or "")
        except Exception:
            pass
    return {
        "success": True,
        "plugin_available": bool(toolkit),
        "toolkit_dir": toolkit,
        "db_dir": db_dir or None,
        "contact_db_path": contact_path or None,
        "contact_db_exists": exists,
        "runtime_configured": bool(runtime.get("toolkit_dir")),
        "keys_file_exists": bool(
            toolkit and os.path.isfile(os.path.join(toolkit, "all_keys.json"))
        ),
    }
