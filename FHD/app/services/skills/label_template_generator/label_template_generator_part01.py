# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.services.skills.label_template_generator.label_template_generator')

def analyze_image(image_path: str, verbose: bool=False) -> dict[str, _facade().Any]:
    """
    分析图片并提取基本信息

    Args:
        image_path: 图片文件路径
        verbose: 是否输出详细信息

    Returns:
        包含图片分析结果的字典
    """
    img: _facade().Image.Image | None = None
    try:
        img = _facade().Image.open(image_path)
        (width, height) = img.size
        result = {'success': True, 'file': _facade().Path(image_path).name, 'format': img.format, 'mode': img.mode, 'size': {'width': width, 'height': height}, 'colors': _facade()._analyze_colors(img), 'sections': _facade()._estimate_sections(width, height)}
        if verbose:
            result['additional_info'] = {'dpi': img.info.get('dpi', 'unknown'), 'has_transparency': img.mode in ('RGBA', 'LA'), 'estimated_font_sizes': _facade()._estimate_font_sizes(width, height)}
        return result
    except FileNotFoundError:
        return {'success': False, 'message': f'文件不存在：{image_path}'}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error('分析图片失败：%s', e)
        return {'success': False, 'message': f'分析失败：{str(e)}'}
    finally:
        if img is not None:
            img.close()

