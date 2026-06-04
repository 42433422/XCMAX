#!/usr/bin/env python3
"""生成 SYNTHETIC/SEED 月报证据（T56）— 非生产数据。

写入：
  - metrics/ai-evidence-seed.db（SQLite 种子库）
  - metrics/ai-evidence-YYYYMM.json
  - 更新 docs/AI_BUSINESS_EVIDENCE.md 中对应月份表格
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "metrics"
DOC = ROOT / "docs" / "AI_BUSINESS_EVIDENCE.md"
SEED_DB = METRICS / "ai-evidence-seed.db"

MONTH = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("%Y-%m")
YEAR, MON = map(int, MONTH.split("-"))
MONTH_START = datetime(YEAR, MON, 1, tzinfo=timezone.utc)
if MON == 12:
    MONTH_END = datetime(YEAR + 1, 1, 1, tzinfo=timezone.utc)
else:
    MONTH_END = datetime(YEAR, MON + 1, 1, tzinfo=timezone.utc)

RNG = random.Random(20260604)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS shipment_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            decision TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contract_expiry_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheduled_at TEXT NOT NULL,
            push_status TEXT NOT NULL
        );
        """
    )
    conn.execute("DELETE FROM shipment_audit_events")
    conn.execute("DELETE FROM contract_expiry_notifications")

    decisions = ["auto_approve"] * 72 + ["manual"] * 23 + ["ocr_failed"] * 5
    RNG.shuffle(decisions)
    for i, decision in enumerate(decisions):
        day = RNG.randint(1, 28)
        ts = MONTH_START + timedelta(days=day - 1, hours=RNG.randint(8, 18))
        conn.execute(
            "INSERT INTO shipment_audit_events (created_at, decision) VALUES (?, ?)",
            (_iso(ts), decision),
        )

    should_push = 120
    success = 108
    failed = 9
    skipped = 3
    for _ in range(success):
        ts = MONTH_START + timedelta(days=RNG.randint(1, 28), hours=RNG.randint(9, 17))
        conn.execute(
            "INSERT INTO contract_expiry_notifications (scheduled_at, push_status) VALUES (?, 'success')",
            (_iso(ts),),
        )
    for _ in range(failed):
        ts = MONTH_START + timedelta(days=RNG.randint(1, 28), hours=RNG.randint(9, 17))
        conn.execute(
            "INSERT INTO contract_expiry_notifications (scheduled_at, push_status) VALUES (?, 'failed')",
            (_iso(ts),),
        )
    for _ in range(skipped):
        ts = MONTH_START + timedelta(days=RNG.randint(1, 28), hours=RNG.randint(9, 17))
        conn.execute(
            "INSERT INTO contract_expiry_notifications (scheduled_at, push_status) VALUES (?, 'skipped')",
            (_iso(ts),),
        )
    conn.commit()


def collect_shipment(conn: sqlite3.Connection) -> dict:
    cur = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN decision = 'auto_approve' THEN 1 ELSE 0 END) AS auto_approve,
          SUM(CASE WHEN decision = 'manual' THEN 1 ELSE 0 END) AS manual,
          SUM(CASE WHEN decision = 'ocr_failed' THEN 1 ELSE 0 END) AS ocr_failed
        FROM shipment_audit_events
        WHERE created_at >= ? AND created_at < ?
        """,
        (_iso(MONTH_START), _iso(MONTH_END)),
    )
    row = cur.fetchone()
    total, auto, manual, ocr_failed = row
    hit = round(100.0 * auto / max(auto + manual, 1), 1)
    return {
        "total": total,
        "auto_approve": auto,
        "manual": manual,
        "ocr_failed": ocr_failed,
        "ai_hit_rate_pct": hit,
    }


def collect_contract(conn: sqlite3.Connection) -> dict:
    cur = conn.execute(
        """
        SELECT
          COUNT(*) AS should_push,
          SUM(CASE WHEN push_status = 'success' THEN 1 ELSE 0 END) AS push_success,
          SUM(CASE WHEN push_status IN ('failed', 'skipped') THEN 1 ELSE 0 END) AS push_failed
        FROM contract_expiry_notifications
        WHERE scheduled_at >= ? AND scheduled_at < ?
        """,
        (_iso(MONTH_START), _iso(MONTH_END)),
    )
    row = cur.fetchone()
    should_push, success, failed = row
    reach = round(100.0 * success / max(should_push, 1), 1)
    return {
        "contracts_due_30d": 95,
        "should_push": should_push,
        "push_success": success,
        "push_failed": failed,
        "reach_rate_pct": reach,
    }


def write_json(payload: dict) -> Path:
    METRICS.mkdir(parents=True, exist_ok=True)
    out = METRICS / f"ai-evidence-{MONTH.replace('-', '')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def patch_markdown(payload: dict) -> None:
    text = DOC.read_text(encoding="utf-8")
    s1 = payload["scenarios"]["shipment_audit"]
    s2 = payload["scenarios"]["contract_reminder"]

    block1 = f"""## 月报 — 场景 1：发货单自动审（**SYNTHETIC/SEED**）

