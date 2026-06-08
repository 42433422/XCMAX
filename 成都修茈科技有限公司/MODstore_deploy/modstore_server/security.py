"""MODstore 安全相关工具和配置"""

from __future__ import annotations

import os
import secrets
import string
from pathlib import Path


def generate_secure_key(length: int = 32) -> str:
    """生成安全的随机密钥"""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(alphabet) for _ in range(length))


def get_env_var(name: str, default: str | None = None) -> str:
    """获取环境变量，确保敏感数据不被硬编码"""
    value = os.environ.get(name)
    if value is None:
        return default
    return value


_INSECURE_JWT_DEFAULTS = frozenset(
    {
        "modstore-dev-secret-change-in-prod",
        "modstore-dev-secret-change-in-prod-32bytes",
        "your-random-secret-key-change-in-production",
        "changeme",
        "secret",
    }
)

_INSECURE_ADMIN_TOKEN_DEFAULTS = frozenset(
    {
        "dev-admin-token",
        "your-admin-token-change-this",
        "admin",
    }
)

_INSECURE_ADMIN_PASSWORD_DEFAULTS = frozenset(
    {
        "admin123",
        "admin",
        "password",
        "123456",
    }
)

_INSECURE_PAYMENT_SECRET_DEFAULTS = frozenset(
    {
        "default_secret_key",
        "secret",
        "payment_secret",
        "changeme",
    }
)


def ensure_secure_config() -> None:
    deploy_tier = (os.environ.get("MODSTORE_DEPLOY_TIER") or "").strip().lower()
    is_production = deploy_tier in ("production", "prod")

    jwt_secret = get_env_var("MODSTORE_JWT_SECRET")
    if not jwt_secret:
        print("错误: MODSTORE_JWT_SECRET 未设置，服务拒绝启动")
        if is_production:
            raise SystemExit(1)
    elif jwt_secret in _INSECURE_JWT_DEFAULTS:
        print(f"错误: MODSTORE_JWT_SECRET 使用了已知不安全默认值 '{jwt_secret}'，服务拒绝启动")
        if is_production:
            raise SystemExit(1)
        else:
            print(f"建议使用: {generate_secure_key()}")

    admin_token = get_env_var("MODSTORE_ADMIN_RECHARGE_TOKEN")
    if not admin_token:
        print("警告: MODSTORE_ADMIN_RECHARGE_TOKEN 未设置，管理员充值接口不可用")
    elif admin_token in _INSECURE_ADMIN_TOKEN_DEFAULTS:
        print(f"错误: MODSTORE_ADMIN_RECHARGE_TOKEN 使用了已知不安全默认值 '{admin_token}'")
        if is_production:
            raise SystemExit(1)
        else:
            print(f"建议使用: {generate_secure_key()}")

    bootstrap_pwd = get_env_var("MODSTORE_BOOTSTRAP_ADMIN_PASSWORD")
    if bootstrap_pwd and bootstrap_pwd in _INSECURE_ADMIN_PASSWORD_DEFAULTS:
        print(f"错误: MODSTORE_BOOTSTRAP_ADMIN_PASSWORD 使用了已知不安全默认值 '{bootstrap_pwd}'")
        if is_production:
            raise SystemExit(1)
        else:
            print("建议设置强密码")

    alipay_app_id = get_env_var("ALIPAY_APP_ID")
    if not alipay_app_id or alipay_app_id == "your-alipay-app-id":
        print("警告: ALIPAY_APP_ID 未设置或使用默认值")

    smtp_password = get_env_var("MODSTORE_SMTP_PASSWORD")
    if not smtp_password or smtp_password == "your-qq-smtp-password":
        print("警告: MODSTORE_SMTP_PASSWORD 未设置或使用默认值")

    payment_secret = get_env_var("PAYMENT_SECRET_KEY")
    if not payment_secret:
        print("错误: PAYMENT_SECRET_KEY 未设置，支付签名功能不可用")
        if is_production:
            raise SystemExit(1)
    elif payment_secret in _INSECURE_PAYMENT_SECRET_DEFAULTS:
        print(f"错误: PAYMENT_SECRET_KEY 使用了已知不安全默认值 '{payment_secret}'，服务拒绝启动")
        if is_production:
            raise SystemExit(1)
        else:
            print(f"建议使用: {generate_secure_key()}")


def secure_file_permissions(file_path: Path) -> None:
    """设置文件的安全权限"""
    if file_path.exists():
        # 在不同操作系统上设置适当的权限
        if os.name == "posix":
            # Unix/Linux系统
            os.chmod(file_path, 0o600)  # 只有所有者可读写
        elif os.name == "nt":
            # Windows系统
            # Windows权限设置较为复杂，这里简化处理
            pass


def validate_secure_config() -> dict[str, bool]:
    """验证安全配置是否正确"""
    return {
        "jwt_secret_set": bool(
            get_env_var("MODSTORE_JWT_SECRET")
            and get_env_var("MODSTORE_JWT_SECRET") not in _INSECURE_JWT_DEFAULTS
        ),
        "admin_token_set": bool(
            get_env_var("MODSTORE_ADMIN_RECHARGE_TOKEN")
            and get_env_var("MODSTORE_ADMIN_RECHARGE_TOKEN") not in _INSECURE_ADMIN_TOKEN_DEFAULTS
        ),
        "payment_secret_set": bool(
            get_env_var("PAYMENT_SECRET_KEY")
            and get_env_var("PAYMENT_SECRET_KEY") not in _INSECURE_PAYMENT_SECRET_DEFAULTS
        ),
        "alipay_configured": bool(
            get_env_var("ALIPAY_APP_ID") and get_env_var("ALIPAY_APP_ID") != "your-alipay-app-id"
        ),
        "smtp_configured": bool(
            get_env_var("MODSTORE_SMTP_PASSWORD")
            and get_env_var("MODSTORE_SMTP_PASSWORD") != "your-qq-smtp-password"
        ),
    }