def extract_text_with_ocr(image_path: str, use_regions: bool=True) -> dict[str, _facade().Any]:
    """
    使用 PaddleOCR 提取图片中的文本，并识别固定标签和可变数据

    Args:
        image_path: 图片文件路径
        use_regions: 是否使用分区域识别（提高准确率）
    """
    img: _facade().Image.Image | None = None
    try:
        import cv2
        import numpy as np
        img = _facade().Image.open(image_path)
        (width, height) = img.size
        img_array = np.array(img)
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        (_, binary) = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
        horizontal_lines = []
        for y in range(gray.shape[0]):
            row = binary[y, :]
            continuous_start = None
            max_continuous_length = 0
            current_length = 0
            for x in range(len(row)):
                if row[x] > 0:
                    if continuous_start is None:
                        continuous_start = x
                    current_length += 1
                else:
                    if current_length > max_continuous_length:
                        max_continuous_length = current_length
                    continuous_start = None
                    current_length = 0
            if current_length > max_continuous_length:
                max_continuous_length = current_length
            if max_continuous_length > gray.shape[1] * 0.5:
                horizontal_lines.append(y)
        vertical_lines = []
        for x in range(gray.shape[1]):
            col = binary[:, x]
            continuous_start = None
            max_continuous_length = 0
            current_length = 0
            for y in range(len(col)):
                if col[y] > 0:
                    if continuous_start is None:
                        continuous_start = y
                    current_length += 1
                else:
                    if current_length > max_continuous_length:
                        max_continuous_length = current_length
                    continuous_start = None
                    current_length = 0
            if current_length > max_continuous_length:
                max_continuous_length = current_length
            if max_continuous_length > gray.shape[0] * 0.5:
                vertical_lines.append(x)
        horizontal_lines = sorted({int(y) for y in horizontal_lines})
        vertical_lines = sorted({int(x) for x in vertical_lines})

        def merge_close_lines(lines, threshold=50):
            if not lines:
                return []
            merged = [lines[0]]
            for line in lines[1:]:
                if line - merged[-1] > threshold:
                    merged.append(line)
            return merged

        def merge_very_close_lines(lines, threshold=5):
            if not lines:
                return []
            merged = [lines[0]]
            for line in lines[1:]:
                if line - merged[-1] > threshold:
                    merged.append(line)
                else:
                    merged[-1] = (merged[-1] + line) // 2
            return merged
        horizontal_lines = merge_very_close_lines(horizontal_lines, threshold=5)
        vertical_lines = merge_very_close_lines(vertical_lines, threshold=5)
        horizontal_lines = merge_close_lines(horizontal_lines, threshold=50)
        vertical_lines = merge_close_lines(vertical_lines, threshold=50)
        _facade().logger.info('检测到网格：%s条水平线，%s条垂直线', len(horizontal_lines), len(vertical_lines))
        from app.services.ocr_service import get_ocr_service
        ocr_svc = get_ocr_service()
        text_blocks = ocr_svc.recognize_text_blocks(img)
        if not text_blocks:
            return {'success': False, 'message': 'OCR 未识别到文本。请安装 paddlepaddle+paddleocr（推荐）或 easyocr，并检查图片清晰度。', 'fallback_fields': _facade()._extract_fields_by_pattern(image_path)}
        _facade().logger.info('OCR 识别到 %s 个文本块（引擎：%s）', len(text_blocks), ocr_svc.get_active_ocr_backend())
        cells: list[dict[str, _facade().Any]] = []
        merged_cells: list[dict[str, _facade().Any]] = []
        if len(horizontal_lines) > 1 and len(vertical_lines) > 1:
            rows = len(horizontal_lines) - 1
            cols = len(vertical_lines) - 1
            for i in range(rows):
                for j in range(cols):
                    x = vertical_lines[j]
                    y = horizontal_lines[i]
                    w = vertical_lines[j + 1] - vertical_lines[j]
                    h = horizontal_lines[i + 1] - horizontal_lines[i]
                    cell = {'row': i, 'col': j, 'x': x, 'y': y, 'width': w, 'height': h, 'should_merge_right': False}
                    if j < cols - 1:
                        right_border_x = x + w
                        border_black_count = 0
                        border_total = 0
                        for check_y in range(y, y + h):
                            if check_y < gray.shape[0] and right_border_x < gray.shape[1]:
                                border_total += 1
                                if binary[check_y, right_border_x] > 0:
                                    border_black_count += 1
                        if border_total > 0 and 0 < border_black_count < h * 0.5:
                            cell['should_merge_right'] = True
                    cells.append(cell)
            merged_cells = []
            visited = set()
            for i in range(rows):
                for j in range(cols):
                    cell_id = f'{i},{j}'
                    if cell_id in visited:
                        continue
                    cell = next((c for c in cells if c['row'] == i and c['col'] == j), {})
                    if not cell:
                        continue
                    merge_count = 1
                    while cell['should_merge_right'] and j + merge_count < cols:
                        visited.add(f'{i},{j + merge_count}')
                        merge_count += 1
                        if j + merge_count < cols:
                            next_cell = next((c for c in cells if c['row'] == i and c['col'] == j + merge_count), None)
                            if next_cell:
                                cell = next_cell
                            else:
                                break
                    merged_cells.append({'row': i, 'start_col': j, 'end_col': j + merge_count - 1, 'merge_cols': merge_count, 'x': vertical_lines[j], 'y': horizontal_lines[i], 'width': vertical_lines[j + merge_count] - vertical_lines[j], 'height': horizontal_lines[i + 1] - horizontal_lines[i], 'original_cols': list(range(j, j + merge_count))})
                    visited.add(cell_id)
        merged_cells_info = []
        for mc in merged_cells:
            if mc.get('start_col', 0) != mc.get('end_col', 0):
                merged_cells_info.append({'row': mc['row'], 'start_col': mc['start_col'], 'end_col': mc['end_col']})
        fields = _facade()._pair_fields_by_grid(text_blocks, horizontal_lines, vertical_lines, merged_cells_info)
        return {'success': True, 'text_blocks': text_blocks, 'fields': fields, 'total_blocks': len(text_blocks), 'grid': {'rows': len(horizontal_lines) - 1 if len(horizontal_lines) > 1 else 0, 'cols': len(vertical_lines) - 1 if len(vertical_lines) > 1 else 0, 'horizontal_lines': horizontal_lines, 'vertical_lines': vertical_lines, 'cells': merged_cells if merged_cells else cells}}
    except ImportError as e:
        _facade().logger.warning('标签模板 OCR 依赖缺失：%s', e)
        return {'success': False, 'message': f'缺少图像处理依赖：{e}（需 Pillow、numpy、opencv-python；OCR 需 paddleocr 或 easyocr）', 'fallback_fields': _facade()._extract_fields_by_pattern(image_path)}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error('OCR 提取失败：%s', e)
        import traceback
        traceback.print_exc()
        return {'success': False, 'message': f'OCR 失败：{str(e)}', 'fallback_fields': _facade()._extract_fields_by_pattern(image_path)}
    finally:
        if img is not None:
            img.close()

