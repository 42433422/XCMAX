"""Private, origin-scoped cookie and conversation storage for xcagi-brain."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


class BrainError(Exception):
    """A user-facing command failure, without credentials or request bodies."""

    def __init__(self, message: str, *, kind: str = "command", status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def normalize_origin(raw: str) -> str:
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BrainError("origin 必须是 http(s)://主机[:端口]，不能含凭据、路径或查询")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise BrainError("非本机连接必须使用 HTTPS，以保护账号会话")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    suffix = f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
    return f"{parsed.scheme}://{host}{suffix}"


class SessionStore:
    def __init__(self, origin: str, directory: Path):
        self.origin = normalize_origin(origin)
        self.directory = directory.expanduser()
        if self.directory.is_symlink():
            raise BrainError("会话目录不能是符号链接")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt" and self.directory.stat().st_uid != os.getuid():
            raise BrainError("会话目录不属于当前用户")
        if os.name != "nt" and self.directory.stat().st_mode & 0o077:
            raise BrainError("会话目录必须仅当前用户可访问；请创建专用 0700 目录")
        key = hashlib.sha256(self.origin.encode()).hexdigest()
        self.cookie_path = self.directory / f"{key}.cookies"
        self.state_path = self.directory / f"{key}.json"
        self.cookies = http.cookiejar.LWPCookieJar()
        self.state: dict = {"origin": self.origin}
        for path in (self.cookie_path, self.state_path):
            self._check_private(path)
        if self.cookie_path.exists():
            self.cookies.load(str(self.cookie_path), ignore_discard=True)
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(self.state, dict) or self.state.get("origin") != self.origin:
                raise BrainError("会话文件 origin 不匹配，请检查 --session-dir")

    @staticmethod
    def _check_private(path: Path) -> None:
        if path.is_symlink():
            raise BrainError("会话文件不能是符号链接")
        if path.exists():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise BrainError("会话文件必须是普通文件")
            if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise BrainError("会话文件必须属于当前用户且权限为 0600")

    def _save_file(self, path: Path, content: str) -> None:
        self._check_private(path)
        fd, temporary = tempfile.mkstemp(prefix=".session-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self) -> None:
        self.cookies.clear_expired_cookies()
        self._save_file(self.cookie_path, "#LWP-Cookies-2.0\n" + self.cookies.as_lwp_str(True))
        self._save_file(self.state_path, json.dumps(self.state, ensure_ascii=False))

    def clear(self) -> None:
        self.cookies.clear()
        self.state = {"origin": self.origin}
        self.save()

    def csrf_token(self) -> str:
        for cookie in self.cookies:
            if cookie.name == "csrf_token" and not cookie.is_expired():
                return cookie.value or ""
        return ""
