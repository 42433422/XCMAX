"""Owned label artifacts and durable, single-consumption print confirmations."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterator

from sqlalchemy import text

from app.db.session import get_db
from app.infrastructure.printing.label_dispatch_guard import (
    authorized_label_dispatch,
    label_job_lock,
    write_label_job,
)
from app.infrastructure.printing.template_label_renderer import render_template_label
from app.services.document_templates.crud import _build_template_payload_from_row
from app.utils.operational_errors import BOUNDARY_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir


class LabelJobError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class LabelJobService:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(get_app_data_dir()) / "label_jobs"

    def _directory(self, owner: tuple[int, int], job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise LabelJobError("标签任务不存在", 404)
        path = self.root
        for part in (str(owner[0]), str(owner[1]), job_id):
            path = path / part
            if path.is_symlink():
                raise LabelJobError("标签任务路径无效", 404)
        if self.root.is_symlink():
            raise LabelJobError("标签目录无效", 404)
        return path

    def _read(self, owner: tuple[int, int], job_id: str) -> tuple[Path, dict]:
        directory = self._directory(owner, job_id)
        manifest = directory / "job.json"
        if manifest.is_symlink() or not manifest.is_file():
            raise LabelJobError("标签任务不存在", 404)
        job = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            job.get("tenant_id") != owner[0]
            or job.get("user_id") != owner[1]
            or job.get("id") != job_id
        ):
            raise LabelJobError("标签任务不存在", 404)
        return directory, job

    @staticmethod
    def _write(directory: Path, job: dict) -> None:
        write_label_job(directory, job)

    @contextmanager
    def _locked(self, owner: tuple[int, int], job_id: str) -> Iterator[tuple[Path, dict]]:
        directory, _ = self._read(owner, job_id)
        try:
            with label_job_lock(directory):
                yield self._read(owner, job_id)
        except OSError as exc:
            raise LabelJobError("标签任务正在处理，请稍后刷新状态；不要重复提交", 409) from exc

    @staticmethod
    def public(job: dict) -> dict:
        keys = (
            "id",
            "status",
            "message",
            "product_id",
            "product_name",
            "template_id",
            "template_name",
            "copies",
            "paper_width_mm",
            "paper_height_mm",
            "printer",
            "run_id",
        )
        return {key: job[key] for key in keys if key in job}

    def get(self, owner: tuple[int, int], job_id: str) -> dict:
        return self.public(self._read(owner, job_id)[1])

    def products(self, owner: tuple[int, int], keyword: str, page: int, per_page: int) -> dict:
        from sqlalchemy import func, or_, select

        from app.db.models.product import Product

        table = Product.__table__
        conditions = [table.c.tenant_id == owner[0], table.c.is_active == 1]
        if keyword.strip():
            conditions.append(
                or_(
                    table.c.name.icontains(keyword.strip(), autoescape=True),
                    table.c.model_number.icontains(keyword.strip(), autoescape=True),
                )
            )
        with get_db() as db:
            total = db.execute(
                select(func.count()).select_from(table).where(*conditions)
            ).scalar_one()
            rows = (
                db.execute(
                    select(table.c.id, table.c.name, table.c.model_number, table.c.specification)
                    .where(*conditions)
                    .order_by(table.c.id)
                    .limit(per_page)
                    .offset((page - 1) * per_page)
                )
                .mappings()
                .all()
            )
        return {
            "success": True,
            "data": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    def generate(self, owner: tuple[int, int], payload: dict) -> dict:
        product_id = payload["product_id"]
        raw_template = str(payload["template_id"])
        if not re.fullmatch(r"(?:db:)?[1-9][0-9]*", raw_template):
            raise LabelJobError("请选择已保存的标签模板")
        template_id = int(raw_template.removeprefix("db:"))
        with get_db() as db:
            # Explicit strict ownership also applies during legacy-null migration mode.
            product_row = (
                db.execute(
                    text(
                        "SELECT id, name, model_number, specification, price, unit, brand, category, description, quantity FROM products WHERE id=:id AND tenant_id=:tenant AND is_active=1"
                    ),
                    {"id": product_id, "tenant": owner[0]},
                )
                .mappings()
                .first()
            )
            template_row = (
                db.execute(
                    text(
                        "SELECT * FROM templates WHERE id=:id AND tenant_id=:tenant AND is_active=1"
                    ),
                    {"id": template_id, "tenant": owner[0]},
                )
                .mappings()
                .first()
            )
        if product_row is None:
            raise LabelJobError("产品不存在或当前租户不可访问", 404)
        if template_row is None:
            raise LabelJobError("标签模板不存在或当前租户不可访问", 404)
        product = {
            key: value if isinstance(value, (int, float, str, type(None))) else str(value)
            for key, value in product_row.items()
        }
        template = _build_template_payload_from_row(SimpleNamespace(**dict(template_row)))
        preview = template.get("preview_data") or {}
        paper = preview.get("paper_size") or preview.get("layout") or {}
        if isinstance(paper, dict):
            saved_width = paper.get("width_mm", paper.get("paper_width_mm"))
            saved_height = paper.get("height_mm", paper.get("paper_height_mm"))
            if saved_width is not None or saved_height is not None:
                try:
                    matches = (
                        abs(float(str(saved_width)) - payload["paper_width_mm"]) < 0.01
                        and abs(float(str(saved_height)) - payload["paper_height_mm"]) < 0.01
                    )
                except (ValueError, TypeError) as exc:
                    raise LabelJobError("模板保存的纸张尺寸无效") from exc
                if not matches:
                    raise LabelJobError("所选纸张尺寸与模板保存尺寸不一致，请重新加载模板")
        job_id = uuid.uuid4().hex
        directory = self._directory(owner, job_id)
        directory.mkdir(parents=True, mode=0o700)
        job = {
            "id": job_id,
            "tenant_id": owner[0],
            "user_id": owner[1],
            "product_id": product_id,
            "product_name": product["name"],
            "template_id": template["id"],
            "template_name": template["name"],
            "copies": payload["copies"],
            "paper_width_mm": payload["paper_width_mm"],
            "paper_height_mm": payload["paper_height_mm"],
            "status": "generating",
        }
        self._write(directory, job)
        try:
            layout = render_template_label(
                directory / "labels.pdf",
                template,
                product,
                payload["copies"],
                payload["paper_width_mm"],
                payload["paper_height_mm"],
            )
            path = directory / "labels.pdf"
            path.chmod(0o600)
            job.update(
                status="generated",
                message="标签 PDF 已生成，请预览并核对纸张尺寸后确认打印",
                layout=layout,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            self._write(directory, job)
        except (ValueError, OSError) as exc:
            (directory / "labels.pdf").unlink(missing_ok=True)
            job.update(status="generation_failed", message=str(exc))
            self._write(directory, job)
            raise LabelJobError(str(exc)) from exc
        return self.public(job)

    def file(self, owner: tuple[int, int], job_id: str) -> Path:
        directory, job = self._read(owner, job_id)
        path = directory / "labels.pdf"
        if path.is_symlink() or not path.is_file() or not job.get("sha256"):
            raise LabelJobError("标签文件尚未生成或已丢失，请重新生成", 404)
        if hashlib.sha256(path.read_bytes()).hexdigest() != job["sha256"]:
            raise LabelJobError("标签文件校验失败，请重新生成", 409)
        return path

    def confirmation(self, owner: tuple[int, int], job_id: str, printer: str | None) -> dict:
        with self._locked(owner, job_id) as (directory, job):
            self.file(owner, job_id)
            if job["status"] not in {"generated", "failed"}:
                raise LabelJobError("此任务已提交或提交结果待确认，请检查打印队列", 409)
            if not printer:
                raise LabelJobError("未找到标签打印机；可下载 PDF，配置打印机后重试")
            token = secrets.token_urlsafe(32)
            job.update(
                confirm_hash=hashlib.sha256(token.encode()).hexdigest(),
                confirm_expires=time.time() + 300,
                printer=printer,
            )
            self._write(directory, job)
            return {
                "job": self.public(job),
                "confirm_token": token,
                "confirm_prompt": f"将 {job['copies']} 张标签（{job['paper_width_mm']} × {job['paper_height_mm']} mm）提交到【{printer}】。请确认纸张规格与预览内容。",
            }

    def submit(
        self, owner: tuple[int, int], job_id: str, token: str, dispatch: Callable[[dict], dict]
    ) -> dict:
        with self._locked(owner, job_id) as (directory, job):
            if job["status"] in {"submitted", "outcome_unknown", "submitting"}:
                return self.public(job)
            expected = job.pop("confirm_hash", "")
            expires = job.pop("confirm_expires", 0)
            if (
                not expected
                or time.time() > expires
                or not secrets.compare_digest(expected, hashlib.sha256(token.encode()).hexdigest())
            ):
                raise LabelJobError("打印确认已过期或无效，请重新确认", 409)
            path = self.file(owner, job_id)
            credential = secrets.token_urlsafe(32)
            job.update(
                status="submitting",
                message="正在提交打印队列，请勿重复提交",
                dispatch_hash=hashlib.sha256(credential.encode()).hexdigest(),
                dispatch_claimed=False,
            )
            self._write(directory, job)
        # Persist consumption BEFORE calling the side-effectful agent, across processes/restarts.
        # Physical printer adapter boundary: never retry an ambiguous side effect.
        try:
            with authorized_label_dispatch(path, credential):
                result = dispatch(
                    {"file_path": str(path), "printer_name": job["printer"], "copies": 1}
                )
            if result.get("submission_state") == "submitted":
                job.update(status="submitted", message="已提交打印队列；物理出纸仍需现场核对")
            elif result.get("submission_state") == "rejected":
                job.update(
                    status="failed", message=result.get("message") or "打印服务拒绝任务，可重新确认"
                )
            else:
                job.update(
                    status="outcome_unknown",
                    message="提交结果待确认，请先检查打印队列；为避免重复出纸已暂停重试",
                )
            job["run_id"] = result.get("run_id", "")
        except BOUNDARY_ERRORS:
            # An exception after dispatch cannot establish that no pages were queued.
            job.update(
                status="outcome_unknown",
                message="提交结果待确认，请先检查打印队列；为避免重复出纸已暂停重试",
            )
        with self._locked(owner, job_id) as (directory, persisted):
            persisted.update(
                {key: job[key] for key in ("status", "message", "run_id") if key in job}
            )
            self._write(directory, persisted)
        return self.public(persisted)