def _pair_fields_by_grid(text_blocks: list[dict], horizontal_lines: list[int], vertical_lines: list[int], merged_horizontal: list[dict] | None=None) -> list[dict[str, _facade().Any]]:
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
    text_blocks_sorted = sorted(text_blocks, key=lambda x: x['y_center'])

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
        center_x = block['center'][0]
        center_y = block['center'][1]
        (row, col) = find_cell(center_x, center_y, horizontal_lines, vertical_lines)
        block['cell_row'] = row
        block['cell_col'] = col

    def group_by_row(blocks, h_lines):
        groups = []
        current_group = []
        current_row = None
        for block in blocks:
            row = block['cell_row']
            if current_row is None or row == current_row:
                current_group.append(block)
                current_row = row
            else:
                groups.append({'row': current_row, 'blocks': current_group})
                current_group = [block]
                current_row = row
        if current_group:
            groups.append({'row': current_row, 'blocks': current_group})
        return groups
    row_groups = group_by_row(text_blocks_sorted, horizontal_lines)
    fields = []
    for group in row_groups:
        blocks = group['blocks']
        blocks_sorted = sorted(blocks, key=lambda x: x['left'])
        row = group['row']
        row_merges = [m for m in merged_horizontal if m.get('row') == row]
        j = 0
        while j < len(blocks_sorted):
            block = blocks_sorted[j]
            col = block['cell_col']
            is_in_merged = False
            merged_info = None
            for m in row_merges:
                if m.get('start_col') <= col <= m.get('end_col'):
                    is_in_merged = True
                    merged_info = m
                    break
            if not isinstance(merged_info, dict):
                merged_info = {}
            if is_in_merged and col == merged_info.get('start_col'):
                (field_type, field_key) = _facade()._classify_field(block['text'])
                fields.append({'label': block['text'], 'value': '', 'field_key': field_key, 'type': field_type, 'position': {'left': block['left'], 'top': block['top'], 'width': block['width'], 'height': block['height']}, 'full_text': block['text'], 'confidence': block['conf'], 'is_merged': True, 'merge_cols': int(merged_info.get('end_col', merged_info.get('start_col', 0)) or 0) - int(merged_info.get('start_col', 0) or 0) + 1})
                skip_count = merged_info.get('end_col', col) - col
                j += skip_count
            elif not is_in_merged:
                if j + 1 < len(blocks_sorted):
                    next_block = blocks_sorted[j + 1]
                    next_col = next_block['cell_col']
                    next_is_in_merged = False
                    for m in row_merges:
                        if m.get('start_col') <= next_col <= m.get('end_col'):
                            next_is_in_merged = True
                            break
                    if not next_is_in_merged and next_col == col + 1:
                        label_block = block
                        value_block = next_block
                        (field_type, field_key) = _facade()._classify_field(label_block['text'])
                        fields.append({'label': label_block['text'], 'value': value_block['text'], 'field_key': field_key, 'type': field_type, 'position': {'left': label_block['left'], 'top': label_block['top'], 'width': label_block['width'], 'height': label_block['height']}, 'full_text': f"{label_block['text']}: {value_block['text']}", 'confidence': (label_block['conf'] + value_block['conf']) / 2, 'is_merged': False})
                        j += 1
                    else:
                        (field_type, field_key) = _facade()._classify_field(block['text'])
                        fields.append({'label': block['text'], 'value': '', 'field_key': field_key, 'type': field_type, 'position': {'left': block['left'], 'top': block['top'], 'width': block['width'], 'height': block['height']}, 'full_text': block['text'], 'confidence': block['conf'], 'is_merged': False})
                else:
                    (field_type, field_key) = _facade()._classify_field(block['text'])
                    fields.append({'label': block['text'], 'value': '', 'field_key': field_key, 'type': field_type, 'position': {'left': block['left'], 'top': block['top'], 'width': block['width'], 'height': block['height']}, 'full_text': block['text'], 'confidence': block['conf'], 'is_merged': False})
            j += 1
    return fields

