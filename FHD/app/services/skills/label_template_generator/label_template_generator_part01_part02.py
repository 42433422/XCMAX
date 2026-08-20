# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module(
        "app.services.skills.label_template_generator.label_template_generator"
    )


def _pair_fields_by_grid(
    text_blocks: list[dict],
    horizontal_lines: list[int],
    vertical_lines: list[int],
    merged_horizontal: list[dict] | None = None,
) -> list[dict[str, _facade().Any]]:
    """
    基于网格布局智能配对字段（标签 + 值）

    Args:
        text_blocks: OCR 识别的文本块列表
        horizontal_lines: 水平线 Y 坐标列表
        vertical_lines: 垂直线 X 坐标列表
        merged_horizontal: 水平合并单元格列表

    Returns:
        字段列表
    """
    if not text_blocks:
        return []
    if merged_horizontal is None:
        merged_horizontal = []
    text_blocks_sorted = sorted(text_blocks, key=lambda x: x["y_center"])

    def find_cell(x, y, h_lines, v_lines):
        """根据坐标找到单元格索引"""
        row = 0
        for i in range(len(h_lines) - 1):
            if h_lines[i] <= y < h_lines[i + 1]:
                row = i
                break
        col = 0
        for j in range(len(v_lines) - 1):
            if v_lines[j] <= x < v_lines[j + 1]:
                col = j
                break
        return (row, col)

    for block in text_blocks_sorted:
        center_x = block["center"][0]
        center_y = block["center"][1]
        row, col = find_cell(center_x, center_y, horizontal_lines, vertical_lines)
        block["cell_row"] = row
        block["cell_col"] = col

    def group_by_row(blocks, h_lines):
        groups = []
        current_group = []
        current_row = None
        for block in blocks:
            row = block["cell_row"]
            if current_row is None or row == current_row:
                current_group.append(block)
                current_row = row
            else:
                groups.append({"row": current_row, "blocks": current_group})
                current_group = [block]
                current_row = row
        if current_group:
            groups.append({"row": current_row, "blocks": current_group})
        return groups

    row_groups = group_by_row(text_blocks_sorted, horizontal_lines)
    fields = []
    for group in row_groups:
        blocks = group["blocks"]
        blocks_sorted = sorted(blocks, key=lambda x: x["left"])
        row = group["row"]
        row_merges = [m for m in merged_horizontal if m.get("row") == row]
        j = 0
        while j < len(blocks_sorted):
            block = blocks_sorted[j]
            col = block["cell_col"]
            is_in_merged = False
            merged_info = None
            for m in row_merges:
                if m.get("start_col") <= col <= m.get("end_col"):
                    is_in_merged = True
                    merged_info = m
                    break
            if not isinstance(merged_info, dict):
                merged_info = {}
            if is_in_merged and col == merged_info.get("start_col"):
                field_type, field_key = _facade()._classify_field(block["text"])
                fields.append(
                    {
                        "label": block["text"],
                        "value": "",
                        "field_key": field_key,
                        "type": field_type,
                        "position": {
                            "left": block["left"],
                            "top": block["top"],
                            "width": block["width"],
                            "height": block["height"],
                        },
                        "full_text": block["text"],
                        "confidence": block["conf"],
                        "is_merged": True,
                        "merge_cols": int(
                            merged_info.get("end_col", merged_info.get("start_col", 0)) or 0
                        )
                        - int(merged_info.get("start_col", 0) or 0)
                        + 1,
                    }
                )
                skip_count = merged_info.get("end_col", col) - col
                j += skip_count
            elif not is_in_merged:
                if j + 1 < len(blocks_sorted):
                    next_block = blocks_sorted[j + 1]
                    next_col = next_block["cell_col"]
                    next_is_in_merged = False
                    for m in row_merges:
                        if m.get("start_col") <= next_col <= m.get("end_col"):
                            next_is_in_merged = True
                            break
                    if not next_is_in_merged and next_col == col + 1:
                        label_block = block
                        value_block = next_block
                        field_type, field_key = _facade()._classify_field(label_block["text"])
                        fields.append(
                            {
                                "label": label_block["text"],
                                "value": value_block["text"],
                                "field_key": field_key,
                                "type": field_type,
                                "position": {
                                    "left": label_block["left"],
                                    "top": label_block["top"],
                                    "width": label_block["width"],
                                    "height": label_block["height"],
                                },
                                "full_text": f"{label_block['text']}: {value_block['text']}",
                                "confidence": (label_block["conf"] + value_block["conf"]) / 2,
                                "is_merged": False,
                            }
                        )
                        j += 1
                    else:
                        field_type, field_key = _facade()._classify_field(block["text"])
                        fields.append(
                            {
                                "label": block["text"],
                                "value": "",
                                "field_key": field_key,
                                "type": field_type,
                                "position": {
                                    "left": block["left"],
                                    "top": block["top"],
                                    "width": block["width"],
                                    "height": block["height"],
                                },
                                "full_text": block["text"],
                                "confidence": block["conf"],
                                "is_merged": False,
                            }
                        )
                else:
                    field_type, field_key = _facade()._classify_field(block["text"])
                    fields.append(
                        {
                            "label": block["text"],
                            "value": "",
                            "field_key": field_key,
                            "type": field_type,
                            "position": {
                                "left": block["left"],
                                "top": block["top"],
                                "width": block["width"],
                                "height": block["height"],
                            },
                            "full_text": block["text"],
                            "confidence": block["conf"],
                            "is_merged": False,
                        }
                    )
            j += 1
    return fields


