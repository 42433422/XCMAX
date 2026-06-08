"""AI 员工账号池 ORM 模型。

把"AI 员工拥有外部账号"这件事抽象成一张可共享的池表：每个 AI 员工
（``employee_id``，例如 ``xc-digital-butler``）名下可以挂任意多个外部
账号（QQ 官方机器人、企业微信、邮箱等），密钥 **不入库**——只在
``_local_secrets/<platform>/<account_id>.json`` 里存运行时凭证。

放在独立模块、由 ``models.py`` 末尾 ``import``，与 ``models_cs`` 同样的
扩展套路：让外部 ORM 仍共享 ``Base`` / metadata，``init_db`` 跑
``Base.metadata.create_all`` 时也会一并建表。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


class AIEmployeeAccount(Base):
    """AI 员工的外部账号档案（不存密钥本身，只存索引/状态）。

    ``platform`` 取值约定（暂列）：

    - ``qq``           QQ 官方机器人 V2（与 ``butler_qq_bridge`` 配套）
    - ``wechat``       企业/服务号（预留）
    - ``email``        邮箱（预留）
    - ``slack``、``feishu``、``discord``  …… 后续按平台补

    ``external_id`` 是该平台上这个账号的"对外名片"，比如 QQ 号、邮箱地址。
    跟 ``platform`` 联合唯一——同一个 QQ 号不能同时挂在两个 AI 员工名下。

    ``employee_id`` 是 manifest 里那一串 id（与 ``BUTLER_VIRTUAL_EMPLOYEE_ID``
    或 catalog 里 .xcemp 的 id 对齐），允许同一员工持有多个账号。

    密钥永远落在 ``secrets_path`` 指向的那个 JSON 文件里，文件由
    ``ai_employee_account_secrets.py`` 读写；DB 只保留路径引用。
    """

    __tablename__ = "ai_employee_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_ai_acc_platform_external"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(32), nullable=False, index=True)
    external_id = Column(String(128), nullable=False, index=True)
    employee_id = Column(String(128), nullable=False, index=True)
    display_name = Column(String(128), default="")
    status = Column(String(16), default="active", index=True)  # active/disabled/revoked
    sandbox = Column(Boolean, default=False, nullable=False)
    secrets_path = Column(String(512), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen_at = Column(DateTime, nullable=True)
