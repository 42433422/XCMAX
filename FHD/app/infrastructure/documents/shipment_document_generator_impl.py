from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

try:
    from PIL import Image, ImageDraw, ImageFont

    _PIL_AVAILABLE = True
    _PIL_IMPORT_ERROR = ""
except ImportError as _pil_import_error:
    Image = None
    ImageDraw = None
    ImageFont = None
    _PIL_AVAILABLE = False
    _PIL_IMPORT_ERROR = str(_pil_import_error)

from app.application.ports.shipment_document_generator import ShipmentDocumentGeneratorPort
from app.db.models import Product
from app.db.session import get_db
from app.domain.shipment.shipment_product_parser import prepare_parsed_products
from app.infrastructure.lookups.purchase_unit_resolver import (
    resolve_purchase_unit,
)
from app.infrastructure.tenant_scope import apply_tenant_filter
from app.legacy.documents.legacy_shipment_document import (
    load_legacy_shipment_document_generator,
)
from app.utils.path_utils import get_app_data_dir, get_base_dir

logger = logging.getLogger(__name__)


def _positive_scope_id(value: Any, *, fallback: str) -> str:
    """Return a filesystem-safe tenant/owner scope without trusting a path."""

    try:
        normalized = int(value) if value is not None else 0
    except (TypeError, ValueError):
        normalized = 0
    return str(normalized) if normalized > 0 else fallback


def _current_label_tenant_id() -> int | None:
    try:
        from app.infrastructure.tenant_scope import current_tenant_id

        return current_tenant_id()
    except (ImportError, TypeError, ValueError, AttributeError):
        return None


def _current_label_owner_user_id() -> int | None:
    """Read the authenticated owner from request context when callers omit it."""

    try:
        from app.infrastructure.request_context import get_current_request

        request = get_current_request()
        value = getattr(getattr(request, "state", None), "user_id", None)
        return int(value) if value is not None else None
    except (ImportError, TypeError, ValueError, AttributeError):
        return None


