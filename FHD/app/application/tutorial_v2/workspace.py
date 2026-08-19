"""Workspace ownership and reporting helpers for Tutorial V2."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.application.tutorial_v2.catalog import COURSE_BY_ID
from app.application.tutorial_v2.common import TutorialServiceError
from app.application.tutorial_v2.common import utcnow as _now
from app.db.models.inventory import InventoryLedger, Warehouse
from app.db.models.product import Product
from app.db.models.tenant import Tenant
from app.db.models.tutorial import TutorialRun, TutorialWorkspace
from app.db.models.user import User
from app.infrastructure.tenant_scope import tenant_scope


class TutorialWorkspaceMixin:
    if TYPE_CHECKING:
        _run_dto: Any

    def _owner(self, user: Any) -> tuple[int, int]:
        user_id = getattr(user, "id", None)
        source_tenant_id = getattr(user, "tenant_id", None)
        if user_id is None:
            raise TutorialServiceError("authentication_required", "请先登录。", 401)
        if source_tenant_id is None:
            raise TutorialServiceError(
                "source_tenant_required", "当前账号尚未加入企业，无法创建教学空间。", 409
            )
        return int(user_id), int(source_tenant_id)

    def _owned_run(self, db: Session, user: Any, run_id: str) -> TutorialRun:
        user_id, source_tenant_id = self._owner(user)
        run = (
            db.query(TutorialRun)
            .filter(
                TutorialRun.id == str(run_id),
                TutorialRun.user_id == user_id,
                TutorialRun.source_tenant_id == source_tenant_id,
            )
            .first()
        )
        if run is None:
            raise TutorialServiceError("tutorial_run_not_found", "未找到该课程运行。", 404)
        return cast(TutorialRun, run)

    def _active_workspace(self, db: Session, user: Any) -> TutorialWorkspace | None:
        user_id, source_tenant_id = self._owner(user)
        return cast(
            TutorialWorkspace | None,
            db.query(TutorialWorkspace)
            .filter(
                TutorialWorkspace.user_id == user_id,
                TutorialWorkspace.source_tenant_id == source_tenant_id,
                TutorialWorkspace.status == "active",
            )
            .order_by(TutorialWorkspace.generation.desc())
            .first(),
        )

    def _new_workspace(self, db: Session, user: Any) -> TutorialWorkspace:
        user_id, source_tenant_id = self._owner(user)
        generation = (
            int(
                db.query(func.max(TutorialWorkspace.generation))
                .filter(
                    TutorialWorkspace.user_id == user_id,
                    TutorialWorkspace.source_tenant_id == source_tenant_id,
                )
                .scalar()
                or 0
            )
            + 1
        )
        token = uuid.uuid4().hex[:12]
        tenant = Tenant(
            code=f"TUT-{source_tenant_id}-{user_id}-{token}",
            name=f"教学空间 · {user_id} · 第 {generation} 代",
            is_active=True,
            created_at=_now(),
        )
        db.add(tenant)
        db.flush()
        workspace = TutorialWorkspace(
            id=str(uuid.uuid4()),
            source_tenant_id=source_tenant_id,
            user_id=user_id,
            tutorial_tenant_id=int(tenant.id),
            active_key=f"{source_tenant_id}:{user_id}",
            generation=generation,
            status="active",
        )
        db.add(workspace)
        db.flush()
        return workspace

    def _ensure_teaching_warehouse(self, db: Session, workspace: TutorialWorkspace) -> Warehouse:
        """Create the shadow tenant's private default warehouse exactly once."""
        tenant_id = int(workspace.tutorial_tenant_id)
        with tenant_scope(tenant_id):
            existing = (
                db.query(Warehouse)
                .filter(Warehouse.status == "active")
                .order_by(Warehouse.id.asc())
                .first()
            )
            if existing is not None:
                return cast(Warehouse, existing)
            warehouse = Warehouse(
                code=f"TUT-{str(workspace.id)[:12]}-WH",
                name="教学默认仓库",
                status="active",
                tenant_id=tenant_id,
                created_at=_now(),
            )
            db.add(warehouse)
            db.flush()
            return warehouse

    def _workspace_or_create(self, db: Session, user: Any) -> TutorialWorkspace:
        return self._active_workspace(db, user) or self._new_workspace(db, user)

    def _ensure_teaching_inventory(self, db: Session, workspace: TutorialWorkspace) -> None:
        """Project the verified tutorial product stock into its private warehouse."""
        tenant_id = int(workspace.tutorial_tenant_id)
        with tenant_scope(tenant_id):
            products = db.query(Product).filter(Product.name == "A 产品").limit(2).all()
            warehouses = db.query(Warehouse).filter(Warehouse.status == "active").limit(2).all()
            if len(products) != 1 or len(warehouses) != 1:
                return
            existing = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.product_id == products[0].id,
                    InventoryLedger.warehouse_id == warehouses[0].id,
                )
                .limit(2)
                .all()
            )
            if existing:
                return
            quantity = Decimal(str(products[0].quantity or 0))
            db.add(
                InventoryLedger(
                    product_id=int(products[0].id),
                    warehouse_id=int(warehouses[0].id),
                    quantity=quantity,
                    available_quantity=quantity,
                    reserved_quantity=Decimal("0"),
                    unit=str(products[0].unit or "个"),
                    tenant_id=tenant_id,
                    created_at=_now(),
                )
            )
            db.flush()

    def _completed_course_ids(self, db: Session, workspace: TutorialWorkspace) -> set[str]:
        return {
            str(row.course_id)
            for row in db.query(TutorialRun)
            .filter(
                TutorialRun.workspace_id == workspace.id,
                TutorialRun.status == "completed",
            )
            .all()
            if row.course_id in COURSE_BY_ID
            and int(row.version) == int(COURSE_BY_ID[row.course_id]["version"])
        }

    def reports(self, db: Session, user: Any) -> list[dict[str, Any]]:
        _user_id, source_tenant_id = self._owner(user)
        role = str(getattr(user, "role", "") or "").strip().lower()
        tier = str(getattr(user, "tier", "") or "").strip().lower()
        if role not in {"owner", "admin", "superadmin", "super_admin"} and tier != "admin":
            raise TutorialServiceError("tutorial_report_forbidden", "仅企业管理员可查看。", 403)
        rows = (
            db.query(TutorialRun)
            .filter(TutorialRun.source_tenant_id == source_tenant_id)
            .order_by(TutorialRun.updated_at.desc())
            .all()
        )
        member_names = {
            int(item.id): str(item.display_name or item.username or f"成员 {item.id}")
            for item in db.query(User).filter(User.id.in_({row.user_id for row in rows})).all()
        }
        return [
            {
                "user_id": row.user_id,
                "user_name": member_names.get(int(row.user_id), f"成员 {row.user_id}"),
                "course_id": row.course_id,
                "status": row.status,
                "progress": self._run_dto(row)["progress"],
                "attempt_count": row.attempt_count,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "evidence_summary": [
                    {
                        "step_id": item.step_id,
                        "status": item.status,
                        "result_code": item.result_code,
                    }
                    for item in row.evidence
                ],
            }
            for row in rows
        ]