**统计月份**：`{MONTH}`  
**环境**：`seed-sqlite`（[`metrics/ai-evidence-seed.db`](../../metrics/ai-evidence-seed.db)）  
**数据性质**：**非生产** — 由 [`scripts/ai_evidence/seed_synthetic_evidence.py`](../../scripts/ai_evidence/seed_synthetic_evidence.py) 生成

| 指标 | 数值 | 说明 |
|------|------|------|
| 处理总量 | {s1['total']} | 进入审单流水线的发货单数 |
| AI 自动通过 | {s1['auto_approve']} | `decision=auto_approve` |
| 转人工 | {s1['manual']} | `decision=manual` |
| **AI 命中率** | **{s1['ai_hit_rate_pct']}%** | `auto_approve / (auto_approve + manual)` |
| OCR 失败放弃 | {s1['ocr_failed']} | 无法解析 |

**结论**：种子数据 AI 命中率 {s1['ai_hit_rate_pct']}%（目标 ≥70%）；待 staging 真实月报替换。

---

## 月报 — 场景 2：合同到期提醒（**SYNTHETIC/SEED**）

**统计月份**：`{MONTH}`  
**环境**：`seed-sqlite`（同上种子库）  
**数据性质**：**非生产**

| 指标 | 数值 | 说明 |
|------|------|------|
| 到期前 30 天合同数 | {s2['contracts_due_30d']} | 符合条件合同（种子常量） |
| 应推送任务数 | {s2['should_push']} | 调度生成 |
| 推送成功 | {s2['push_success']} | 企微 API 2xx |
| 推送失败 / 跳过 | {s2['push_failed']} | 含用户拒收 |
| **触达率** | **{s2['reach_rate_pct']}%** | `成功 / 应推送` |

**结论**：种子数据触达率 {s2['reach_rate_pct']}%（目标 ≥90%）；待 staging 真实月报替换。

---

## 月报模板 — 场景 1：发货单自动审"""

    marker = "## 月报模板 — 场景 1：发货单自动审"
    if marker not in text:
        raise SystemExit(f"marker not found in {DOC}")
    before, after = text.split(marker, 1)
    # 去掉旧 SYNTHETIC 块（若存在）
    if "## 月报 — 场景 1" in before:
        idx = before.index("## 月报 — 场景 1")
        before = before[:idx]
    text = before.rstrip() + "\n\n---\n\n" + block1 + after

    old_row = "| 2026-06 | 模板 | 模板 | 脚手架；数据待 T56 |"
    new_row = f"| {MONTH} | SYNTHETIC {s1['ai_hit_rate_pct']}% | SYNTHETIC {s2['reach_rate_pct']}% | seed-sqlite；非生产 |"
    text = text.replace(old_row, new_row) if old_row in text else text

    status_line = "> **状态（2026-06）**：两场景月报**模板**"
    if status_line in text:
        text = text.replace(
            status_line,
            f"> **状态（2026-06）**：已写入 **SYNTHETIC/SEED** 月报（{MONTH}）；生产/staging 真实数据仍待 T56 复核",
            1,
        )

    DOC.write_text(text, encoding="utf-8")


def main() -> None:
    METRICS.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SEED_DB)
    try:
        seed_db(conn)
        shipment = collect_shipment(conn)
        contract = collect_contract(conn)
    finally:
        conn.close()

    payload = {
        "month": MONTH,
        "data_class": "SYNTHETIC/SEED",
        "source": str(SEED_DB.relative_to(ROOT)),
        "generated_at": _iso(datetime.now(timezone.utc)),
        "scenarios": {
            "shipment_audit": shipment,
            "contract_reminder": contract,
        },
    }
    out = write_json(payload)
    patch_markdown(payload)
    print(f"Wrote {SEED_DB}")
    print(f"Wrote {out}")
    print(f"Updated {DOC}")


if __name__ == "__main__":
    main()
