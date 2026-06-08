"""沙箱运行时 preamble：在用户脚本执行前注入，作用范围仅限子进程。

由 ``sandbox_runner.py`` 在写 ``script.py`` 时拼接到用户代码前面。
不要直接 import 本模块——它的职责是被读出文本后注入到子进程脚本里。

提供两类边界（best-effort，对抗 ctypes/反射等深度逃逸需要 OS 级容器）：

1. **文件系统边界**：``builtins.open`` / ``os.open`` / ``os.scandir`` /
   ``os.listdir`` / ``os.walk`` / ``os.chdir`` / ``os.remove`` / ``os.unlink`` /
   ``os.rename`` / ``os.replace`` / ``os.rmdir`` / ``os.mkdir`` / ``os.makedirs``
   等的路径参数必须解析后位于 ``MODSTORE_SANDBOX_WORK_DIR`` 之下；
   越界抛 ``PermissionError`` 而不是默默放行。
2. **网络出网阻断**：``socket.socket`` / ``socket.create_connection`` /
   ``socket.create_server`` / ``socket.socketpair`` 全部替换为抛错。
"""

# ruff: noqa: E501

PREAMBLE_SOURCE = r'''# === MODSTORE SANDBOX PREAMBLE (auto-injected, do not edit) ===
import os as _ms_os
import sys as _ms_sys
import builtins as _ms_builtins
from pathlib import Path as _MsPath


def _ms_get_workdir():
    raw = _ms_os.environ.get("MODSTORE_SANDBOX_WORK_DIR") or _ms_os.getcwd()
    try:
        return _MsPath(raw).resolve()
    except Exception:
        return _MsPath(_ms_os.getcwd()).resolve()


_MS_WORK_DIR = _ms_get_workdir()


def _ms_within(path):
    """True 表示 path 解析后位于 _MS_WORK_DIR（含自身）之下。"""
    if path is None:
        return False
    if isinstance(path, (bytes, bytearray)):
        try:
            path = path.decode("utf-8", errors="strict")
        except Exception:
            return False
    if isinstance(path, int):
        # 已打开的 fd：放行（fd 是上层验证过的）
        return True
    try:
        rp = _MsPath(_ms_os.fspath(path)).expanduser()
        if not rp.is_absolute():
            rp = (_MS_WORK_DIR / rp)
        rp = rp.resolve(strict=False)
    except Exception:
        return False
    try:
        rp.relative_to(_MS_WORK_DIR)
        return True
    except ValueError:
        return False


class _MsSandboxDenied(PermissionError):
    """沙箱拒绝越界 / 网络访问"""


def _ms_assert_within(path, op):
    if not _ms_within(path):
        raise _MsSandboxDenied(
            "sandbox: {op} 越界，路径必须在工作目录 {wd!s} 之下，收到 {p!r}".format(
                op=op, wd=_MS_WORK_DIR, p=path,
            )
        )


# ---- fd 白名单：只允许使用 stdio (0/1/2) 与 preamble 包装的 open 创建出来的 fd
# 防止脚本通过 os.fdopen / os.dup / os.dup2 / os.read / os.write 拿任意 fd 绕过路径检查
_MS_ALLOWED_FDS = {0, 1, 2}


def _ms_register_fd(fd):
    try:
        _MS_ALLOWED_FDS.add(int(fd))
    except Exception:
        pass


def _ms_assert_fd(fd, op):
    try:
        i = int(fd)
    except Exception:
        raise _MsSandboxDenied("sandbox: {} 收到非法 fd {!r}".format(op, fd))
    if i not in _MS_ALLOWED_FDS:
        raise _MsSandboxDenied(
            "sandbox: {} 拒绝未由 preamble 注册的 fd={}（fd 白名单内 {!r}）".format(
                op, i, sorted(_MS_ALLOWED_FDS)
            )
        )


# ---- builtins.open ----------------------------------------------------------
_ms_orig_open = _ms_builtins.open


def _ms_safe_open(file, mode="r", *args, **kwargs):
    if isinstance(file, int):
        _ms_assert_fd(file, "open(fd)")
        return _ms_orig_open(file, mode, *args, **kwargs)
    _ms_assert_within(file, "open")
    f = _ms_orig_open(file, mode, *args, **kwargs)
    try:
        _ms_register_fd(f.fileno())
    except Exception:
        pass
    return f


_ms_builtins.open = _ms_safe_open

# ---- os 路径 / fd 相关 -------------------------------------------------------
_ms_orig_os_open = _ms_os.open


def _ms_safe_os_open(path, *args, **kwargs):
    _ms_assert_within(path, "os.open")
    fd = _ms_orig_os_open(path, *args, **kwargs)
    _ms_register_fd(fd)
    return fd


_ms_os.open = _ms_safe_os_open


def _ms_wrap_fd_only(name):
    fn = getattr(_ms_os, name, None)
    if fn is None:
        return

    def _wrapped(fd, *args, **kwargs):
        _ms_assert_fd(fd, "os." + name)
        return fn(fd, *args, **kwargs)

    setattr(_ms_os, name, _wrapped)


for _n in (
    "fdopen",
    "read",
    "write",
    "lseek",
    "ftruncate",
    "fstat",
    "fsync",
    "fdatasync",
    "close",
    "dup",
):
    _ms_wrap_fd_only(_n)


# os.dup2(fd, fd2) 需要校验源 fd
_ms_orig_dup2 = getattr(_ms_os, "dup2", None)
if _ms_orig_dup2 is not None:

    def _ms_safe_dup2(fd, fd2, *args, **kwargs):
        _ms_assert_fd(fd, "os.dup2 src")
        result = _ms_orig_dup2(fd, fd2, *args, **kwargs)
        _ms_register_fd(fd2)
        return result

    _ms_os.dup2 = _ms_safe_dup2


def _ms_wrap_path1(name):
    fn = getattr(_ms_os, name, None)
    if fn is None:
        return

    def _wrapped(path, *args, **kwargs):
        _ms_assert_within(path, "os." + name)
        return fn(path, *args, **kwargs)

    setattr(_ms_os, name, _wrapped)


for _n in (
    "scandir",
    "listdir",
    "remove",
    "unlink",
    "rmdir",
    "mkdir",
    "makedirs",
    "stat",
    "lstat",
    "chmod",
    "chown",
    "readlink",
    "symlink",
    "link",
    "chdir",
    "truncate",
    "utime",
    "access",
):
    _ms_wrap_path1(_n)


def _ms_wrap_path2(name):
    fn = getattr(_ms_os, name, None)
    if fn is None:
        return

    def _wrapped(src, dst, *args, **kwargs):
        _ms_assert_within(src, "os." + name + " src")
        _ms_assert_within(dst, "os." + name + " dst")
        return fn(src, dst, *args, **kwargs)

    setattr(_ms_os, name, _wrapped)


for _n in ("rename", "replace", "renames"):
    _ms_wrap_path2(_n)


# os.walk: 起点目录必须在 work_dir 内（递归遍历由 work_dir 边界自然约束）
_ms_orig_walk = _ms_os.walk


def _ms_safe_walk(top, *args, **kwargs):
    _ms_assert_within(top, "os.walk")
    return _ms_orig_walk(top, *args, **kwargs)


_ms_os.walk = _ms_safe_walk

# ---- 网络阻断（仅放行 127.0.0.1:MODSTORE_RUNTIME_PORT 给自家 SDK 走 RPC）-----
try:
    import socket as _ms_socket

    _ms_orig_socket_cls = _ms_socket.socket
    _ms_orig_create_conn = _ms_socket.create_connection

    def _ms_rpc_port():
        try:
            return int(_ms_os.environ.get("MODSTORE_RUNTIME_PORT") or 0)
        except Exception:
            return 0

    def _ms_rpc_hosts():
        """允许连到的 RPC host 集合。

        - subprocess 后端：``127.0.0.1`` / ``localhost`` / ``::1``
        - docker-per-run 后端：会另设 ``MODSTORE_RUNTIME_HOST=host.docker.internal``
          指向宿主网关；该值同样进白名单。
        """
        base = {"127.0.0.1", "localhost", "::1"}
        extra = (_ms_os.environ.get("MODSTORE_RUNTIME_HOST") or "").strip()
        if extra:
            base.add(extra)
        return base

    def _ms_is_loopback_rpc(addr):
        """addr 形如 (host, port)；仅允许 RPC host 白名单 + RPC 端口。"""
        try:
            host = str(addr[0])
            port = int(addr[1])
        except Exception:
            return False
        if host not in _ms_rpc_hosts():
            return False
        rpc = _ms_rpc_port()
        return rpc != 0 and port == rpc

    class _MsGuardedSocket(_ms_orig_socket_cls):  # type: ignore[misc]
        """socket 子类：``connect`` 时校验目标为本地 RPC 端口。"""

        def connect(self, address):
            if not _ms_is_loopback_rpc(address):
                raise _MsSandboxDenied(
                    "sandbox: 网络已禁用（仅允许连 127.0.0.1:MODSTORE_RUNTIME_PORT 走 SDK），"
                    "目标 {!r} 被拒绝".format(address)
                )
            return super().connect(address)

        def connect_ex(self, address):
            if not _ms_is_loopback_rpc(address):
                raise _MsSandboxDenied(
                    "sandbox: 网络已禁用，目标 {!r} 被拒绝".format(address)
                )
            return super().connect_ex(address)

        def bind(self, address):
            raise _MsSandboxDenied("sandbox: bind/listen 已禁用")

    _ms_socket.socket = _MsGuardedSocket

    def _ms_safe_create_connection(address, *args, **kwargs):
        if not _ms_is_loopback_rpc(address):
            raise _MsSandboxDenied(
                "sandbox: 网络已禁用，create_connection 目标 {!r} 被拒绝".format(address)
            )
        return _ms_orig_create_conn(address, *args, **kwargs)

    _ms_socket.create_connection = _ms_safe_create_connection

    def _ms_no_create_server(*args, **kwargs):
        raise _MsSandboxDenied("sandbox: 不允许在脚本里 create_server / 监听端口")

    if hasattr(_ms_socket, "create_server"):
        _ms_socket.create_server = _ms_no_create_server
    if hasattr(_ms_socket, "socketpair"):
        _ms_socket.socketpair = _ms_no_create_server

    # DNS 解析也拦下：避免 DNS 隧道泄露 / 主机名探测；仅放行 loopback 名字
    # 与 ``MODSTORE_RUNTIME_HOST``（docker-per-run 设的网关名，如 host.docker.internal）。
    _ms_loopback_names = {"localhost", "ip6-localhost", "localhost.localdomain"}

    def _ms_dns_allowed(name):
        if not isinstance(name, str):
            return False
        if name in ("127.0.0.1", "::1"):
            return True
        if name.lower() in _ms_loopback_names:
            return True
        rpc_host = (_ms_os.environ.get("MODSTORE_RUNTIME_HOST") or "").strip()
        return bool(rpc_host) and name == rpc_host

    _ms_orig_gethostbyname = getattr(_ms_socket, "gethostbyname", None)
    if _ms_orig_gethostbyname is not None:

        def _ms_safe_gethostbyname(name):
            if not _ms_dns_allowed(name):
                raise _MsSandboxDenied(
                    "sandbox: DNS 已禁用（仅 localhost/127.0.0.1/::1），收到 {!r}".format(name)
                )
            return _ms_orig_gethostbyname(name)

        _ms_socket.gethostbyname = _ms_safe_gethostbyname

    _ms_orig_gethostbyname_ex = getattr(_ms_socket, "gethostbyname_ex", None)
    if _ms_orig_gethostbyname_ex is not None:

        def _ms_safe_gethostbyname_ex(name):
            if not _ms_dns_allowed(name):
                raise _MsSandboxDenied(
                    "sandbox: DNS 已禁用，收到 {!r}".format(name)
                )
            return _ms_orig_gethostbyname_ex(name)

        _ms_socket.gethostbyname_ex = _ms_safe_gethostbyname_ex

    _ms_orig_gethostbyaddr = getattr(_ms_socket, "gethostbyaddr", None)
    if _ms_orig_gethostbyaddr is not None:

        def _ms_safe_gethostbyaddr(addr):
            if not _ms_dns_allowed(addr):
                raise _MsSandboxDenied(
                    "sandbox: DNS 反查已禁用，收到 {!r}".format(addr)
                )
            return _ms_orig_gethostbyaddr(addr)

        _ms_socket.gethostbyaddr = _ms_safe_gethostbyaddr

    _ms_orig_getaddrinfo = getattr(_ms_socket, "getaddrinfo", None)
    if _ms_orig_getaddrinfo is not None:

        def _ms_safe_getaddrinfo(host, port, *args, **kwargs):
            # host 为 None 表示绑定本机所有接口；脚本里几乎不会合理用到，全拦
            if host is None or not _ms_dns_allowed(host):
                raise _MsSandboxDenied(
                    "sandbox: getaddrinfo 已禁用，收到 host={!r} port={!r}".format(host, port)
                )
            return _ms_orig_getaddrinfo(host, port, *args, **kwargs)

        _ms_socket.getaddrinfo = _ms_safe_getaddrinfo

    _ms_orig_getnameinfo = getattr(_ms_socket, "getnameinfo", None)
    if _ms_orig_getnameinfo is not None:

        def _ms_safe_getnameinfo(addr, *args, **kwargs):
            host = addr[0] if isinstance(addr, tuple) and addr else None
            if not _ms_dns_allowed(host):
                raise _MsSandboxDenied(
                    "sandbox: getnameinfo 已禁用，收到 {!r}".format(addr)
                )
            return _ms_orig_getnameinfo(addr, *args, **kwargs)

        _ms_socket.getnameinfo = _ms_safe_getnameinfo
except ImportError:
    pass

# === END MODSTORE SANDBOX PREAMBLE ===

'''
