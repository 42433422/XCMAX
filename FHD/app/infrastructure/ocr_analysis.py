"""Pure text-analysis helpers shared by OCR service backends."""

from __future__ import annotations

import re
from typing import Any


class OCRAnalysisMixin:
    """Text cleanup, classification and structured-field extraction."""

    def extract_structured_data(self, text: str) -> dict[str, Any]:
        """从OCR文本中提取结构化数据"""
        structured_data: dict[str, Any] = {
            "purchase_unit": None,
            "contact_person": None,
            "contact_phone": None,
            "purchase_date": None,
            "order_number": None,
            "total_amount": None,
            "products": [],
            "raw_text": text,
        }

        unit_match = re.search(r"购货单位[：:]\s*(.+?)(?:\n|$)", text)
        if unit_match:
            structured_data["purchase_unit"] = unit_match.group(1).strip()

        contact_match = re.search(r"联系人[：:]\s*(.+?)(?:\n|$)", text)
        if contact_match:
            structured_data["contact_person"] = contact_match.group(1).strip()

        phone_match = re.search(r"联系电话[：:]\s*([\d\-\+]+)", text)
        if phone_match:
            structured_data["contact_phone"] = phone_match.group(1).strip()

        date_match = re.search(r"(\d{4}[-年]\d{1,2}[-月]\d{1,2}[日]?)", text)
        if date_match:
            structured_data["purchase_date"] = date_match.group(1)

        order_match = re.search(r"订单编号[：:]\s*(.+?)(?:\n|$)", text)
        if order_match:
            structured_data["order_number"] = order_match.group(1).strip()

        amount_match = re.search(r"合计[：:]\s*([\d\.]+)", text)
        if amount_match:
            try:
                structured_data["total_amount"] = float(amount_match.group(1))
            except ValueError:
                pass

        product_pattern = r"([A-Za-z0-9\-]+)\s+(.+?)\s+(\d+)\s+([\d\.]+)\s+([\d\.]+)"
        for match in re.finditer(product_pattern, text):
            structured_data["products"].append(
                {
                    "model": match.group(1),
                    "name": match.group(2),
                    "quantity": int(match.group(3)),
                    "unit_price": float(match.group(4)),
                    "total_price": float(match.group(5)),
                }
            )

        return structured_data

    def analyze_text(self, text: str) -> dict[str, Any]:
        """分析文本内容"""
        analysis: dict[str, Any] = {
            "text_type": "unknown",
            "confidence": 0.0,
            "detected_fields": {},
            "missing_fields": [],
            "suggestions": [],
        }

        if not text:
            return analysis

        keywords = {
            "order": ["订单", "订购", "下单"],
            "shipment": ["发货", "送货"],
            "payment": ["付款", "支付", "金额", "合计"],
            "product": ["产品", "型号", "规格"],
            "customer": ["客户", "购货单位"],
            "contact": ["联系人", "电话"],
            "date": ["日期", "时间"],
        }
        type_scores = {
            type_name: sum(1 for keyword in values if keyword in text)
            for type_name, values in keywords.items()
        }
        max_type = max(type_scores, key=lambda name: type_scores[name])
        if type_scores[max_type] > 0:
            analysis["text_type"] = max_type
            analysis["confidence"] = min(1.0, type_scores[max_type] / 3)

        field_patterns = {
            "purchase_unit": r"购货单位[：:]\s*(.+?)(?:\n|$)",
            "contact_person": r"联系人[：:]\s*(.+?)(?:\n|$)",
            "phone": r"电话[：:]\s*([\d\-\+]+)",
            "date": r"(\d{4}[年-]\d{1,2}[月-]\d{1,2}[日]?)",
            "order_id": r"订单[编号]?[：:]\s*(.+?)(?:\n|$)",
            "total": r"合计[：:]\s*([\d\.]+)",
        }
        for field, pattern in field_patterns.items():
            match = re.search(pattern, text)
            if match:
                value = match.group(1) if match.lastindex else match.group(0)
                analysis["detected_fields"][field] = value.strip()

        for field in ("purchase_unit", "contact_person", "date"):
            if field not in analysis["detected_fields"]:
                analysis["missing_fields"].append(field)
        if analysis["text_type"] == "unknown":
            analysis["suggestions"].append("文本类型不明确，请手动确认")
        return analysis

    def _clean_text(self, text: str) -> str:
        """清理识别出的文字"""
        if not text:
            return ""
        return "\n".join(line.strip() for line in text.split("\n") if line.strip())

    def _classify_text(self, text: str) -> str:
        """分类文本类型"""
        if not text:
            return "unknown"
        if any(
            re.search(pattern, text)
            for pattern in (r"\d{4}[-年]\d{1,2}[-月]\d{1,2}", r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}")
        ):
            return "date"
        if any(
            re.search(pattern, text)
            for pattern in (r"[\d\.]+\s*(元|¥|dollar|\$|€)", r"[$¥€]\s*[\d\.]+")
        ):
            return "amount"
        if re.match(r"^[\d\-\+\(\)]{7,}$", text):
            return "phone"
        if re.match(r"^[\d\.\,\-\+]+$", text):
            return "number"
        return "text"
