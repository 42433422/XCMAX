"""一键创建/提权管理员账号 + 授予会员档（默认 VIP+ = plan_pro）。

用法：
    cd MODstore_deploy
    python -m scripts.grant_admin --username admin --password 'YourStrongPw!' --email admin@example.com

可选参数：
    --plan plan_pro          会员档：plan_basic / plan_pro / plan_enterprise / plan_svip2..8
    --days 365               会员有效期天数；传 0 表示永久（expires_at 留空）
    --no-admin               只授予会员档，不提权管理员
    --reset-password         账号已存在时重置密码（默认会保留旧密码）

行为：
    - 账号不存在：注册 + 创建钱包
    - 账号存在：根据 --reset-password 决定是否改密码
    - 默认 is_admin = True
    - 把该用户其它 user_plans 记录置为 is_active=False，再插入一条目标 plan
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from typing import Optional


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="创建/提权 MODstore 管理员账号 + 会员")
    p.add_argument("--username", required=True, help="用户名（登录用）")
    p.add_argument("--password", required=True, help="登录密码")
    p.add_argument("--email", default="", help="邮箱（可选，用于邮箱登录）")
    p.add_argument("--plan", default="plan_pro", help="会员档 id，默认 plan_pro（VIP+）")
    p.add_argument("--days", type=int, default=365, help="有效期天数；0 表示永久")
    p.add_argument("--no-admin", action="store_true", help="不提权管理员")
    p.add_argument("--reset-password", action="store_true", help="账号已存在时重置密码")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    username = args.username.strip()
    password = args.password
    email = (args.email or "").strip().lower() or None
    plan_id = args.plan.strip() or "plan_pro"

    if not username or not password:
        print("用户名和密码不能为空", file=sys.stderr)
        return 2

    from modstore_server.auth_service import hash_password, register_user
    from modstore_server.models import (
        PlanTemplate,
        User,
        UserPlan,
        Wallet,
        get_session_factory,
        init_db,
    )

    init_db()
    sf = get_session_factory()

    with sf() as session:
        plan = session.query(PlanTemplate).filter(PlanTemplate.id == plan_id).first()
        if not plan:
            available = [row.id for row in session.query(PlanTemplate.id).all()]
            print(f"plan_id 不存在：{plan_id}\n可用：{available}", file=sys.stderr)
            return 3

        user: Optional[User] = (
            session.query(User).filter(User.username == username).first()
        )
        created = False
        if user is None:
            session.close()
            user = register_user(username, password, email or "")
            created = True
            session = sf()
            user = session.query(User).filter(User.id == user.id).first()
        elif args.reset_password:
            user.password_hash = hash_password(password)

        if not args.no_admin:
            user.is_admin = True
        if email and (user.email or "").lower() != email:
            user.email = email

        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
        if wallet is None:
            session.add(Wallet(user_id=user.id, balance=0.0))

        for row in (
            session.query(UserPlan)
            .filter(UserPlan.user_id == user.id, UserPlan.is_active == True)
            .all()
        ):
            row.is_active = False

        expires_at = None
        if args.days and args.days > 0:
            expires_at = datetime.utcnow() + timedelta(days=int(args.days))

        session.add(
            UserPlan(
                user_id=user.id,
                plan_id=plan_id,
                started_at=datetime.utcnow(),
                expires_at=expires_at,
                is_active=True,
            )
        )
        session.commit()
        session.refresh(user)

        print(
            "OK · "
            + ("created" if created else "updated")
            + f" user_id={user.id} username={user.username} "
            + f"is_admin={bool(user.is_admin)} plan={plan_id} "
            + f"expires_at={expires_at.isoformat() if expires_at else 'never'}"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
