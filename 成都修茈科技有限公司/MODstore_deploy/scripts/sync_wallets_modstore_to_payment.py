#!/usr/bin/env python3
"""把 modstore 库里有、payment_db 缺失的钱包补齐（不覆盖已有行）。

背景：PAYMENT_BACKEND=java 时 /api/wallet/* 走 Java/payment_db。
若历史余额只在 modstore.wallets，前端会显示 ¥0.00。

用法（CVM）::

    cd /opt/xcmax/current/成都修茈科技有限公司/MODstore_deploy
    .venv/bin/python scripts/sync_wallets_modstore_to_payment.py
    # 或 dry-run：
    .venv/bin/python scripts/sync_wallets_modstore_to_payment.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from pathlib import Path


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--env-file",
        default="/etc/xcmax/modstore.env",
        help="含 DATABASE_URL / DATABASE_USER / DATABASE_PASSWORD 的环境文件",
    )
    args = parser.parse_args()

    file_env = _load_env(Path(args.env_file))
    for k, v in file_env.items():
        os.environ.setdefault(k, v)

    mod_url = (os.environ.get("DATABASE_URL") or "").strip()
    user = (os.environ.get("DATABASE_USER") or "modstore_pay").strip()
    password = (os.environ.get("DATABASE_PASSWORD") or "").strip()
    jdbc = (os.environ.get("JAVA_DATABASE_URL") or "jdbc:postgresql://127.0.0.1:5432/payment_db").strip()
    if not mod_url:
        print("DATABASE_URL missing", file=sys.stderr)
        return 2
    if not jdbc.startswith("jdbc:postgresql://"):
        print("JAVA_DATABASE_URL must be jdbc:postgresql://...", file=sys.stderr)
        return 2
    host_db = jdbc[len("jdbc:postgresql://") :]
    pay_url = f"postgresql://{urllib.parse.quote(user)}:{urllib.parse.quote(password)}@{host_db}"

    from sqlalchemy import create_engine, text

    mod = create_engine(mod_url)
    pay = create_engine(pay_url)
    inserted: list[tuple[int, float]] = []
    ensured_users: list[int] = []
    skipped_no_user: list[int] = []

    with mod.connect() as mc:
        mod_w = list(
            mc.execute(
                text(
                    "select user_id, balance, coalesce(version,0) as version, updated_at from wallets"
                )
            ).mappings()
        )
        if args.dry_run:
            with pay.connect() as pc:
                pay_ids = {int(r[0]) for r in pc.execute(text("select user_id from wallets"))}
            missing = [
                (int(r["user_id"]), float(r["balance"] or 0))
                for r in mod_w
                if int(r["user_id"]) not in pay_ids
            ]
            print(f"dry-run: would insert {len(missing)} wallets")
            for uid, bal in missing[:50]:
                print(f"  user_id={uid} balance={bal:.2f}")
            if len(missing) > 50:
                print(f"  ... +{len(missing) - 50} more")
            return 0

        with pay.begin() as pc:
            pay_ids = {int(r[0]) for r in pc.execute(text("select user_id from wallets"))}
            pay_users = {int(r[0]) for r in pc.execute(text("select id from users"))}
            for row in mod_w:
                uid = int(row["user_id"])
                bal = row["balance"]
                ver = int(row["version"] or 0)
                upd = row["updated_at"]
                if uid in pay_ids:
                    continue
                if uid not in pay_users:
                    u = mc.execute(
                        text(
                            "select id, username, email, is_admin, created_at from users where id=:id"
                        ),
                        {"id": uid},
                    ).mappings().first()
                    if not u:
                        skipped_no_user.append(uid)
                        continue
                    uname = (u["username"] or f"user_{uid}")[:64]
                    email = u["email"]
                    taken = pc.execute(
                        text("select id from users where username=:u"), {"u": uname}
                    ).scalar()
                    if taken and int(taken) != uid:
                        uname = f"{uname[:50]}_{uid}"
                    if email:
                        etaken = pc.execute(
                            text("select id from users where email=:e"), {"e": email}
                        ).scalar()
                        if etaken and int(etaken) != uid:
                            email = None
                    pc.execute(
                        text(
                            """
                            INSERT INTO users (id, username, email, password_hash, is_admin, created_at)
                            VALUES (:id, :username, :email, 'external-jwt', :is_admin,
                                    coalesce(CAST(:created_at AS timestamp), NOW()))
                            ON CONFLICT (id) DO NOTHING
                            """
                        ),
                        {
                            "id": uid,
                            "username": uname,
                            "email": email,
                            "is_admin": bool(u["is_admin"]),
                            "created_at": u["created_at"].isoformat() if u["created_at"] else None,
                        },
                    )
                    pay_users.add(uid)
                    ensured_users.append(uid)
                pc.execute(
                    text(
                        """
                        INSERT INTO wallets (user_id, balance, version, updated_at)
                        VALUES (:uid, :bal, :ver, coalesce(CAST(:upd AS timestamp), NOW()))
                        """
                    ),
                    {
                        "uid": uid,
                        "bal": bal,
                        "ver": ver,
                        "upd": upd.isoformat() if upd else None,
                    },
                )
                inserted.append((uid, float(bal or 0)))

    print(f"ensured_users={ensured_users}")
    print(f"inserted={len(inserted)}")
    for uid, bal in inserted:
        print(f"  user_id={uid} balance={bal:.2f}")
    if skipped_no_user:
        print(f"skipped_no_user={skipped_no_user}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
