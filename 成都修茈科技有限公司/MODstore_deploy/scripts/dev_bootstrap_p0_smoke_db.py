"""
一次性开发库修补：插入最小 employee_pack（与现有员工节点 emp-node-001 对齐），
并将 workflow_id=1 修成 start -> employee -> end 可执行图。

仅用于本地 modstore.db；勿在生产库运行。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    db = root / "modstore_server" / "modstore.db"
    c = sqlite3.connect(str(db))
    cur = c.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO catalog_items
        (pkg_id, version, name, description, price, author_id, artifact, industry, stored_filename, sha256, is_public)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "emp-node-001",
            "1.0.0",
            "P0 smoke employee_pack",
            "dev bootstrap for p0_api_smoke",
            0.0,
            1,
            "employee_pack",
            "通用",
            "",
            "",
            1,
        ),
    )

    wid = 1
    cur.execute("DELETE FROM workflow_edges WHERE workflow_id=?", (wid,))
    cur.execute("DELETE FROM workflow_nodes WHERE workflow_id=?", (wid,))

    emp_cfg = {
        "employee_id": "emp-node-001",
        "task": "smoke",
        "input_mapping": {"message": "from workflow"},
    }
    cur.execute(
        """
        INSERT INTO workflow_nodes (workflow_id, node_type, name, config, position_x, position_y)
        VALUES (?, 'start', 'start', '{}', 0, 0)
        """,
        (wid,),
    )
    sid = int(cur.execute("SELECT last_insert_rowid()").fetchone()[0])
    cur.execute(
        """
        INSERT INTO workflow_nodes (workflow_id, node_type, name, config, position_x, position_y)
        VALUES (?, 'employee', 'emp', ?, 0, 0)
        """,
        (wid, json.dumps(emp_cfg, ensure_ascii=False)),
    )
    eid = int(cur.execute("SELECT last_insert_rowid()").fetchone()[0])
    cur.execute(
        """
        INSERT INTO workflow_nodes (workflow_id, node_type, name, config, position_x, position_y)
        VALUES (?, 'end', 'end', '{}', 0, 0)
        """,
        (wid,),
    )
    nid = int(cur.execute("SELECT last_insert_rowid()").fetchone()[0])

    cur.execute(
        "INSERT INTO workflow_edges (workflow_id, source_node_id, target_node_id, condition) VALUES (?,?,?,?)",
        (wid, sid, eid, ""),
    )
    cur.execute(
        "INSERT INTO workflow_edges (workflow_id, source_node_id, target_node_id, condition) VALUES (?,?,?,?)",
        (wid, eid, nid, ""),
    )

    cur.execute(
        "UPDATE workflows SET is_active=1, name=? WHERE id=?",
        ("p0-smoke-linear", wid),
    )

    c.commit()
    c.close()
    print("ok:", db, "workflow", wid, "nodes", sid, eid, nid)


if __name__ == "__main__":
    main()