def _classify_field(label: str) -> tuple[str, str]:
    """
    判断字段类型（固定标签 or 可变数据）和字段 key

    Returns:
        (field_type, field_key)
    """
    common_labels = {'品名': 'product_name', '颜色': 'color', '货号': 'item_number', '码段': 'code_segment', '等级': 'grade', '执行标准': 'standard', '统一零售价': 'price', '产品名称': 'product_name', '产品编号': 'product_number', '规格': 'specification', '型号': 'model', '价格': 'price', '零售价': 'price', '生产日期': 'production_date', '保质期': 'shelf_life', '产品规格': 'product_spec', '检验员': 'inspector'}
    if label in common_labels:
        return ('fixed_label', common_labels[label])
    elif label.endswith('价'):
        return ('fixed_label', 'price')
    else:
        return ('dynamic', label)

def _identify_fields(text_blocks: list[dict]) -> list[dict[str, _facade().Any]]:
    """
    识别文本块中的字段（固定标签和可变数据）

    常见固定标签模式：
    - 品名：、颜色：、货号：、码段：、等级：、执行标准：、统一零售价：
    - 产品名称、产品编号、规格、型号、等级
    - 无冒号格式：产品编号 6808AA、产品名称 PE 封固底漆稀料
    """
    fields = []
    common_labels = {'品名': 'product_name', '颜色': 'color', '货号': 'item_number', '码段': 'code_segment', '等级': 'grade', '执行标准': 'standard', '统一零售价': 'price', '产品名称': 'product_name', '产品编号': 'product_number', '规格': 'specification', '型号': 'model', '价格': 'price', '零售价': 'price', '生产日期': 'production_date', '保质期': 'shelf_life', '产品规格': 'product_spec', '检验员': 'inspector'}
    for block in text_blocks:
        text = block['text']
        match = _facade().re.match('^([^:：]+)[:：]\\s*(.*)$', text)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()
            field_type = 'dynamic'
            if label in common_labels:
                field_key = common_labels[label]
                field_type = 'fixed_label'
            elif label.endswith('价'):
                field_key = 'price'
                field_type = 'fixed_label'
            else:
                field_key = label
            fields.append({'label': label, 'value': value, 'field_key': field_key, 'type': field_type, 'position': {'left': block['left'], 'top': block['top'], 'width': block['width'], 'height': block['height']}, 'full_text': text, 'confidence': block['conf']})
        else:
            for known_label in common_labels:
                if text.startswith(known_label):
                    value_part = text[len(known_label):].strip()
                    if value_part:
                        field_key = common_labels[known_label]
                        fields.append({'label': known_label, 'value': value_part, 'field_key': field_key, 'type': 'fixed_label' if known_label in ['产品名称', '产品编号', '规格', '生产日期', '保质期', '产品规格', '检验员'] else 'dynamic', 'position': {'left': block['left'], 'top': block['top'], 'width': block['width'], 'height': block['height']}, 'full_text': text, 'confidence': block['conf']})
                    break
    return fields