def _classify_field(label: str) -> tuple[str, str]:
    """
    判断字段类型（固定标签 or 可变数据）和字段 key

    Returns:
        (field_type, field_key)
    """
    common_labels = {
        "品名": "product_name",
        "颜色": "color",
        "货号": "item_number",
        "码段": "code_segment",
        "等级": "grade",
        "执行标准": "standard",
        "统一零售价": "price",
        "产品名称": "product_name",
        "产品编号": "product_number",
        "规格": "specification",
        "型号": "model",
        "价格": "price",
        "零售价": "price",
        "生产日期": "production_date",
        "保质期": "shelf_life",
        "产品规格": "product_spec",
        "检验员": "inspector",
    }
    if label in common_labels:
        return ("fixed_label", common_labels[label])
    elif label.endswith("价"):
        return ("fixed_label", "price")
    else:
        return ("dynamic", label)


def _identify_fields(text_blocks: list[dict]) -> list[dict[str, _facade().Any]]:
    """
    识别文本块中的字段（固定标签和可变数据）

    常见固定标签模式：
    - 品名：、颜色：、货号：、码段：、等级：、执行标准：、统一零售价：
    - 产品名称、产品编号、规格、型号、等级
    - 无冒号格式：产品编号 6808AA、产品名称 PE 封固底漆稀料
    """
    fields = []
    common_labels = {
        "品名": "product_name",
        "颜色": "color",
        "货号": "item_number",
        "码段": "code_segment",
        "等级": "grade",
        "执行标准": "standard",
        "统一零售价": "price",
        "产品名称": "product_name",
        "产品编号": "product_number",
        "规格": "specification",
        "型号": "model",
        "价格": "price",
        "零售价": "price",
        "生产日期": "production_date",
        "保质期": "shelf_life",
        "产品规格": "product_spec",
        "检验员": "inspector",
    }
    for block in text_blocks:
        text = block["text"]
        match = _facade().re.match("^([^:：]+)[:：]\\s*(.*)$", text)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()
            field_type = "dynamic"
            if label in common_labels:
                field_key = common_labels[label]
                field_type = "fixed_label"
            elif label.endswith("价"):
                field_key = "price"
                field_type = "fixed_label"
            else:
                field_key = label
            fields.append(
                {
                    "label": label,
                    "value": value,
                    "field_key": field_key,
                    "type": field_type,
                    "position": {
                        "left": block["left"],
                        "top": block["top"],
                        "width": block["width"],
                        "height": block["height"],
                    },
                    "full_text": text,
                    "confidence": block["conf"],
                }
            )
        else:
            for known_label in common_labels:
                if text.startswith(known_label):
                    value_part = text[len(known_label) :].strip()
                    if value_part:
                        field_key = common_labels[known_label]
                        fields.append(
                            {
                                "label": known_label,
                                "value": value_part,
                                "field_key": field_key,
                                "type": "fixed_label"
                                if known_label
                                in [
                                    "产品名称",
                                    "产品编号",
                                    "规格",
                                    "生产日期",
                                    "保质期",
                                    "产品规格",
                                    "检验员",
                                ]
                                else "dynamic",
                                "position": {
                                    "left": block["left"],
                                    "top": block["top"],
                                    "width": block["width"],
                                    "height": block["height"],
                                },
                                "full_text": text,
                                "confidence": block["conf"],
                            }
                        )
                    break
    return fields