def _safe_label_run_id(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return uuid.uuid4().hex
    # A run id is an opaque directory component, never an input path.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return cleaned[:96] or uuid.uuid4().hex


def get_shipment_label_output_dir(
    *,
    tenant_id: int | None = None,
    owner_user_id: int | None = None,
    run_id: str | None = None,
) -> tuple[str, str]:
    """Allocate the per-run user-data directory for generated shipment labels.

    Bundled ``resources`` are read-only in signed desktop builds.  Labels are
    business outputs, so they must be isolated by tenant, authenticated owner,
    and generation run under the desktop user-data root instead.
    """

    resolved_tenant_id = tenant_id if tenant_id is not None else _current_label_tenant_id()
    resolved_owner_user_id = (
        owner_user_id if owner_user_id is not None else _current_label_owner_user_id()
    )
    tenant_scope = _positive_scope_id(resolved_tenant_id, fallback="local")
    owner_scope = _positive_scope_id(resolved_owner_user_id, fallback="local")
    label_run_id = _safe_label_run_id(run_id)

    explicit_data_dir = os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_DESKTOP_DATA_DIR")
    if explicit_data_dir:
        explicit_path = Path(explicit_data_dir).expanduser()
        if not explicit_path.is_absolute():
            raise OSError("shipment label user-data directory must be absolute")
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            try:
                resource_root = Path(frozen_root).resolve()
                resolved_explicit = explicit_path.resolve()
                if resolved_explicit == resource_root or resource_root in resolved_explicit.parents:
                    raise OSError(
                        "shipment label user-data directory cannot be inside app resources"
                    )
            except OSError:
                raise
            except (TypeError, ValueError) as exc:
                raise OSError("shipment label user-data directory is invalid") from exc
    app_data_dir = Path(get_app_data_dir()).expanduser()
    # ``XCAGI_DATA_DIR`` is expected to be absolute in packaged desktop mode.
    # Rejecting a relative override avoids silently resolving it against the
    # PyInstaller/Electron executable directory.
    if not app_data_dir.is_absolute():
        raise OSError("shipment label user-data directory must be absolute")
    output_dir = (
        app_data_dir.resolve()
        / "shipment_outputs"
        / "labels"
        / "tenants"
        / tenant_scope
        / "owners"
        / owner_scope
        / "runs"
        / label_run_id
    )
    return str(output_dir), label_run_id


class SimpleLabelGenerator:
    """简单的标签生成器，使用 PIL 直接绘制标签图片"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.width = 900
        self.height = 600
        self.bg_color = (255, 255, 255)
        self.border_color = (0, 0, 0)
        self.text_color = (0, 0, 0)

    def _get_font(self, size: int):
        if not _PIL_AVAILABLE:
            return None
        font_paths = [
            "msyhbd.ttf",
            "simhei.ttf",
            "simsun.ttc",
            "arial.ttf",
            "times.ttf",
        ]
        for font_path in font_paths:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue

        import sys

        if sys.platform == "win32":
            win_fonts = [
                "C:\\Windows\\Fonts\\msyhbd.ttf",
                "C:\\Windows\\Fonts\\simhei.ttf",
                "C:\\Windows\\Fonts\\simsun.ttc",
                "C:\\Windows\\Fonts\\msyh.ttf",
            ]
            for font_path in win_fonts:
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue

        return ImageFont.load_default()

    def generate_label(
        self, product_data: dict[str, Any], order_number: str, label_index: int = 1
    ) -> str | None:
        if not _PIL_AVAILABLE:
            logger.warning("PIL 不可用，跳过标签生成：%s", _PIL_IMPORT_ERROR)
            return None
        try:
            image = Image.new("RGB", (self.width, self.height), self.bg_color)
            draw = ImageDraw.Draw(image)

            draw.rectangle(
                [0, 0, self.width - 1, self.height - 1], outline=self.border_color, width=3
            )

            product_name = product_data.get("name", "") or product_data.get("product_name", "")
            has_ratio = not any(keyword in product_name for keyword in ["剂", "料"])

            y_pn = 25
            h_pn = 70
            y_name = y_pn + h_pn + 20
            h_name = 62

            if has_ratio:
                y_ratio = y_name + h_name + 20
                h_ratio = 94
                y_date = y_ratio + h_ratio + 20
                h_date = 62
                y_spec = y_date + h_date + 20
                h_spec = 62
                y_footer = y_spec + h_spec + 20
            else:
                y_pn = 25
                h_pn = 100
                y_name = y_pn + h_pn
                h_name = 100
                y_date = y_name + h_name
                h_date = 100
                y_spec = y_date + h_date
                h_spec = 100

            label_x = 20
            label_width = 180
            col1_x = 180
            col1_width = 320
            col2_x = 500
            col2_width = 150

            if has_ratio:
                draw.line(
                    [label_x + label_width, y_pn, label_x + label_width, y_spec + h_spec],
                    fill=self.border_color,
                    width=2,
                )
                draw.line(
                    [col2_x + col2_width, y_date, col2_x + col2_width, y_spec + h_spec],
                    fill=self.border_color,
                    width=2,
                )
                draw.line(
                    [col1_x + col1_width, y_date, col1_x + col1_width, y_spec + h_spec],
                    fill=self.border_color,
                    width=2,
                )
            else:
                draw.line(
                    [label_x + label_width, y_pn, label_x + label_width, 599],
                    fill=self.border_color,
                    width=2,
                )
                draw.line(
                    [col2_x + col2_width, y_date, col2_x + col2_width, 599],
                    fill=self.border_color,
                    width=2,
                )

            draw.line([20, y_pn + h_pn, 880, y_pn + h_pn], fill=self.border_color, width=2)
            draw.line([20, y_name + h_name, 880, y_name + h_name], fill=self.border_color, width=2)

            if has_ratio:
                draw.line(
                    [20, y_ratio + h_ratio, 880, y_ratio + h_ratio], fill=self.border_color, width=2
                )

            draw.line([20, y_date + h_date, 880, y_date + h_date], fill=self.border_color, width=2)
            draw.line([20, y_spec + h_spec, 880, y_spec + h_spec], fill=self.border_color, width=2)

            pn_value_font = self._get_font(70)
            draw.text((45, y_pn + 12), "产品编号", font=self._get_font(40), fill=self.text_color)
            pn_value = product_data.get("model_number", "") or product_data.get(
                "product_number", ""
            )
            pn_bbox = draw.textbbox((0, 0), pn_value, font=pn_value_font)
            pn_width = pn_bbox[2] - pn_bbox[0]
            pn_x = 200 + (680 - pn_width) // 2
            draw.text((pn_x, y_pn + 12), pn_value, font=pn_value_font, fill=self.text_color)

            name_value_font = self._get_font(58)
            draw.text((45, y_name + 12), "产品名称", font=self._get_font(40), fill=self.text_color)
            name_bbox = draw.textbbox((0, 0), product_name, font=name_value_font)
            name_width = name_bbox[2] - name_bbox[0]
            name_x = 200 + (680 - name_width) // 2
            draw.text(
                (name_x, y_name + 12), product_name, font=name_value_font, fill=self.text_color
            )

            if has_ratio:
                ratio_label = "参考配比"
                ratio_label_font = self._get_font(32)
                draw.text(
                    (45, y_ratio + 10), ratio_label, font=ratio_label_font, fill=self.text_color
                )
                ratio_text = product_data.get("ratio", "1 : 0.5-0.6 : 0.5-0.8")
                ratio_value_font = self._get_font(38)
                ratio_bbox = draw.textbbox((0, 0), ratio_text, font=ratio_value_font)
                ratio_width = ratio_bbox[2] - ratio_bbox[0]
                ratio_x = 200 + (680 - ratio_width) // 2
                draw.text(
                    (ratio_x, y_ratio + 10), ratio_text, font=ratio_value_font, fill=self.text_color
                )

            date_font = self._get_font(38)
            production_date = datetime.now().strftime("%Y.%m.%d")
            draw.text((45, y_date + 12), "生产日期", font=date_font, fill=self.text_color)
            draw.text((210, y_date + 12), production_date, font=date_font, fill=self.text_color)
            draw.text((520, y_date + 12), "保质期", font=date_font, fill=self.text_color)
            draw.text((670, y_date + 12), "6个月", font=date_font, fill=self.text_color)

            tin_spec = product_data.get("tin_spec", 0)
            product_data.get("quantity_tins", 0)
            specification = f"{tin_spec}±0.1KG/桶" if tin_spec else "20±0.1KG/桶"
            draw.text((45, y_spec + 12), "产品规格", font=date_font, fill=self.text_color)
            draw.text((210, y_spec + 12), specification, font=date_font, fill=self.text_color)
            draw.text((520, y_spec + 12), "检验员", font=date_font, fill=self.text_color)
            draw.text((670, y_spec + 12), "合格", font=date_font, fill=self.text_color)

            if has_ratio:
                footer_text = "请充分搅拌均匀后使用"
                footer_font = self._get_font(48)
                footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
                footer_width = footer_bbox[2] - footer_bbox[0]
                footer_height = footer_bbox[3] - footer_bbox[1]
                footer_x = 20 + (860 - footer_width) // 2
                footer_y = y_footer + (h_spec - footer_height) // 2
                draw.text((footer_x, footer_y), footer_text, font=footer_font, fill=self.text_color)

            os.makedirs(self.output_dir, exist_ok=True)
            safe_name = product_name.replace("/", "_").replace(" ", "_")[:20]
            filename = f"{order_number}_第{label_index}项_{safe_name}.png"
            output_path = os.path.join(self.output_dir, filename)
            image.save(output_path)
            logger.info("标签已生成: %s", output_path)
            return filename

        except RECOVERABLE_ERRORS as e:
            logger.error("生成标签失败: %s", e)
            return None

    def generate_labels_for_order(
        self, order_number: str, products: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        labels = []
        for i, product in enumerate(products, 1):
            filename = self.generate_label(product, order_number, i)
            if filename:
                file_path = os.path.join(self.output_dir, filename)
                labels.append(
                    {
                        "filename": filename,
                        "file_path": file_path,
                        "order_number": order_number,
                        "label_number": str(i),
                    }
                )
        return labels


from app.infrastructure.documents.shipment_document_legacy_adapter import (
    LegacyShipmentDocumentGenerator,
)