def _extract_fields_by_pattern(image_path: str) -> list[dict[str, _facade().Any]]:
    """
    基于常见标签模式提取字段（OCR 不可用时的回退方案）
    """
    return [{'label': '品名', 'value': '（需要 OCR 识别）', 'field_key': 'product_name', 'type': 'fixed_label'}, {'label': '颜色', 'value': '（需要 OCR 识别）', 'field_key': 'color', 'type': 'fixed_label'}, {'label': '货号', 'value': '（需要 OCR 识别）', 'field_key': 'item_number', 'type': 'fixed_label'}, {'label': '码段', 'value': '（需要 OCR 识别）', 'field_key': 'code_segment', 'type': 'fixed_label'}, {'label': '等级', 'value': '（需要 OCR 识别）', 'field_key': 'grade', 'type': 'fixed_label'}, {'label': '执行标准', 'value': '（需要 OCR 识别）', 'field_key': 'standard', 'type': 'fixed_label'}, {'label': '统一零售价', 'value': '（需要 OCR 识别）', 'field_key': 'price', 'type': 'fixed_label'}]

def _analyze_colors(img: _facade().Image.Image) -> dict[str, _facade().Any]:
    """分析图片中的主要颜色"""
    try:
        img_rgb = img.convert('RGB')
        corners = [(10, 10), (img.width - 10, 10), (10, img.height - 10), (img.width - 10, img.height - 10)]
        corner_colors = [img_rgb.getpixel(pos) for pos in corners]
        bg_color = corner_colors[0]
        is_consistent_bg = all((c == bg_color for c in corner_colors))
        return {'background': f'#{bg_color[0]:02x}{bg_color[1]:02x}{bg_color[2]:02x}', 'is_consistent_background': is_consistent_bg, 'border': '#000000', 'text': '#000000'}
    except _facade().RECOVERABLE_ERRORS:
        return {'background': '#FFFFFF', 'is_consistent_background': True, 'border': '#000000', 'text': '#000000'}

def _estimate_sections(width: int, height: int) -> list[dict[str, _facade().Any]]:
    """估算标签的分区"""
    sections = []
    if width >= 800 and height >= 500:
        sections = [{'name': 'product_number', 'y_start': 20, 'y_end': 100, 'description': '产品编号区域'}, {'name': 'product_name', 'y_start': 110, 'y_end': 190, 'description': '产品名称区域'}, {'name': 'ratio', 'y_start': 200, 'y_end': 290, 'description': '参考配比区域'}, {'name': 'date_spec', 'y_start': 300, 'y_end': 380, 'description': '日期和规格区域'}, {'name': 'footer', 'y_start': 390, 'y_end': 460, 'description': '底部提示区域'}]
    elif width >= 400 and height >= 300:
        sections = [{'name': 'header', 'y_start': 20, 'y_end': 80, 'description': '标题区域'}, {'name': 'content', 'y_start': 90, 'y_end': 220, 'description': '内容区域'}, {'name': 'footer', 'y_start': 230, 'y_end': 280, 'description': '底部区域'}]
    else:
        sections = [{'name': 'main', 'y_start': 10, 'y_end': height - 10, 'description': '主内容区域'}]
    return sections

def _estimate_font_sizes(width: int, height: int) -> dict[str, int]:
    """估算字体大小"""
    if width >= 800:
        return {'title': 70, 'label': 40, 'content': 58, 'small': 38}
    elif width >= 400:
        return {'title': 40, 'label': 24, 'content': 32, 'small': 20}
    else:
        return {'title': 24, 'label': 14, 'content': 18, 'small': 12}

def generate_template_code(image_path: str, class_name: str='LabelTemplateGenerator', ocr_result: dict | None=None, verbose: bool=False) -> str:
    """
    从图片生成 Python 模板代码

    Args:
        image_path: 图片文件路径
        class_name: 生成的类名
        ocr_result: OCR 识别结果（可选）
        verbose: 是否生成详细代码

    Returns:
        生成的 Python 代码字符串
    """
    analysis = _facade().analyze_image(image_path, verbose=True)
    if not analysis['success']:
        return f"# Error: {analysis.get('error', '分析失败')}"
    width = analysis['size']['width']
    height = analysis['size']['height']
    colors = analysis['colors']
    if ocr_result and ocr_result.get('success'):
        fields = ocr_result.get('fields', [])
        code = _facade()._generate_code_with_fields(image_path, class_name, width, height, colors, fields)
    else:
        code = _facade()._generate_basic_code(image_path, class_name, width, height, colors)
    return code
