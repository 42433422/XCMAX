"""超级员工执行信任域：把"产品身份"与"工厂身份"沿正交轴 ``ExecutionScope`` 分开。

设计要点（见仓库根 ``ARCH-ENTERPRISE-MOD-EMPLOYEE.md`` 讨论）：

- 与 :class:`~app.application.super_employee_service.SuperEmployeeToolProfile`
  （codex / claude，"用哪个工具"轴）**正交**：本模块是"以什么身份执行"轴。
- ``deny-by-default``：缺/错平台令牌一律降级为 ``PRODUCT``；``FACTORY`` 仅凭不可伪造的
  平台密钥铸造。客户请求体里即便塞 ``scope=factory`` 也无法越权（不知道密钥）。
- 平台密钥只存在于平台环境（``XCMAX_FACTORY_CAPABILITY_TOKEN``），永不下发到客户部署。
"""

from __future__ import annotations

import enum
import hmac
import os
from dataclasses import dataclass
from typing import Any

# 平台密钥环境变量名。仅在平台/操作者机器配置；客户部署里为空 == 工厂能力禁用。
FACTORY_TOKEN_ENV = "XCMAX_FACTORY_CAPABILITY_TOKEN"
# 受信任的内部路由在合并完客户 body 后注入真令牌的保留键。
CONTEXT_TOKEN_KEY = "_factory_token"
CONTEXT_WORKSPACE_KEY = "workspace_id"
DEFAULT_WORKSPACE_ID = "xcmax"


class ExecutionScope(enum.Enum):
    """一次派工的执行身份。"""

    PRODUCT = "product"  # 客户面：窄工具、跑在客户设备/临时区、客户钱包计费
    FACTORY = "factory"  # 你的开发者：全权、跑在工厂 Workspace、平台计费

    def __str__(self) -> str:  # pragma: no cover - 便于日志
        return self.value


def _configured_token() -> str:
    return str(os.environ.get(FACTORY_TOKEN_ENV) or "").strip()


@dataclass(frozen=True)
class CapabilityGrant:
    """一次 ``invoke`` 的执行授权。

    ``grant`` 来自路由 / 内部铸造，**绝不**来自客户请求体里可伪造的字段。
    """

    scope: ExecutionScope
    workspace_id: str | None = None

    @property
    def is_factory(self) -> bool:
        return self.scope is ExecutionScope.FACTORY

    @classmethod
    def product(cls) -> CapabilityGrant:
        """默认拒绝档：产品域、无 workspace。"""
        return cls(ExecutionScope.PRODUCT, None)

    @classmethod
    def resolve(cls, context: dict[str, Any] | None) -> CapabilityGrant:
        """从 ``context`` 解析授权（``deny-by-default``）。

        仅当 ``context`` 携带的 ``_factory_token`` 与平台环境密钥**常量时间相等**时升
        ``FACTORY``；否则（含密钥未配置、令牌缺失/不符）一律 ``PRODUCT``。
        """
        ctx = context if isinstance(context, dict) else {}
        token = str(ctx.get(CONTEXT_TOKEN_KEY) or "").strip()
        expected = _configured_token()
        if expected and token and hmac.compare_digest(token, expected):
            ws = str(ctx.get(CONTEXT_WORKSPACE_KEY) or DEFAULT_WORKSPACE_ID).strip()
            return cls(ExecutionScope.FACTORY, ws or DEFAULT_WORKSPACE_ID)
        return cls.product()


def factory_context(
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """供受信任的内部入口（管理端工厂路由 / cron）构造带令牌的 ``context``。

    若平台密钥未配置（``XCMAX_FACTORY_CAPABILITY_TOKEN`` 为空），返回的 ``context`` 不含
    有效令牌，:meth:`CapabilityGrant.resolve` 将降级为 ``PRODUCT`` —— 即"未配置密钥=工厂
    禁用"的安全默认，不会因忘配密钥而把工厂能力暴露给任何人。
    """
    ctx: dict[str, Any] = dict(base) if isinstance(base, dict) else {}
    expected = _configured_token()
    if expected:
        ctx[CONTEXT_TOKEN_KEY] = expected
        ctx[CONTEXT_WORKSPACE_KEY] = (
            str(workspace_id or DEFAULT_WORKSPACE_ID).strip() or DEFAULT_WORKSPACE_ID
        )
    return ctx


def require_factory_capability(grant: CapabilityGrant) -> None:
    """结构性闸门：非 ``FACTORY`` 授权访问工厂能力时**硬抛**，不做软性拒绝。"""
    if not isinstance(grant, CapabilityGrant) or grant.scope is not ExecutionScope.FACTORY:
        raise PermissionError(
            "factory capability denied: product-scope grant cannot access factory tools"
        )


__all__ = [
    "FACTORY_TOKEN_ENV",
    "CONTEXT_TOKEN_KEY",
    "CONTEXT_WORKSPACE_KEY",
    "DEFAULT_WORKSPACE_ID",
    "ExecutionScope",
    "CapabilityGrant",
    "factory_context",
    "require_factory_capability",
]
