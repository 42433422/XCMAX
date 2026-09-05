"""考勤人员、部门与逐日记录管理；数据留在考勤模块私有库。"""

import sqlite3
from contextlib import closing

from fastapi.responses import JSONResponse


def _connect_for_write(db_path):
    """首次录入建表，不覆盖已交付名单或历史记录。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS attendance_employees ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
            "employee_name TEXT NOT NULL, department TEXT NOT NULL DEFAULT '', "
            "main_department TEXT NOT NULL DEFAULT '', attendance_group TEXT NOT NULL DEFAULT '', "
            "employee_no TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '', "
            "user_id TEXT NOT NULL DEFAULT '', UNIQUE(source_file, employee_name, department))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS attendance_departments ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
            "department TEXT NOT NULL, main_department TEXT NOT NULL DEFAULT '', "
            "attendance_group TEXT NOT NULL DEFAULT '', UNIQUE(source_file, department, attendance_group))"
        )
        conn.execute("BEGIN IMMEDIATE")
        return conn
    except sqlite3.Error:
        conn.close()
        raise


def _has_table(db_path, table):
    if not db_path.is_file():
        return False
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            is not None
        )


def _check_employee_duplicate(conn, fields, employee_id=0):
    if conn.execute(
        "SELECT 1 FROM attendance_employees WHERE employee_name = ? AND department = ? AND id <> ?",
        (fields[0], fields[1], employee_id),
    ).fetchone():
        raise sqlite3.IntegrityError("duplicate personnel")


def _check_department_duplicate(conn, department, department_id=0):
    if conn.execute(
        "SELECT 1 FROM attendance_departments WHERE department = ? AND id <> ?",
        (department, department_id),
    ).fetchone():
        raise sqlite3.IntegrityError("duplicate department")


def register(router, *, logger, get_database_path) -> None:
    @router.get("/employees", response_model=None)
    async def list_employees(page: int = 1, page_size: int = 50, search: str = ""):
        import sqlite3

        page = max(1, int(page or 1))
        page_size = min(500, max(1, int(page_size or 50)))
        db_path = get_database_path()
        if not _has_table(db_path, "attendance_employees"):
            return {
                "success": True,
                "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
            }
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        like = f"%{(search or '').strip()}%"
        try:
            cur.execute(
                "SELECT COUNT(*) FROM attendance_employees "
                "WHERE employee_name LIKE ? OR department LIKE ? OR employee_no LIKE ? "
                "OR position LIKE ? OR user_id LIKE ?",
                (like, like, like, like, like),
            )
            total = int(cur.fetchone()[0] or 0)
            offset = (page - 1) * page_size
            cur.execute(
                "SELECT id, employee_name, department, main_department, attendance_group, employee_no, position, user_id "
                "FROM attendance_employees WHERE employee_name LIKE ? OR department LIKE ? OR employee_no LIKE ? "
                "OR position LIKE ? OR user_id LIKE ? ORDER BY id LIMIT ? OFFSET ?",
                (like, like, like, like, like, page_size, offset),
            )
            items = [dict(r) for r in cur.fetchall()]
            return {
                "success": True,
                "data": {"items": items, "total": total, "page": page, "page_size": page_size},
            }
        except sqlite3.Error:
            logger.exception("读取人员管理失败")
            return JSONResponse(
                {"success": False, "message": "读取人员管理失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.post("/employees", response_model=None)
    async def create_employee(body: dict):
        import sqlite3

        payload = body if isinstance(body, dict) else {}
        employee_name = str(payload.get("employee_name") or "").strip()
        if not employee_name:
            return JSONResponse(
                {"success": False, "message": "姓名不能为空"},
                status_code=400,
            )
        fields = {
            "employee_name": employee_name,
            "department": str(payload.get("department") or "").strip(),
            "main_department": str(payload.get("main_department") or "").strip(),
            "attendance_group": str(payload.get("attendance_group") or "").strip(),
            "employee_no": str(payload.get("employee_no") or "").strip(),
            "position": str(payload.get("position") or "").strip(),
            "user_id": str(payload.get("user_id") or "").strip(),
        }
        db_path = get_database_path()
        conn = _connect_for_write(db_path)
        try:
            _check_employee_duplicate(conn, list(fields.values()))
            cur = conn.execute(
                "INSERT INTO attendance_employees "
                "(source_file, employee_name, department, main_department, attendance_group, employee_no, position, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("manual", *fields.values()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, employee_name, department, main_department, attendance_group, employee_no, position, user_id "
                "FROM attendance_employees WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            return {"success": True, "data": dict(row) if row else {"id": cur.lastrowid, **fields}}
        except sqlite3.IntegrityError:
            conn.rollback()
            return JSONResponse(
                {"success": False, "message": "该人员已存在，请勿重复添加"},
                status_code=409,
            )
        except sqlite3.Error:
            conn.rollback()
            logger.exception("新增人员失败")
            return JSONResponse(
                {"success": False, "message": "新增人员失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.put("/employees/{employee_id}", response_model=None)
    async def update_employee(employee_id: int, body: dict):
        import sqlite3

        payload = body if isinstance(body, dict) else {}
        employee_name = str(payload.get("employee_name") or "").strip()
        if not employee_name:
            return JSONResponse(
                {"success": False, "message": "姓名不能为空"},
                status_code=400,
            )
        fields = (
            employee_name,
            str(payload.get("department") or "").strip(),
            str(payload.get("main_department") or "").strip(),
            str(payload.get("attendance_group") or "").strip(),
            str(payload.get("employee_no") or "").strip(),
            str(payload.get("position") or "").strip(),
            str(payload.get("user_id") or "").strip(),
        )
        conn = _connect_for_write(get_database_path())
        try:
            _check_employee_duplicate(conn, fields, employee_id)
            cur = conn.execute(
                "UPDATE attendance_employees SET employee_name = ?, department = ?, main_department = ?, "
                "attendance_group = ?, employee_no = ?, position = ?, user_id = ? WHERE id = ?",
                (*fields, employee_id),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return JSONResponse(
                    {"success": False, "message": "人员不存在"},
                    status_code=404,
                )
            conn.commit()
            row = conn.execute(
                "SELECT id, employee_name, department, main_department, attendance_group, employee_no, position, user_id "
                "FROM attendance_employees WHERE id = ?",
                (employee_id,),
            ).fetchone()
            return {"success": True, "data": dict(row) if row else None}
        except sqlite3.IntegrityError:
            conn.rollback()
            return JSONResponse(
                {"success": False, "message": "人员信息与现有记录重复"},
                status_code=409,
            )
        except sqlite3.Error:
            conn.rollback()
            logger.exception("更新人员失败")
            return JSONResponse(
                {"success": False, "message": "更新人员失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.delete("/employees/{employee_id}", response_model=None)
    async def delete_employee(employee_id: int):
        import sqlite3

        conn = _connect_for_write(get_database_path())
        try:
            cur = conn.execute("DELETE FROM attendance_employees WHERE id = ?", (employee_id,))
            if cur.rowcount == 0:
                conn.rollback()
                return JSONResponse(
                    {"success": False, "message": "人员不存在"},
                    status_code=404,
                )
            conn.commit()
            return {"success": True, "data": {"id": employee_id}}
        except sqlite3.Error:
            conn.rollback()
            logger.exception("删除人员失败")
            return JSONResponse(
                {"success": False, "message": "删除人员失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.get("/departments", response_model=None)
    async def list_departments(page: int = 1, page_size: int = 50, search: str = ""):
        import sqlite3

        page = max(1, int(page or 1))
        page_size = min(500, max(1, int(page_size or 50)))
        db_path = get_database_path()
        if not _has_table(db_path, "attendance_departments"):
            return {
                "success": True,
                "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
            }
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        like = f"%{(search or '').strip()}%"
        try:
            cur.execute(
                "SELECT COUNT(*) FROM attendance_departments "
                "WHERE department LIKE ? OR main_department LIKE ? OR attendance_group LIKE ?",
                (like, like, like),
            )
            total = int(cur.fetchone()[0] or 0)
            offset = (page - 1) * page_size
            cur.execute(
                "SELECT d.id, d.department, d.main_department, d.attendance_group, "
                "(SELECT COUNT(*) FROM attendance_employees e WHERE e.department = d.department) AS employee_count "
                "FROM attendance_departments d WHERE d.department LIKE ? OR d.main_department LIKE ? "
                "OR d.attendance_group LIKE ? ORDER BY d.id LIMIT ? OFFSET ?",
                (like, like, like, page_size, offset),
            )
            items = [dict(r) for r in cur.fetchall()]
            return {
                "success": True,
                "data": {"items": items, "total": total, "page": page, "page_size": page_size},
            }
        except sqlite3.Error:
            logger.exception("读取部门管理失败")
            return JSONResponse(
                {"success": False, "message": "读取部门管理失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.post("/departments", response_model=None)
    async def create_department(body: dict):
        import sqlite3

        payload = body if isinstance(body, dict) else {}
        department = str(payload.get("department") or "").strip()
        if not department:
            return JSONResponse(
                {"success": False, "message": "部门名称不能为空"},
                status_code=400,
            )
        fields = {
            "department": department,
            "main_department": str(payload.get("main_department") or department).strip(),
            "attendance_group": str(payload.get("attendance_group") or "").strip(),
        }
        db_path = get_database_path()
        conn = _connect_for_write(db_path)
        try:
            _check_department_duplicate(conn, department)
            cur = conn.execute(
                "INSERT INTO attendance_departments (source_file, department, main_department, attendance_group) "
                "VALUES (?, ?, ?, ?)",
                ("manual", *fields.values()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, department, main_department, attendance_group FROM attendance_departments WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            data = dict(row) if row else {"id": cur.lastrowid, **fields}
            data["employee_count"] = 0
            return {"success": True, "data": data}
        except sqlite3.IntegrityError:
            conn.rollback()
            return JSONResponse(
                {"success": False, "message": "该部门已存在，请勿重复添加"},
                status_code=409,
            )
        except sqlite3.Error:
            conn.rollback()
            logger.exception("新增部门失败")
            return JSONResponse(
                {"success": False, "message": "新增部门失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.put("/departments/{department_id}", response_model=None)
    async def update_department(department_id: int, body: dict):
        import sqlite3

        payload = body if isinstance(body, dict) else {}
        department = str(payload.get("department") or "").strip()
        if not department:
            return JSONResponse(
                {"success": False, "message": "部门名称不能为空"},
                status_code=400,
            )
        main_department = str(payload.get("main_department") or department).strip()
        attendance_group = str(payload.get("attendance_group") or "").strip()
        conn = _connect_for_write(get_database_path())
        try:
            _check_department_duplicate(conn, department, department_id)
            previous = conn.execute(
                "SELECT department FROM attendance_departments WHERE id = ?",
                (department_id,),
            ).fetchone()
            if previous is None:
                return JSONResponse(
                    {"success": False, "message": "部门不存在"},
                    status_code=404,
                )
            old_department = str(previous["department"] or "")
            conn.execute(
                "UPDATE attendance_departments SET department = ?, main_department = ?, attendance_group = ? WHERE id = ?",
                (department, main_department, attendance_group, department_id),
            )
            if old_department != department:
                conn.execute(
                    "UPDATE attendance_employees SET department = ?, "
                    "main_department = CASE WHEN main_department = ? THEN ? ELSE main_department END "
                    "WHERE department = ?",
                    (department, old_department, main_department, old_department),
                )
            conn.commit()
            row = conn.execute(
                "SELECT d.id, d.department, d.main_department, d.attendance_group, "
                "(SELECT COUNT(*) FROM attendance_employees e WHERE e.department = d.department) AS employee_count "
                "FROM attendance_departments d WHERE d.id = ?",
                (department_id,),
            ).fetchone()
            return {"success": True, "data": dict(row) if row else None}
        except sqlite3.IntegrityError:
            conn.rollback()
            return JSONResponse(
                {"success": False, "message": "部门信息与现有记录重复"},
                status_code=409,
            )
        except sqlite3.Error:
            conn.rollback()
            logger.exception("更新部门失败")
            return JSONResponse(
                {"success": False, "message": "更新部门失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.delete("/departments/{department_id}", response_model=None)
    async def delete_department(department_id: int):
        import sqlite3

        conn = _connect_for_write(get_database_path())
        try:
            row = conn.execute(
                "SELECT department FROM attendance_departments WHERE id = ?",
                (department_id,),
            ).fetchone()
            if row is None:
                return JSONResponse(
                    {"success": False, "message": "部门不存在"},
                    status_code=404,
                )
            department = str(row["department"] or "")
            employee_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM attendance_employees WHERE department = ?",
                    (department,),
                ).fetchone()[0]
                or 0
            )
            if employee_count:
                return JSONResponse(
                    {
                        "success": False,
                        "message": f"该部门仍有 {employee_count} 名人员，请先调整人员所属部门",
                    },
                    status_code=409,
                )
            conn.execute("DELETE FROM attendance_departments WHERE id = ?", (department_id,))
            conn.commit()
            return {"success": True, "data": {"id": department_id}}
        except sqlite3.Error:
            conn.rollback()
            logger.exception("删除部门失败")
            return JSONResponse(
                {"success": False, "message": "删除部门失败"},
                status_code=500,
            )
        finally:
            conn.close()

    @router.get("/records", response_model=None)
    async def list_attendance_records(
        page: int = 1,
        page_size: int = 50,
        search: str = "",
        month: str = "",
    ):
        import sqlite3

        page = max(1, int(page or 1))
        page_size = min(500, max(1, int(page_size or 50)))
        db_path = get_database_path()
        if not db_path.exists():
            return {
                "success": True,
                "data": {
                    "items": [],
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "months": [],
                },
            }
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attendance_daily_records'"
            ).fetchone()
            if exists is None:
                return {
                    "success": True,
                    "data": {
                        "items": [],
                        "total": 0,
                        "page": page,
                        "page_size": page_size,
                        "months": [],
                    },
                }
            like = f"%{(search or '').strip()}%"
            month_value = (month or "").strip()
            where = (
                "(employee_name LIKE ? OR department LIKE ? OR employee_no LIKE ? OR shift_name LIKE ?) "
                "AND (? = '' OR month_label = ?)"
            )
            params = (like, like, like, like, month_value, month_value)
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM attendance_daily_records WHERE {where}",
                    params,
                ).fetchone()[0]
                or 0
            )
            rows = conn.execute(
                "SELECT id, month_label, employee_name, attendance_group, department, employee_no, position, "
                "work_date, shift_name, leave_hours, absent_days, late_count_hint, early_count_hint, "
                f"missing_card_count, imported_at FROM attendance_daily_records WHERE {where} "
                "ORDER BY work_date DESC, id DESC LIMIT ? OFFSET ?",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
            months = [
                str(row[0])
                for row in conn.execute(
                    "SELECT DISTINCT month_label FROM attendance_daily_records "
                    "WHERE TRIM(month_label) <> '' ORDER BY month_label DESC"
                ).fetchall()
            ]
            return {
                "success": True,
                "data": {
                    "items": [dict(row) for row in rows],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "months": months,
                },
            }
        except sqlite3.Error:
            logger.exception("读取考勤记录失败")
            return JSONResponse(
                {"success": False, "message": "读取考勤记录失败"},
                status_code=500,
            )
        finally:
            conn.close()
