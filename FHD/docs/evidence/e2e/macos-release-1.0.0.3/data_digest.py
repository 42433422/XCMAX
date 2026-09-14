#!/usr/bin/env python3
"""数据保留摘要：统计 XCAGI userData 关键数据的字节级/文件级指标。

用法: python3 data_digest_10003.py <输出.json>
路径: ~/Library/Application Support/XCAGI/（正式包 userData）
"""
import glob, json, os, sys

USER_DATA = os.path.expanduser("~/Library/Application Support/XCAGI")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "digest.json")


def fsize(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return -1


def count(pattern):
    return len(glob.glob(pattern, recursive=True))


db = os.path.join(USER_DATA, "data", "xcagi.db")
if not os.path.exists(db):
    db = os.path.join(USER_DATA, "xcagi.db")
digest = {
    "xcagi.db.bytes": fsize(db),
    "xcagi.db.wal.bytes": fsize(db + "-wal"),
    "excel_vectors.db.bytes": fsize(os.path.join(USER_DATA, "excel_vectors.db")),
    "mod_dbs.files": count(os.path.join(USER_DATA, "mod_data", "**", "*.db")),
    "uploads.files": count(os.path.join(USER_DATA, "uploads", "**")),
    "uploads.templates.files": count(os.path.join(USER_DATA, "uploads", "templates", "**")),
    "routing_policies.files": count(os.path.join(USER_DATA, "data", "routing_policies", "**")),
    "mods.files": count(os.path.join(USER_DATA, "mods", "**")),
    "models.files": count(os.path.join(USER_DATA, "models", "**")),
    "backups.files": count(os.path.join(USER_DATA, "backups", "*.db")),
}
backups = sorted(glob.glob(os.path.join(USER_DATA, "backups", "*.db")), key=os.path.getmtime)
digest["backups.latest"] = os.path.basename(backups[-1]) if backups else None
# DB 内容级校验（sqlite3 可用时）：关键表行数
try:
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    for t in ("templates", "sales_orders", "manufacturing_orders", "customers", "users"):
        try:
            digest[f"rows.{t}"] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        except Exception as e:
            digest[f"rows.{t}"] = f"ERR:{type(e).__name__}"
    con.close()
except Exception as e:
    digest["sqlite"] = f"ERR:{type(e).__name__}"

json.dump(digest, open(OUT, "w"), indent=2, ensure_ascii=False)
print(json.dumps(digest, indent=2, ensure_ascii=False))
