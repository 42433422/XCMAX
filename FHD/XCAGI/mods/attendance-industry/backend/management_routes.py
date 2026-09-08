"""考勤人员、部门与逐日记录管理；数据留在考勤模块私有库，按登录账号隔离。

隔离语义（fail-closed）：
- 读：仅返回 ``owner_user_id == 当前登录账号`` 的行；未登录 → 空结果。
- 写：新行归属当前登录账号；未登录 → 401。
- 改/删：目标行不属于当前账号 → 404（不泄露存在性）。
- 历史存量：首次访问幂等迁移，旧行归属太阳鸟交付账号。
"""

import sqlite3
from contextlib import closing

from fastapi import Request
from fastapi.responses import JSONResponse

try:
    from .owner_scope import migrate_owner_column, owner_from_request
except ImportError:  # mod_manager 以顶层模块名加载 backend/*.py
    from owner_scope import migrate_owner_column, owner_from_request


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"success": False, "message": "请先登录后再管理考勤数据"},
        status_code=401,
    )


def _connect_for_write(db_path):
    """首次录入建表（含 owner_user_id），不覆盖已交付名单或历史记录。

    新库唯一约束包含 owner_user_id：不同账号可维护同名人员/部门。
    旧库在同一事务内重建唯一约束并保留数据及 schema 对象，升级后也按账号判重。
    """
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
            "user_id TEXT NOT NULL DEFAULT '', owner_user_id TEXT NOT NULL DEFAULT '', "
            "UNIQUE(source_file, employee_name, department, owner_user_id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS attendance_departments ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
            "department TEXT NOT NULL, main_department TEXT NOT NULL DEFAULT '', "
            "attendance_group TEXT NOT NULL DEFAULT '', owner_user_id TEXT NOT NULL DEFAULT '', "
            "UNIQUE(source_file, department, attendance_group, owner_user_id))"
        )
        migrate_owner_column(db_path)
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


def _check_employee_duplicate(conn, fields, owner, employee_id=0):
    if conn.execute(
        "SELECT 1 FROM attendance_employees "
        "WHERE employee_name = ? AND department = ? AND owner_user_id = ? AND id <> ?",
        (fields[0], fields[1], owner, employee_id),
    ).fetchone():
        raise sqlite3.IntegrityError("duplicate personnel")


def _check_department_duplicate(conn, department, owner, department_id=0):
    if conn.execute(
        "SELECT 1 FROM attendance_departments "
        "WHERE department = ? AND owner_user_id = ? AND id <> ?",
        (department, owner, department_id),
    ).fetchone():
        raise sqlite3.IntegrityError("duplicate department")


