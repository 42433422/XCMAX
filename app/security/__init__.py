"""
LAN security package: 局域网模式 + 一级密钥授权。

- ``lan_config``    集中读取 ``.env`` 配置（开关、CIDR、TTL、bypass、cookie 名等）
- ``lan_ip``        客户端真实 IP 提取（含 X-Forwarded-For、信任代理白名单）
- ``license_token`` 基于 stdlib HMAC-SHA256 的短 token 签发与校验
- ``license_store`` 一级密钥与会话的持久化（独立 SQLite 文件，避免触动主库）
- ``lan_cidr_guard``    ASGI 中间件：网段白名单
- ``license_guard``     ASGI 中间件：cookie token 校验

公开导出仅暴露中间件与少量帮助函数；其余通过子模块按需引入。
"""

from app.security.lan_cidr_guard import LanCidrGuard
from app.security.license_guard import LanLicenseGuard

__all__ = [
    "LanCidrGuard",
    "LanLicenseGuard",
]
