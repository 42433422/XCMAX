#!/usr/bin/env python3
"""把 Mac 日更主跑库的 daily_digest_records 同步到公网 CVM Postgres。

背景：公网 ``MODSTORE_DAILY_DIGEST_ENABLED=0`` + ``AUTOMATION_PRIMARY=local_mac``，
摘要只落在本机 runtime SQLite；管理端读的是公网 ``/api/xcmax/admin/daily-digests``，
不同步则存档停在旧日期（例如 2026-06-10）。

用法：
  python3 FHD/scripts/dev/sync_daily_digests_to_prod.py
  MODSTORE_DIGEST_SYNC_SINCE=2026-06-11 python3 FHD/scripts/dev/sync_daily_digests_to_prod.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from app.utils.operational_errors import BOUNDARY_ERRORS

HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
USER = os.environ.get("XCMAX_REMOTE_USER", "root")
SINCE = (os.environ.get("MODSTORE_DIGEST_SYNC_SINCE") or "2026-06-11").strip()
DEFAULT_DB = Path.home() / "Library/Application Support/XCMAX/modstore-daily/modstore.db"
DB_PATH = Path(
    os.environ.get("MODSTORE_RUNTIME_DB_PATH") or os.environ.get("MODSTORE_DB_PATH") or DEFAULT_DB
)

COLUMNS = [
    "day",
    "subject",
    "body_html",
    "body_text",
    "meeting_minutes_html",
    "recipients_json",
    "delivery_json",
    "delivered",
    "source",
    "created_at",
    "vibe_prep_updates_md",
    "vibe_prep_patches_md",
    "vibe_prep_meta_json",
    "vibe_prep_pw_md",
    "vibe_prep_ps_md",
    "vibe_prep_app_md",
    "vibe_prep_sr_md",
    "vibe_prep_line_dispatch_json",
    "vibe_line_execute_json",
    "release_train_before",
    "release_train_after",
    "release_kind",
]


def _export_rows() -> list[dict]:
    if not DB_PATH.is_file():
        raise SystemExit(f"local digest db missing: {DB_PATH}")
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    # 每天取最新一条；排除本地校验假日
    sql = """
    SELECT t.*
    FROM daily_digest_records t
    INNER JOIN (
      SELECT day, MAX(id) AS mid
      FROM daily_digest_records
      WHERE day >= ?
        AND day GLOB '????-??-??'
        AND day NOT LIKE 'local%'
      GROUP BY day
    ) x ON t.id = x.mid
    ORDER BY t.day ASC
    """
    rows = []
    for r in con.execute(sql, (SINCE,)):
        item = {c: r[c] if c in r.keys() else "" for c in COLUMNS}
        item["delivered"] = bool(item.get("delivered"))
        for c in COLUMNS:
            if item.get(c) is None:
                item[c] = "" if c != "delivered" else False
        rows.append(item)
    con.close()
    return rows


REMOTE_IMPORT = r"""
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
rows = payload.get('rows') or []
import psycopg2
conn = psycopg2.connect(
    host='127.0.0.1', port=5433, user='modstore', password='modstore', dbname='modstore'
)
cols = payload['columns']
inserted = updated = skipped = 0
with conn, conn.cursor() as cur:
    for row in rows:
        day = row['day']
        cur.execute('SELECT id FROM daily_digest_records WHERE day=%s ORDER BY id DESC LIMIT 1', (day,))
        existing = cur.fetchone()
        values = [row.get(c) for c in cols]
        if existing:
            # 已有该日：仅当本地 created_at 更新或正文更长时覆盖
            cur.execute(
                "SELECT created_at, length(coalesce(body_html,'')) "
                "FROM daily_digest_records WHERE id=%s",
                (existing[0],),
            )
            old_created, old_len = cur.fetchone()
            new_created = row.get('created_at') or ''
            new_len = len(row.get('body_html') or '')
            if str(new_created) <= str(old_created or '') and new_len <= int(old_len or 0):
                skipped += 1
                continue
            sets = ', '.join(f'{c}=%s' for c in cols if c != 'day')
            cur.execute(
                f'UPDATE daily_digest_records SET {sets} WHERE id=%s',
                [row.get(c) for c in cols if c != 'day'] + [existing[0]],
            )
            updated += 1
        else:
            placeholders = ', '.join(['%s'] * len(cols))
            col_sql = ', '.join(cols)
            cur.execute(
                f'INSERT INTO daily_digest_records ({col_sql}) VALUES ({placeholders})',
                values,
            )
            inserted += 1
conn.close()
print(json.dumps({'ok': True, 'inserted': inserted, 'updated': updated, 'skipped': skipped, 'total': len(rows)}))
"""


def main() -> int:
    rows = _export_rows()
    print(f"[digest-sync] source={DB_PATH} since={SINCE} rows={len(rows)}")
    if not rows:
        print("[digest-sync] nothing to sync")
        return 0
    print(
        "[digest-sync] range",
        rows[0]["day"],
        "→",
        rows[-1]["day"],
    )
    with tempfile.TemporaryDirectory(prefix="digest-sync-") as tmp:
        local_json = Path(tmp) / "digests.json"
        remote_json = f"/tmp/daily_digest_sync_{os.getpid()}.json"
        remote_py = f"/tmp/daily_digest_sync_{os.getpid()}.py"
        local_json.write_text(
            json.dumps({"columns": COLUMNS, "rows": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", f"{USER}@{HOST}"]
        scp = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
        subprocess.check_call([*scp, str(local_json), f"{USER}@{HOST}:{remote_json}"])
        Path(tmp, "import.py").write_text(REMOTE_IMPORT, encoding="utf-8")
        subprocess.check_call([*scp, str(Path(tmp, "import.py")), f"{USER}@{HOST}:{remote_py}"])
        remote_python = (
            os.environ.get("MODSTORE_REMOTE_PYTHON")
            or "/opt/xcmax/current/成都修茈科技有限公司/MODstore_deploy/.venv/bin/python"
        )
        out = subprocess.check_output(
            [
                *ssh,
                f"{remote_python} {remote_py} {remote_json}; rm -f {remote_py} {remote_json}",
            ],
            text=True,
        )
        print("[digest-sync] remote:", out.strip())
    # verify public API
    try:
        import urllib.request

        with urllib.request.urlopen(
            "https://xiu-ci.com/api/xcmax/admin/daily-digests?limit=5", timeout=30
        ) as resp:
            data = json.loads(resp.read().decode())
        top = [(r.get("id"), r.get("day")) for r in (data.get("data") or [])[:5]]
        print("[digest-sync] public top:", data.get("total"), top)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        print("[digest-sync] public verify skipped:", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