def register(router, *, logger, get_database_path) -> None:
    @router.get("/schedules", response_model=None)
    async def schedules_get(request: Request):
        """共享考勤组资源来自当前账号人员主数据，不读取任何客户模板规则。"""
        owner = owner_from_request(request)
        db_path = get_database_path()
        if not owner:
            return {"success": True, "schedule_groups": [], "lines": []}
        try:
            if not _has_table(db_path, "attendance_employees"):
                return {"success": True, "schedule_groups": [], "lines": []}
            migrate_owner_column(db_path)
            with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as conn:
                groups = conn.execute(
                    "SELECT attendance_group, COUNT(*) FROM attendance_employees "
                    "WHERE TRIM(attendance_group) <> '' AND owner_user_id = ? "
                    "GROUP BY attendance_group ORDER BY attendance_group",
                    (owner,),
                ).fetchall()
            return {
                "success": True,
                "schedule_groups": [
                    {
                        "name": name,
                        "headcount": f"{count} 人",
                        "shift_type": "人员考勤组",
                        "lines": [],
                    }
                    for name, count in groups
                ],
                "lines": [],
            }
        except sqlite3.Error:
            logger.exception("读取排班资源失败")
            return JSONResponse({"success": False, "message": "读取排班资源失败"}, status_code=500)

    @router.get("/employees", response_model=None)
    async def list_employees(
        request: Request, page: int = 1, page_size: int = 50, search: str = ""
    ):
        page = max(1, int(page or 1))
        page_size = min(500, max(1, int(page_size or 50)))
        owner = owner_from_request(request)
        db_path = get_database_path()
        if not owner or not _has_table(db_path, "attendance_employees"):
            return {
                "success": True,
                "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
            }
        migrate_owner_column(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        like = f"%{(search or '').strip()}%"
        try:
            where = (
                "owner_user_id = ? AND (employee_name LIKE ? OR department LIKE ? "
                "OR employee_no LIKE ? OR position LIKE ? OR user_id LIKE ?)"
            )
            params = (owner, like, like, like, like, like)
            cur.execute(f"SELECT COUNT(*) FROM attendance_employees WHERE {where}", params)
            total = int(cur.fetchone()[0] or 0)
            offset = (page - 1) * page_size
            cur.execute(
                "SELECT id, employee_name, department, main_department, attendance_group, employee_no, position, user_id "
                f"FROM attendance_employees WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                (*params, page_size, offset),
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
    async def create_employee(request: Request, body: dict):
        owner = owner_from_request(request)
        if not owner:
            return _unauthorized()
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
            _check_employee_duplicate(conn, list(fields.values()), owner)
            cur = conn.execute(
                "INSERT INTO attendance_employees "
                "(source_file, employee_name, department, main_department, attendance_group, employee_no, position, user_id, owner_user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("manual", *fields.values(), owner),
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
    async def update_employee(request: Request, employee_id: int, body: dict):
        owner = owner_from_request(request)
        if not owner:
            return _unauthorized()
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
            _check_employee_duplicate(conn, fields, owner, employee_id)
            cur = conn.execute(
                "UPDATE attendance_employees SET employee_name = ?, department = ?, main_department = ?, "
                "attendance_group = ?, employee_no = ?, position = ?, user_id = ? "
                "WHERE id = ? AND owner_user_id = ?",
                (*fields, employee_id, owner),
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
    async def delete_employee(request: Request, employee_id: int):
        owner = owner_from_request(request)
        if not owner:
            return _unauthorized()
        conn = _connect_for_write(get_database_path())
        try:
            cur = conn.execute(
                "DELETE FROM attendance_employees WHERE id = ? AND owner_user_id = ?",
                (employee_id, owner),
            )
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
    async def list_departments(
        request: Request, page: int = 1, page_size: int = 50, search: str = ""
    ):
        page = max(1, int(page or 1))
        page_size = min(500, max(1, int(page_size or 50)))
        owner = owner_from_request(request)
        db_path = get_database_path()
        if not owner or not _has_table(db_path, "attendance_departments"):
            return {
                "success": True,
                "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
            }
        migrate_owner_column(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        like = f"%{(search or '').strip()}%"
        try:
            cur.execute(
                "SELECT COUNT(*) FROM attendance_departments "
                "WHERE owner_user_id = ? AND (department LIKE ? OR main_department LIKE ? OR attendance_group LIKE ?)",
                (owner, like, like, like),
            )
            total = int(cur.fetchone()[0] or 0)
            offset = (page - 1) * page_size
            cur.execute(
                "SELECT d.id, d.department, d.main_department, d.attendance_group, "
                "(SELECT COUNT(*) FROM attendance_employees e WHERE e.department = d.department AND e.owner_user_id = d.owner_user_id) AS employee_count "
                "FROM attendance_departments d "
                "WHERE d.owner_user_id = ? AND (d.department LIKE ? OR d.main_department LIKE ? OR d.attendance_group LIKE ?) "
                "ORDER BY d.id LIMIT ? OFFSET ?",
                (owner, like, like, like, page_size, offset),
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
    async def create_department(request: Request, body: dict):
        owner = owner_from_request(request)
        if not owner:
            return _unauthorized()
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
            _check_department_duplicate(conn, department, owner)
            cur = conn.execute(
                "INSERT INTO attendance_departments (source_file, department, main_department, attendance_group, owner_user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                ("manual", *fields.values(), owner),
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
    async def update_department(request: Request, department_id: int, body: dict):
        owner = owner_from_request(request)
        if not owner:
            return _unauthorized()
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
            _check_department_duplicate(conn, department, owner, department_id)
            previous = conn.execute(
                "SELECT department FROM attendance_departments WHERE id = ? AND owner_user_id = ?",
                (department_id, owner),
            ).fetchone()
            if previous is None:
                conn.rollback()
                return JSONResponse(
                    {"success": False, "message": "部门不存在"},
                    status_code=404,
                )
            old_department = str(previous["department"] or "")
            conn.execute(
                "UPDATE attendance_departments SET department = ?, main_department = ?, attendance_group = ? "
                "WHERE id = ? AND owner_user_id = ?",
                (department, main_department, attendance_group, department_id, owner),
            )
            if old_department != department:
                conn.execute(
                    "UPDATE attendance_employees SET department = ?, "
                    "main_department = CASE WHEN main_department = ? THEN ? ELSE main_department END "
                    "WHERE department = ? AND owner_user_id = ?",
                    (department, old_department, main_department, old_department, owner),
                )
            conn.commit()
            row = conn.execute(
                "SELECT d.id, d.department, d.main_department, d.attendance_group, "
                "(SELECT COUNT(*) FROM attendance_employees e WHERE e.department = d.department AND e.owner_user_id = d.owner_user_id) AS employee_count "
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
    async def delete_department(request: Request, department_id: int):
        owner = owner_from_request(request)
        if not owner:
            return _unauthorized()
        conn = _connect_for_write(get_database_path())
        try:
            row = conn.execute(
                "SELECT department FROM attendance_departments WHERE id = ? AND owner_user_id = ?",
                (department_id, owner),
            ).fetchone()
            if row is None:
                conn.rollback()
                return JSONResponse(
                    {"success": False, "message": "部门不存在"},
                    status_code=404,
                )
            department = str(row["department"] or "")
            employee_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM attendance_employees WHERE department = ? AND owner_user_id = ?",
                    (department, owner),
                ).fetchone()[0]
                or 0
            )
            if employee_count:
                conn.rollback()
                return JSONResponse(
                    {
                        "success": False,
                        "message": f"该部门仍有 {employee_count} 名人员，请先调整人员所属部门",
                    },
                    status_code=409,
                )
            conn.execute(
                "DELETE FROM attendance_departments WHERE id = ? AND owner_user_id = ?",
                (department_id, owner),
            )
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
        request: Request,
        page: int = 1,
        page_size: int = 50,
        search: str = "",
        month: str = "",
    ):
        page = max(1, int(page or 1))
        page_size = min(500, max(1, int(page_size or 50)))
        owner = owner_from_request(request)
        db_path = get_database_path()
        empty = {
            "success": True,
            "data": {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "months": [],
            },
        }
        if not owner or not db_path.exists():
            return empty
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attendance_daily_records'"
            ).fetchone()
            if exists is None:
                return empty
            migrate_owner_column(db_path)
            like = f"%{(search or '').strip()}%"
            month_value = (month or "").strip()
            where = (
                "owner_user_id = ? AND (employee_name LIKE ? OR department LIKE ? OR employee_no LIKE ? OR shift_name LIKE ?) "
                "AND (? = '' OR month_label = ?)"
            )
            params = (owner, like, like, like, like, month_value, month_value)
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
                    "WHERE owner_user_id = ? AND TRIM(month_label) <> '' ORDER BY month_label DESC",
                    (owner,),
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
