"""太阳鸟 PRO — 人员/产品管理 FastAPI 路由（自 blueprints.py 拆出，行为零变更）。"""

from __future__ import annotations

from fastapi.responses import JSONResponse


def register(router, *, get_database_path) -> None:
    """在给定 router 上注册 /products/* 路由。"""

    @router.get("/products/list", response_model=None)
    async def products_list(
        page: int = 1,
        per_page: int = 20,
        keyword: str = "",
        unit: str = "",
    ):
        import sqlite3

        db_path = get_database_path()
        if not db_path.exists():
            return {"success": True, "data": [], "total": 0}
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cond = []
        args = []
        if keyword:
            cond.append("(model_number LIKE ? OR name LIKE ?)")
            args.extend([f"%{keyword}%", f"%{keyword}%"])
        if unit:
            cond.append("unit = ?")
            args.append(unit)
        where = " AND ".join(cond) if cond else "1=1"
        cur.execute(f"SELECT COUNT(*) FROM products WHERE {where}", args)
        total = cur.fetchone()[0]
        offset = (page - 1) * per_page
        cur.execute(
            f"SELECT id, model_number, name, specification, price, unit "
            f"FROM products WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
            [*args, per_page, offset],
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"success": True, "data": items, "total": total}

    @router.get("/products/{product_id}", response_model=None)
    async def products_get(product_id: int):
        import sqlite3

        db_path = get_database_path()
        if not db_path.exists():
            return JSONResponse({"success": False, "error": "not found"}, status_code=404)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return JSONResponse({"success": False, "error": "not found"}, status_code=404)
        return {"success": True, "data": dict(row)}

    @router.post("/products/add", response_model=None)
    async def products_add(data: dict):
        import datetime
        import sqlite3

        db_path = get_database_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        now = datetime.datetime.now().isoformat()
        cur.execute(
            "INSERT INTO products (source_file, model_number, name, specification, price, unit, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.get("source_file", ""),
                data.get("model_number", ""),
                data.get("name", ""),
                data.get("specification", ""),
                float(data.get("price") or 0),
                data.get("unit", ""),
                now,
                now,
            ),
        )
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        return {"success": True, "data": {"id": new_id}}

    @router.post("/products/update", response_model=None)
    async def products_update(data: dict):
        import datetime
        import sqlite3

        db_path = get_database_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        now = datetime.datetime.now().isoformat()
        cur.execute(
            "UPDATE products SET model_number=?, name=?, specification=?, price=?, unit=?, updated_at=? WHERE id=?",
            (
                data.get("model_number", ""),
                data.get("name", ""),
                data.get("specification", ""),
                float(data.get("price") or 0),
                data.get("unit", ""),
                now,
                data.get("id"),
            ),
        )
        conn.commit()
        conn.close()
        return {"success": True}

    @router.post("/products/delete", response_model=None)
    async def products_delete(data: dict):
        import sqlite3

        db_path = get_database_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id = ?", (data.get("id"),))
        conn.commit()
        conn.close()
        return {"success": True}

    @router.post("/products/batch-delete", response_model=None)
    async def products_batch_delete(data: dict):
        import sqlite3

        ids = data.get("ids") or []
        if not ids:
            return {"success": True}
        db_path = get_database_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        placeholders = ",".join("?" * len(ids))
        cur.execute(f"DELETE FROM products WHERE id IN ({placeholders})", ids)
        conn.commit()
        conn.close()
        return {"success": True}

    @router.get("/products/product_names", response_model=None)
    async def products_names():
        import sqlite3

        db_path = get_database_path()
        if not db_path.exists():
            return {"success": True, "data": []}
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, model_number, name FROM products ORDER BY id")
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"success": True, "data": items}

    @router.get("/products/product_names/search", response_model=None)
    async def products_names_search(keyword: str = ""):
        import sqlite3

        db_path = get_database_path()
        if not db_path.exists():
            return {"success": True, "data": []}
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, model_number, name FROM products WHERE model_number LIKE ? OR name LIKE ? LIMIT 20",
            (f"%{keyword}%", f"%{keyword}%"),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"success": True, "data": items}

    @router.post("/products/batch", response_model=None)
    async def products_batch_add(data: dict):
        import datetime
        import sqlite3

        products_list = data.get("products") or []
        if not products_list:
            return {"success": True, "data": []}
        db_path = get_database_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        now = datetime.datetime.now().isoformat()
        rows = []
        for p in products_list:
            rows.append(
                (
                    "",
                    p.get("model_number", ""),
                    p.get("name", ""),
                    p.get("specification", ""),
                    float(p.get("price") or 0),
                    p.get("unit", ""),
                    now,
                    now,
                )
            )
        cur.executemany(
            "INSERT INTO products (source_file, model_number, name, specification, price, unit, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()
        return {"success": True, "data": []}
